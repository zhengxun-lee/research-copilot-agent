import pytest

from agent import AbortExecution, Agent, ExecutionBudget, HookManager, Recovery
from agent.runtime import AgentState, BudgetExceeded, RunContext
from test_agent_core import _completion, _message, _route_decision, _tool_call


def ready(**kwargs):
    agent = Agent('sys', **kwargs)
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message('answer'))
    return agent


def test_hooks_and_onion_order_with_removal():
    order = []
    def wrapper(name):
        def middleware(ctx, op, value, next_call):
            order.append(name + '.before')
            result = next_call(value)
            order.append(name + '.after')
            return result
        return middleware
    manager = HookManager([wrapper('a'), wrapper('b')])
    remove = manager.register('run', 'before', lambda ctx, value: order.append('before'))
    manager.register('run', 'after', lambda ctx, value: order.append('after'))
    assert manager.invoke(RunContext(ExecutionBudget()), 'run', 'input', lambda _: 'result') == 'result'
    assert order == ['before', 'a.before', 'b.before', 'b.after', 'a.after', 'after']
    remove()
    remove()


def test_input_and_answer_transform_are_kept_in_memory():
    agent = ready()
    agent.hooks.register('run', 'before', lambda ctx, text: text.strip())
    agent.hooks.register('run', 'after', lambda ctx, answer: answer.upper())
    assert agent.run('  hi  ') == 'ANSWER'
    assert agent.memory.messages[-2]['content'] == 'hi'
    assert agent.memory.messages[-1]['content'] == 'ANSWER'


def test_short_circuit_without_llm_or_tools():
    def middleware(ctx, operation, payload, next_call):
        if operation == 'run':
            return 'local answer'
        return next_call(payload)
    agent = ready(middleware=[middleware])
    assert agent.run('hi') == 'local answer'
    assert agent.last_run.state == AgentState.COMPLETED
    assert agent.last_run.llm_calls == 0
    assert agent.memory.messages[-1]['content'] == 'local answer'


def test_error_hook_recovery_runs_after_hooks():
    manager = HookManager()
    manager.register('tool', 'error', lambda ctx, exc: Recovery('fallback'))
    manager.register('tool', 'after', lambda ctx, value: value.upper())
    def fail(_):
        raise OSError('temporary')
    assert manager.invoke(RunContext(ExecutionBudget()), 'tool', {}, fail) == 'FALLBACK'


def test_control_errors_cannot_be_recovered_by_error_hooks():
    manager = HookManager()
    seen = []
    manager.register('llm', 'error', lambda ctx, exc: seen.append(exc) or Recovery('bypass'))
    def fail(_):
        raise BudgetExceeded('limit')
    with pytest.raises(BudgetExceeded):
        manager.invoke(RunContext(ExecutionBudget()), 'llm', {}, fail)
    assert not seen


def test_call_next_cannot_execute_twice():
    calls = []
    def middleware(ctx, op, payload, next_call):
        next_call(payload)
        return next_call(payload)
    manager = HookManager([middleware])
    with pytest.raises(AbortExecution):
        manager.invoke(RunContext(ExecutionBudget()), 'tool', {}, lambda _: calls.append(1))
    assert calls == [1]


def test_explicit_tool_abort_fails_entire_run():
    agent = ready()
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call()]))
    def policy(ctx, payload):
        raise AbortExecution('tool forbidden')
    agent.hooks.register('tool.prepare', 'before', policy)
    assert 'tool forbidden' in agent.run('hi')
    assert agent.last_run.state == AgentState.FAILED
    assert agent.last_run.tool_calls == 0
    assert len(agent.memory.messages) == 1


def test_prepare_changes_tool_before_human_approval():
    agent = ready(approval_tools=['calculator'])
    responses = iter([_completion(_message(tool_calls=[_tool_call('a', 'calculator', '{"expression":"1"}')])),
                      _completion(_message('done'))])
    agent.llm.chat = lambda **_: next(responses)
    agent.hooks.register('tool.prepare', 'before',
                         lambda ctx, payload: {'name': 'calculator', 'arguments': {'expression': '2+2'}})
    assert 'suspended' in agent.run('hi')
    assert agent.status()['pending_tool']['arguments'] == {'expression': '2+2'}
    assert agent.approve('a') == 'done'
    tool_messages = [m for m in agent.memory.messages if m['role'] == 'tool']
    assert '4' in tool_messages[0]['content']


def test_execution_hook_cannot_rewrite_approved_arguments():
    agent = ready(approval_tools=['calculator'])
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[
        _tool_call('a', 'calculator', '{"expression":"1"}')]))
    agent.hooks.register('tool', 'before',
                         lambda ctx, payload: {'name': 'calculator', 'arguments': {'expression': '99'}})
    agent.run('hi')
    assert 'cannot change' in agent.approve('a')
    assert agent.last_run.tool_calls == 0
    assert agent.last_run.state == AgentState.FAILED


def test_context_is_diagnostic_copy():
    manager = HookManager()
    manager.register('run', 'before', lambda ctx, value: setattr(ctx, 'tool_calls', 100))
    context = RunContext(ExecutionBudget())
    manager.invoke(context, 'run', '', lambda _: 'done')
    assert context.tool_calls == 0


def test_call_next_cannot_be_deferred():
    saved = []
    def middleware(ctx, op, payload, next_call):
        saved.append(next_call)
        return 'short circuit'
    manager = HookManager([middleware])
    assert manager.invoke(RunContext(ExecutionBudget()), 'run', '', lambda _: 'late') == 'short circuit'
    with pytest.raises(AbortExecution):
        saved[0]('payload')
