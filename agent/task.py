"""Resumable program counter and thread-safe cooperative task controls."""
from copy import deepcopy
from dataclasses import asdict
import queue
import contextvars
import json
import threading
import time

from agent.budget import BudgetControls
from agent.recovery import classify, repair_json, correct_arguments
from agent.parser import parse_tool_calls
from agent.runtime import AbortExecution, RequiredSubscriberError, AgentState, BudgetExceeded, ExecutionBudget, RunContext, TERMINAL


class TaskCancelled(Exception):
    pass


class TaskSuspended(Exception):
    pass


class TaskControls(BudgetControls):
    def _init_controls(self, checkpoint_store, approval_tools):
        self.checkpoint_store = checkpoint_store
        self._checkpoint_unsubscribe = None
        if checkpoint_store is not None:
            from agent.subscribers import CheckpointSubscriber
            self._checkpoint_unsubscribe = self.event_bus.subscribe(
                'checkpoint.requested', lambda event: CheckpointSubscriber(checkpoint_store)(event) if self.last_run and event.run_id==self.last_run.run_id else None, required=True)
        self.approval_tools = set(approval_tools)
        self._control_lock = threading.RLock()
        self._pause_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._worker_busy = threading.Event()
        self._task = None

    def _recover(self, strategy, **details):
        if self.last_run.recoveries >= self.budget.max_recoveries:
            return False
        self.last_run.recoveries += 1
        self._emit('recovery.applied', strategy=strategy, **details)
        self._budget_event()
        return True

    def _switch_model(self, route, reason):
        if not self.model_router.enabled:
            return False
        if self._task.get('model_route') == route:
            return False
        decision = self.model_router._decision(route, 1.0, reason)
        if self.last_route_decision and decision.model_name == self.last_route_decision.model_name:
            return False
        self.last_route_decision = decision
        self._task['model_route'] = route
        self._emit('recovery.applied', strategy='model_switch', route=route,
                   model=decision.model_name, reason=reason)
        return True

    def _side_effectful(self, name):
        tool = getattr(self.tool_registry, 'tools', {}).get(name)
        return getattr(tool, 'side_effects', True) if tool is not None else name not in {'search_knowledge', 'calculator', 'summarizer'}

    def status(self):
        with self._control_lock:
            if self.last_run is None:
                return {'state': AgentState.IDLE.value}
            ctx = self.last_run
            return {'run_id': ctx.run_id, 'state': ctx.state.value,
                    'phase': self._task['phase'], 'steps': ctx.steps,
                    'llm_calls': ctx.llm_calls, 'tool_calls': ctx.tool_calls,
                    'pause_requested': self._pause_requested.is_set(),
                    'cancel_requested': self._cancel_requested.is_set(),
                    'pending_tool': deepcopy(self._pending_call()),
                    'result': self._task.get('result'), 'error': ctx.error,
                    'partial_output': self._task.get('partial_output'),
                    'budget': self.budget_snapshot()}

    def pause(self):
        with self._control_lock:
            self._require_active()
            self._pause_requested.set()

    def cancel(self):
        with self._control_lock:
            self._require_active()
            self._cancel_requested.set()
            if self.last_run.state in {AgentState.PAUSED, AgentState.WAITING_APPROVAL}:
                self._finish_cancel()

    def _require_active(self):
        if self.last_run is None or self.last_run.state in TERMINAL:
            raise ValueError('No active task')

    def _pending_call(self):
        if self._task and self._task['phase'] in {'tools', 'tool_inflight'}:
            calls = self._task['calls']
            index = self._task['index']
            return calls[index] if index < len(calls) else None
        return None

    def _save(self):
        if self.checkpoint_store:
            context = asdict(self.last_run)
            context['state'] = self.last_run.state.value
            context.pop('started_at')
            self._emit('checkpoint.requested', checkpoint={
                'version': 1, 'context': context,
                'elapsed': self.budget_snapshot()['used']['seconds'],
                'messages': self.memory.messages, 'task': self._task,
                'approval_tools': sorted(self.approval_tools),
                'context_engine': {'scope': self.memory.scope, 'window_tokens': self.memory.window_tokens, 'pinned': self.memory.pinned, 'pressure': self.memory.pressure},
                'trace_identity': self.trace.identity(self.last_run.run_id),
            })

    def _boundary(self):
        with self._control_lock:
            if self._cancel_requested.is_set() or self.last_run.state == AgentState.CANCELLED:
                raise TaskCancelled()
            self.last_run.remaining_seconds()
            for resource in ('tokens', 'cost'):
                limit = getattr(self.budget, 'max_' + resource)
                if limit is not None and getattr(self.last_run, resource) >= limit:
                    self._emit('budget.exceeded', resource=resource, **self.budget_snapshot())
                    raise BudgetExceeded(f'{resource} budget exhausted')
            self._budget_event()
            if self._pause_requested.is_set():
                self._task['resume_state'] = self.last_run.state.value
                self._task['suspended_at'] = time.monotonic()
                self._transition(AgentState.PAUSED)
                self._save()
                raise TaskSuspended()

    def _interruptible(self, action):
        """Detach blocking I/O on cancel; never schedule another operation afterward."""
        if self._cancel_requested.is_set():
            raise TaskCancelled()
        results = queue.Queue()
        self._worker_busy.set()
        execution_context = contextvars.copy_context()
        def work():
            try:
                outcome = (True, execution_context.run(action))
            except BaseException as exc:
                outcome = (False, exc)
            self._worker_busy.clear()
            results.put(outcome)
        with self._control_lock:
            if self._cancel_requested.is_set():
                self._worker_busy.clear()
                raise TaskCancelled()
            threading.Thread(target=work, daemon=True).start()
        while True:
            if self._cancel_requested.is_set():
                raise TaskCancelled()
            self.last_run.remaining_seconds()
            try:
                ok, result = results.get(timeout=0.05)
            except queue.Empty:
                continue
            if self._cancel_requested.is_set():
                raise TaskCancelled()
            if not ok:
                raise result
            return result

    def _finish_cancel(self):
        self.memory.messages = deepcopy(self._task['snapshot'])
        self._task['finished_at'] = self._task.get('suspended_at', time.monotonic())
        self._task['result'] = 'Task cancelled.'
        self._transition(AgentState.CANCELLED)
        self._save()
        self._emit('run.cancelled')

    def _run_segment(self, value):
        if self._task['phase'] == 'route':
            if not isinstance(value, str):
                raise AbortExecution('Run input must be a string')
            self._task['input'] = value
            self._save()
        return self._engine()

    def _drive(self):
        try:
            result = self.hooks.invoke(self.last_run, 'run', self._task['input'], self._run_segment)
            if not isinstance(result, str):
                raise AbortExecution('Run hooks must return a string')
            if self._task.get('answer_stored'):
                self.memory.messages[-1]['content'] = result
            elif self._task['phase'] == 'route':
                self.memory.add_user_message(self._task['input'])
                self.memory.add_assistant_message(result)
            with self._control_lock:
                self._boundary()
                self._task['result'] = result
                self._transition(AgentState.COMPLETED)
        except TaskSuspended:
            self._emit('run.suspended')
            return 'Task suspended: ' + self.last_run.state.value
        except TaskCancelled:
            self._finish_cancel()
        except BudgetExceeded as exc:
            self.last_run.error = str(exc)
            if self.last_run.state not in TERMINAL:
                self._transition(AgentState.EXHAUSTED)
            self._emit('budget.exceeded', reason=str(exc), **self.budget_snapshot())
            self._task['result'] = f'Error: {exc}'
        except Exception as exc:
            self.last_run.error = str(exc)
            self._emit('exception.raised', category=classify(exc).value, operation='run', reason=str(exc))
            if self.last_run.state not in TERMINAL:
                self._transition(AgentState.FAILED)
            self._task['result'] = ('Error: ' + str(exc) if str(exc).startswith('LLM ')
                                    else f'Error: Agent execution failed — {exc}')
        if self.last_run.state in {AgentState.FAILED, AgentState.EXHAUSTED}:
            self.memory.messages = deepcopy(self._task['snapshot'])
            self._emit('memory.rolled_back')
        self._task['finished_at'] = time.monotonic()
        self._save()
        self._emit('run.finished', result=self._task.get('result'), error=self.last_run.error,
                   steps=self.last_run.steps, llm_calls=self.last_run.llm_calls,
                   tool_calls=self.last_run.tool_calls)
        return self._task['result']

    def resume(self):
        with self._run_lock:
            with self._control_lock:
                self._require_active()
                if self.last_run.state != AgentState.PAUSED:
                    raise ValueError('Task must be paused; approval requires approve()')
                self._resume_clock()
                self._pause_requested.clear()
                self._transition(AgentState(self._task['resume_state']))
            return self._drive()

    def _resume_clock(self):
        suspended = self._task.pop('suspended_at', None)
        if suspended is not None:
            self.last_run.started_at += time.monotonic() - suspended

    def approve(self, call_id, approved=True):
        with self._run_lock:
            with self._control_lock:
                self._require_active()
                call = self._pending_call()
                if self.last_run.state != AgentState.WAITING_APPROVAL or not call or call['id'] != call_id:
                    raise ValueError('Approval does not match the pending tool call')
                if self._task['phase'] == 'tool_inflight':
                    raise ValueError('Interrupted tool requires resolve_tool(), not automatic replay')
                self._task['approval'] = bool(approved)
                self._resume_clock()
                self._transition(AgentState.EXECUTING)
                self._save()
            return self._drive()

    def resolve_tool(self, call_id, result):
        """Supply a verified result for a tool interrupted by process exit; never replay it."""
        with self._run_lock:
            with self._control_lock:
                self._require_active()
                call = self._pending_call()
                if (self.last_run.state != AgentState.WAITING_APPROVAL or
                        self._task['phase'] != 'tool_inflight' or not call or call['id'] != call_id):
                    raise ValueError('No matching interrupted tool')
                if not isinstance(result, str):
                    raise ValueError('Tool result must be a string')
                self.memory.add_tool_message(call_id, result)
                self._task['index'] += 1
                self._task['phase'] = 'tools'
                self._resume_clock()
                self._transition(AgentState.EXECUTING)
                self._save()
            return self._drive()

    def restore(self, run_id):
        """Load a checkpoint without executing anything. Then resume/approve/resolve."""
        with self._run_lock, self._control_lock:
            if not self.checkpoint_store:
                raise ValueError('Checkpoint store is required')
            if self._worker_busy.is_set() or (self.last_run and self.last_run.state not in TERMINAL):
                raise ValueError('Agent already owns an active task')
            data = self.checkpoint_store.load(run_id)
            context = data['context']
            context['budget'] = ExecutionBudget(**context['budget'])
            context['state'] = AgentState(context['state'])
            self.last_run = RunContext(**context)
            if data.get('trace_identity'):
                self.trace.identities[self.last_run.run_id] = tuple(data['trace_identity'])
                previous_events=self.trace.store.all_events(self.last_run.run_id)
                previous_snapshots=self.trace.store.checkpoints(self.last_run.run_id)
                self.trace.sequence[self.last_run.run_id]=max([0]+[e.get('run_sequence',0) for e in previous_events]+[e['run_sequence'] for e in previous_snapshots])
            self.budget = self.last_run.budget
            self.last_run.started_at = time.monotonic() - data['elapsed']
            self.memory.messages = data['messages']
            if data.get('context_engine'):
                self.memory.scope = data['context_engine']['scope']
                self.memory.window_tokens = data['context_engine']['window_tokens']
                self.memory.pinned = data['context_engine'].get('pinned', [])
                self.memory.pressure = data['context_engine'].get('pressure', False)
            self._task = data['task']
            self.approval_tools |= set(data['approval_tools'])
            self._pause_requested.clear()
            self._cancel_requested.clear()
            if self.last_run.state in TERMINAL:
                self._task['finished_at'] = time.monotonic()
                self._task.pop('suspended_at', None)
            if self.last_run.state not in TERMINAL:
                previous = self.last_run.state
                self._task['suspended_at'] = time.monotonic()
                if self._task['phase'] == 'tool_inflight':
                    self.last_run.state = AgentState.WAITING_APPROVAL
                elif previous != AgentState.WAITING_APPROVAL:
                    self._task['resume_state'] = self._task.get('resume_state', previous.value)
                    self.last_run.state = AgentState.PAUSED
            self._emit('run.restored')
            self._emit('recovery.applied', strategy='checkpoint_restore', phase=self._task['phase'])
            return self.status()

    def _engine(self):
        t = self._task
        while True:
            self._boundary()
            if t['phase'] == 'route':
                decision = self.hooks.invoke(self.last_run, 'route', t['input'],
                                             lambda value: self._interruptible(lambda: self.model_router._decision(t['model_route'],1.0,'explicit branch profile') if t.get('model_route') else self.model_router.route(value)))
                self.last_route_decision = decision
                self._emit('route.completed', model=decision.model_name, route=decision.route_name)
                self.memory.add_user_message(t['input'])
                t['phase'] = 'think'
                self._transition(AgentState.THINKING)
                self._save()
            elif t['phase'] == 'think':
                if self.last_run.steps >= self.budget.max_steps:
                    raise BudgetExceeded(f'Reached maximum reasoning steps ({self.budget.max_steps}) without a final answer.')
                self._consume('steps')
                self._emit('step.started', step=self.last_run.steps)
                t['phase'] = 'llm'
                self._save()
            elif t['phase'] == 'llm':
                # Credentials are resolved afresh after a restart and never persisted.
                decision = self.last_route_decision
                if decision is None:
                    route = t.get('model_route')
                    decision = (self.model_router._decision(route, 1.0, 'restored profile')
                                if route else self.model_router.route(t['input']))
                    self.last_route_decision = decision
                try:
                    response = self._chat(messages=self.memory.get_messages(),
                        tools=None if t.get('conserve') else self.tool_registry.get_tool_specs(), model_name=decision.model_name,
                        api_key=decision.api_key, base_url=decision.base_url)
                except (TaskCancelled, TaskSuspended, BudgetExceeded, RequiredSubscriberError, AbortExecution):
                    raise
                except Exception as exc:
                    if getattr(exc, 'status_code', None) == 401:
                        role = getattr(decision, 'route_name', 'default')
                        profile = {'default': '默认', 'simple': '简单', 'complex': '复杂'}.get(role, '当前')
                        raise RuntimeError(
                            f'LLM 认证失败（401）：{profile}模型的 API Key 无效或已失效。'
                            '请在「设置 → 模型配置」中检查该模型的 API 地址和密钥；'
                            '若使用继承密钥，请更新默认模型的 API Key，保存后重试。'
                        ) from exc
                    raise RuntimeError(f'LLM call failed — {exc}') from exc
                if not response.choices:
                    raise RuntimeError('LLM returned an empty response. Please try again.')
                message = response.choices[0].message
                calls = parse_tool_calls(message)
                if not calls:
                    t['result'] = self._extract_final_text(message)
                    t['phase'] = 'final'
                    self._save()
                    continue
                signature = [[c['name'], json.dumps(c['arguments'], sort_keys=True)
                              if not c.get('parse_error') else c['raw_arguments']] for c in calls]
                t['repeats'] = t['repeats'] + 1 if signature == t.get('last_signature') else 0
                t['last_signature'] = signature
                if t['repeats'] >= self.budget.max_repeated_calls - 1:
                    self._emit('exception.raised', category='tool_loop', operation='tool', reason='Repeated identical batch blocked')
                    raise AbortExecution('Repeated tool call loop blocked')
                if t['repeats'] >= 1:
                    self._switch_model('complex', 'repeated_tool_calls')
                self.memory.add_assistant_message(message.content or '', [
                    {'id': c['id'], 'type': c['type'], 'function': {
                        'name': c['name'], 'arguments': c['raw_arguments']}} for c in calls])
                t.update(phase='tools', calls=calls, index=0)
                self._transition(AgentState.EXECUTING)
                self._save()
            elif t['phase'] == 'tools':
                if t['index'] >= len(t['calls']):
                    if t['repeats'] >= 2:
                        self.memory.append_to_last_assistant('System notice: You have made the same tool call(s) multiple times. Try a different approach or provide your final answer.')
                    t['phase'] = 'think'
                    self._transition(AgentState.THINKING)
                    self._save()
                    continue
                call = self._pending_call()
                if call.get('parse_error'):
                    repaired = repair_json(call['raw_arguments'])
                    self._emit('exception.raised', category='invalid_arguments', operation='tool', reason=call['parse_error'])
                    if repaired is not None and self._recover('argument_syntax_repair'):
                        call['arguments'] = repaired
                        call.pop('parse_error', None)
                if not call.get('prepared') and not call.get('parse_error'):
                    candidate = self.hooks.invoke(self.last_run, 'tool.prepare',
                        {'name': call['name'], 'arguments': correct_arguments(call['name'], call['arguments'])}, lambda value: value)
                    if candidate.get('arguments') != call['arguments']:
                        if not self._recover('argument_correction'):
                            raise AbortExecution('Argument recovery budget exhausted')
                    if (not isinstance(candidate, dict) or set(candidate) != {'name', 'arguments'} or
                            not isinstance(candidate['name'], str) or not isinstance(candidate['arguments'], dict)):
                        raise AbortExecution('tool.prepare must return name and arguments')
                    call.update(deepcopy(candidate))
                    call['raw_arguments'] = json.dumps(call['arguments'], ensure_ascii=False)
                    call['prepared'] = True
                    for message in reversed(self.memory.messages):
                        stored=next((item for item in message.get('tool_calls',[]) if item['id']==call['id']),None)
                        if stored is not None:
                            stored['function']={'name':call['name'],'arguments':call['raw_arguments']}
                            break
                    self._save()
                    self._boundary()
                signature = json.dumps({'name': call['name'], 'arguments': call['arguments']}, sort_keys=True, ensure_ascii=False)
                if call.get('parse_error'):
                    result = f"Error: invalid arguments for '{call['name']}'. {call['parse_error']}"
                elif signature in t['cache']:
                    self._emit('recovery.applied', strategy='tool_cache_hit', name=call['name'])
                    result = 'Repeated tool call skipped. Previous result:\n' + t['cache'][signature]
                else:
                    if (call['name'] in self.approval_tools or self._side_effectful(call['name'])) and 'approval' not in t:
                        t['suspended_at'] = time.monotonic()
                        self._transition(AgentState.WAITING_APPROVAL)
                        self._save()
                        self._emit('approval.requested', call=deepcopy(call))
                        raise TaskSuspended()
                    approved = t.pop('approval', True)
                    if not approved:
                        result = 'Error: tool execution denied by user.'
                    else:
                        self._boundary()
                        state = AgentState.RETRIEVING if call['name'] == 'search_knowledge' else AgentState.EXECUTING
                        if self.last_run.state != state:
                            self._transition(state)
                        if signature in t.get('uncertain_tools', []):
                            raise AbortExecution('Side-effectful tool outcome is uncertain; refusing duplicate execution')
                        if self._side_effectful(call['name']):
                            t.setdefault('uncertain_tools', []).append(signature)
                        t['phase'] = 'tool_inflight'
                        self._save()
                        try:
                            result = self._execute_tool(call['name'], call['arguments'])
                            if not str(result).startswith('Error'):
                                t['cache'][signature] = result
                            if signature in t.get('uncertain_tools', []):
                                t['uncertain_tools'].remove(signature)
                        except (TaskCancelled, TaskSuspended, BudgetExceeded, RequiredSubscriberError, AbortExecution):
                            raise
                        except Exception as exc:
                            self._emit('exception.raised', category=classify(exc, 'tool').value, operation='tool', reason=str(exc))
                            self._emit('tool.failed', name=call['name'], error=str(exc))
                            result = f'Error: tool execution failed. {exc}'
                self.memory.add_tool_message(call['id'], result)
                t['index'] += 1
                t['phase'] = 'tools'
                self._save()
            elif t['phase'] == 'final':
                if not t.get('answer_stored'):
                    self.memory.add_assistant_message(t['result'])
                    t['answer_stored'] = True
                return t['result']
            else:
                raise ValueError('Unsafe execution phase: ' + t['phase'])
