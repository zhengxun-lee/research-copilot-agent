"""HTTP-independent task supervisor and bounded, real event history."""
from collections import deque
from dataclasses import asdict
import threading

from agent import ExecutionBudget
from agent.runtime import TERMINAL


class InspectorHistory:
    def __init__(self, capacity=400):
        self.events = deque(maxlen=capacity)
        self.sequence = 0
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

    def __call__(self, event):
        if event.name == 'checkpoint.requested':
            return
        with self.lock:
            if hasattr(self, 'redact'):
                from dataclasses import replace
                event = replace(event, data=self.redact(event.data))
            self.sequence += 1
            self.events.append({**event.to_dict(), 'sequence': self.sequence})
            self.condition.notify_all()

    def wait(self,after,timeout=1):
        with self.condition:
            if self.sequence<=after:self.condition.wait(timeout)

    def since(self, after):
        with self.lock:
            events = [event for event in self.events if event['sequence'] > after]
            return {'events': events, 'cursor': self.sequence,
                    'gap': bool(self.events and after and after < self.events[0]['sequence'] - 1)}


def attach_inspector(agent):
    with _ATTACH_LOCK:
        if not hasattr(agent, '_inspector'):
            agent._inspector = InspectorHistory()
            if hasattr(agent,'trace'):agent._inspector.redact=agent.trace.redact
            agent._web_lock = threading.Lock()
            agent._web_running = False
            agent._web_error = ''
            agent.event_bus.subscribe('*', lambda event: agent._inspector(event) if agent.last_run and event.run_id==agent.last_run.run_id else None)
    return agent


_ATTACH_LOCK = threading.Lock()


def is_active(agent):
    if getattr(agent, '_web_running', False) or getattr(agent, '_worker_busy', threading.Event()).is_set():
        return True
    context = getattr(agent, 'last_run', None)
    return bool(context and context.state not in TERMINAL)


def hybrid_retrieval_unavailable():
    """Explain why the running embedding provider cannot serve hybrid retrieval."""
    from api_config import EMBEDDING_API_KEY
    from config import RETRIEVAL_ENABLE_EMBEDDING
    if not EMBEDDING_API_KEY:
        return '混合检索需要 Embedding API，请先在设置中配置向量模型的 API 密钥，保存后重启服务。'
    if not RETRIEVAL_ENABLE_EMBEDDING:
        return '混合检索需要启用 Embedding：请在本地配置中设置 retrieval.enable_embedding: true，并重启服务。'
    return ''


def launch(agent, action, payload, prepare=None):
    attach_inspector(agent)
    with agent._web_lock:
        if agent._web_running:
            raise ValueError('Task is already executing')
        if action == 'start':
            if is_active(agent):
                raise ValueError('Resume or cancel the active task first')
            if prepare is not None:
                prepare(agent)
            message = payload.get('message')
            if not isinstance(message, str) or not message.strip() or len(message) > 10000:
                raise ValueError('Message must contain 1–10000 characters')
            limits = payload.get('budget', {})
            if not isinstance(limits, dict):
                raise ValueError('budget must be an object')
            try:
                budget = ExecutionBudget(**{**asdict(agent.budget), **limits})
            except TypeError as exc:
                raise ValueError('Unknown or invalid budget field') from exc
            approvals = payload.get('approval_tools', [])
            if not isinstance(approvals, list) or any(not isinstance(name, str) for name in approvals):
                raise ValueError('approval_tools must be a list of names')
            agent.budget = budget
            mode = payload.get('retrieval_mode')
            if mode is not None and (not isinstance(mode, str) or mode not in {'keyword', 'semantic', 'hybrid', 'vector'}):
                raise ValueError('Unknown retrieval mode')
            if mode in {'hybrid', 'vector'} and hybrid_retrieval_unavailable():
                raise ValueError(hybrid_retrieval_unavailable())
            agent.tool_registry.tools['search_knowledge'].retrieval_mode = mode
            agent.approval_tools = set(approvals)
            operation = lambda: agent.run(message.strip())
        elif action == 'resume':
            if agent.status()['state'] != 'paused':
                raise ValueError('Task is not paused')
            operation = agent.resume
        elif action == 'approve':
            status = agent.status()
            if status['state'] != 'waiting_approval' or status['pending_tool']['id'] != payload.get('call_id'):
                raise ValueError('No matching pending approval')
            if not isinstance(payload.get('approved'), bool):
                raise ValueError('approved must be boolean')
            operation = lambda: agent.approve(payload['call_id'], payload['approved'])
        elif action == 'resolve':
            if agent.status().get('phase') != 'tool_inflight' or not isinstance(payload.get('result'), str):
                raise ValueError('Verified result is required for an interrupted tool')
            operation = lambda: agent.resolve_tool(payload['call_id'], payload['result'])
        else:
            raise ValueError('Unknown task action')
        agent._web_running = True
        agent._web_error = ''
        def work():
            try:
                operation()
            except Exception as exc:
                agent._web_error = str(exc)
            finally:
                agent._web_running = False
        threading.Thread(target=work, daemon=True).start()


def inspector_status(agent, after=0):
    attach_inspector(agent)
    decision = agent.last_route_decision
    if hasattr(agent,'trace') and agent.last_run:
        observed_sequence=agent._inspector.sequence
        if getattr(agent,'_metrics_sequence',None)!=observed_sequence:
            from agent.observability import metrics
            agent._metrics_cache=metrics(agent.trace.store.all_events(agent.last_run.run_id))
            agent._metrics_sequence=observed_sequence
    result = {**agent.status(), **agent._inspector.since(after),
            'query': (getattr(agent, '_task', None) or {}).get('input'),
            'running': agent._web_running, 'worker_error': agent._web_error,
            'model': decision.model_name if decision else '',
            'route': decision.route_name if decision else '',
            'metrics': getattr(agent,'_metrics_cache',None)}

    return agent.trace.redact(result) if hasattr(agent,'trace') else result
