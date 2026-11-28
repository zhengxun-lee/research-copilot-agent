from types import SimpleNamespace

import pytest

from agent import Agent
from agent.runtime import AgentState, Event, EventBus, ExecutionBudget, RunContext
from test_agent_core import _completion, _message, _route_decision, _tool_call


def ready(**kwargs):
    agent = Agent('sys', **kwargs)
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message('done'))
    return agent


def test_events_states_and_observer_isolation():
    bus = EventBus()
    events = []
    bus.subscribe('*', events.append)
    bus.subscribe('llm.started', lambda _: 1 / 0)
    agent = ready(event_bus=bus)
    assert agent.run('hi') == 'done'
    assert agent.last_run.state == AgentState.COMPLETED
    assert [e.data['current'] for e in events if e.name == 'state.changed'] == [
        'routing', 'thinking', 'completed']
    assert events[-1].name == 'run.finished'
    assert len({e.run_id for e in events}) == 1


def test_invalid_transition():
    ctx = RunContext(ExecutionBudget())
    with pytest.raises(ValueError):
        ctx.transition(AgentState.COMPLETED)


def test_middleware_order_and_transform():
    order = []
    def hook(ctx, operation, payload, next_call):
        order.append(operation)
        result = next_call(payload)
        return result.upper() if operation == 'run' else result
    agent = ready(middleware=[hook])
    assert agent.run('hi') == 'DONE'
    assert order == ['run', 'route', 'llm']


def test_budget_stops_before_request_and_resets():
    agent = ready(budget=ExecutionBudget(max_llm_calls=0))
    agent.llm.chat = lambda **_: pytest.fail('request must not execute')
    for _ in range(2):
        assert 'budget exhausted' in agent.run('hi')
        assert agent.last_run.state == AgentState.EXHAUSTED
        assert len(agent.memory.messages) == 1


def test_rollback_restores_history_after_window_eviction():
    agent = ready()
    agent.memory.max_turns = 1
    agent.run('old')
    before = agent.memory.get_messages()
    agent.llm.chat = lambda **_: SimpleNamespace(choices=[])
    agent.run('new')
    assert agent.memory.messages == before


def test_transient_retry_counts_attempts(monkeypatch):
    monkeypatch.setattr('agent.core.time.sleep', lambda _: None)
    agent = ready()
    attempts = []
    def chat(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError('connection reset')
        return _completion(_message('recovered'))
    agent.llm.chat = chat
    assert agent.run('hi') == 'recovered'
    assert agent.last_run.llm_calls == 2
    assert agent.last_run.retries == 1
    assert all(a['max_retries'] == 0 for a in attempts)


def test_tool_budget_rolls_back_partial_batch():
    agent = ready(budget=ExecutionBudget(max_tool_calls=1))
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[
        _tool_call('a', 'calculator', '{"expression":"1+1"}'),
        _tool_call('b', 'calculator', '{"expression":"2+2"}')]))
    assert 'tool_calls budget exhausted' in agent.run('hi')
    assert agent.last_run.tool_calls == 1
    assert len(agent.memory.messages) == 1


def test_hook_failure_restores_memory():
    def reject(ctx, operation, payload, next_call):
        if operation == 'llm':
            raise ValueError('blocked')
        return next_call(payload)
    agent = ready(middleware=[reject])
    assert 'blocked' in agent.run('hi')
    assert agent.last_run.state == AgentState.FAILED
    assert len(agent.memory.messages) == 1


def test_timeout_checked_after_blocking_call():
    agent = ready()
    def chat(**_):
        agent.last_run.started_at -= 301
        return _completion(_message('late'))
    agent.llm.chat = chat
    assert 'time budget exhausted' in agent.run('hi')
    assert agent.last_run.state == AgentState.EXHAUSTED


def test_unsubscribe():
    bus = EventBus()
    events = []
    unsubscribe = bus.subscribe('*', events.append)
    unsubscribe()
    unsubscribe()
    bus.publish(Event('test', 'id', AgentState.IDLE))
    assert events == []


def test_failed_tool_is_not_cached_and_model_can_recover():
    agent = ready()
    calls = []
    class Registry:
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            calls.append(name)
            if len(calls) == 1:
                raise RuntimeError('temporary tool failure')
            return 'success'
    agent.tool_registry = Registry()
    response = _completion(_message(tool_calls=[_tool_call()]))
    responses = iter([response, response, _completion(_message('recovered'))])
    agent.llm.chat = lambda **_: next(responses)
    assert agent.run('hi') == 'recovered'
    assert len(calls) == 2
    assert agent.last_run.tool_calls == 2


def test_retry_attempts_respect_llm_budget(monkeypatch):
    monkeypatch.setattr('agent.core.time.sleep', lambda _: None)
    agent = ready(budget=ExecutionBudget(max_llm_calls=1))
    attempts = []
    def fail(**_):
        attempts.append(1)
        raise RuntimeError('connection reset')
    agent.llm.chat = fail
    assert 'llm_calls budget exhausted' in agent.run('hi')
    assert len(attempts) == 1
    assert agent.last_run.state == AgentState.EXHAUSTED
