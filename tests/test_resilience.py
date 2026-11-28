from types import SimpleNamespace
import json

import pytest

from agent import Agent, AgentState, ExecutionBudget, CheckpointStore
from agent.recovery import ErrorKind, classify, repair_json
from tools.base import BaseTool
from test_agent_core import _completion, _message, _route_decision, _tool_call


def ready(**kwargs):
    agent = Agent('sys', **kwargs)
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message('done'))
    events = []
    agent.event_bus.subscribe('*', events.append)
    return agent, events


@pytest.mark.parametrize('error,kind', [
    (TimeoutError('slow'), ErrorKind.TIMEOUT),
    (RuntimeError('rate limit'), ErrorKind.RATE_LIMIT),
    (RuntimeError('maximum context length'), ErrorKind.CONTEXT),
    (ValueError('bad config'), ErrorKind.PERMANENT),
    (RuntimeError('connection reset'), ErrorKind.TRANSIENT)])
def test_classification(error, kind):
    assert classify(error) == kind


@pytest.mark.parametrize('limits', [
    {'max_tokens': -1}, {'max_tokens': True}, {'max_cost': 1},
    {'max_cost': float('nan')}, {'warning_ratio': 0}, {'max_seconds': float('inf')},
    {'max_output_tokens': 0}, {'max_repeated_calls': 0}])
def test_invalid_budget(limits):
    with pytest.raises(ValueError):
        ExecutionBudget(**limits)


def test_preflight_token_limit_prevents_request():
    agent, events = ready(budget=ExecutionBudget(max_tokens=2))
    agent.llm.chat = lambda **_: pytest.fail('unfunded request')
    assert 'budget' in agent.run('hi').lower()
    assert agent.last_run.state == AgentState.EXHAUSTED
    assert any(e.name == 'budget.exceeded' for e in events)


def test_actual_usage_replaces_reservation_and_prices_are_used():
    agent, _ = ready(budget=ExecutionBudget(max_tokens=10000, max_cost=1,
                    input_price_per_million=2, output_price_per_million=4))
    response = _completion(_message('done'))
    response.usage = SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25)
    captured = []
    def chat(**kwargs):
        captured.append(kwargs)
        return response
    agent.llm.chat = chat
    assert agent.run('hi') == 'done'
    assert agent.last_run.tokens == 25
    assert agent.last_run.cost == pytest.approx(0.00006)
    assert not agent.last_run.estimated_usage
    assert captured[0]['max_tokens'] == 2048


def test_missing_usage_keeps_reservation_across_checkpoint(tmp_path):
    agent, _ = ready(checkpoint_store=CheckpointStore(tmp_path), budget=ExecutionBudget(max_tokens=10000))
    agent.run('hi')
    restored, _ = ready(checkpoint_store=CheckpointStore(tmp_path))
    restored.restore(agent.last_run.run_id)
    assert restored.last_run.tokens == agent.last_run.tokens > 0
    assert restored.last_run.estimated_usage


def test_cost_limit_prevents_request():
    agent, _ = ready(budget=ExecutionBudget(max_cost=0,
                     input_price_per_million=1, output_price_per_million=1))
    agent.llm.chat = lambda **_: pytest.fail('unfunded request')
    agent.run('hi')
    assert agent.last_run.state == AgentState.EXHAUSTED


def test_provider_usage_over_limit_stops_before_tools():
    agent, _ = ready(budget=ExecutionBudget(max_tokens=5000))
    response = _completion(_message(tool_calls=[_tool_call()]))
    response.usage = SimpleNamespace(prompt_tokens=9000, completion_tokens=5, total_tokens=9005)
    agent.llm.chat = lambda **_: response
    agent.run('hi')
    assert agent.last_run.state == AgentState.EXHAUSTED
    assert agent.last_run.tool_calls == 0
    assert agent.last_run.tokens == 9005


def test_context_overflow_drops_whole_old_turns():
    agent, events = ready()
    agent.memory.add_user_message('old')
    agent.memory.add_assistant_message('old answer')
    attempts = []
    def chat(**kwargs):
        attempts.append(kwargs['messages'])
        if len(attempts) == 1:
            raise RuntimeError('maximum context length exceeded')
        return _completion(_message('recovered'))
    agent.llm.chat = chat
    assert agent.run('new') == 'recovered'
    assert [m['content'] for m in attempts[1] if not m['content'].startswith('Runtime state')] == ['sys', 'new']
    assert any(e.data.get('strategy') == 'context_pressure_offload' for e in events)


def test_query_rewrite_and_local_strategy_switch(monkeypatch):
    from tools import knowledge
    attempts = []
    def search(query, top_k, mode):
        attempts.append((query, mode))
        if len(attempts) < 3:
            return []
        return [{'item': {'content': 'actual matched content', 'title': 'Doc'}, 'score': 1}]
    monkeypatch.setattr(knowledge, 'search', search)
    monkeypatch.setattr(knowledge.KnowledgeSearchTool, '_attach_neighbor_context', lambda self, results, *a: results)
    agent, events = ready()
    responses = iter([_completion(_message(tool_calls=[_tool_call(arguments='{"query":"please find the attention!"}')])),
                      _completion(_message('answer from tool'))])
    agent.llm.chat = lambda **_: next(responses)
    assert agent.run('hi') == 'answer from tool'
    assert attempts == [('please find the attention!', None), ('attention', None), ('attention', 'semantic')]
    assert agent.last_run.tool_calls == 3
    assert any(e.data.get('strategy') == 'retrieval_mode_switch' for e in events)


def test_safe_syntax_and_numeric_argument_correction():
    assert repair_json("{'query': 'x',}") == {'query': 'x'}
    assert repair_json('__import__("os").system("bad")') is None
    agent, events = ready(approval_tools=['search_knowledge'])
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[
        _tool_call(arguments="{'query': ' x ', 'top_k': '3',}")]))
    agent.run('hi')
    assert agent.status()['pending_tool']['arguments'] == {'query': 'x', 'top_k': 3}
    assert agent.last_run.tool_calls == 0


def test_loop_blocking_and_model_upgrade():
    agent, events = ready(budget=ExecutionBudget(max_steps=10, max_repeated_calls=3))
    agent.tool_registry.execute_strict = lambda *args: 'result'
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call()]))
    assert 'loop blocked' in agent.run('hi')
    assert agent.last_run.tool_calls == 1
    assert any(e.data.get('route') == 'complex' for e in events)


def test_budget_warning_downgrades_and_limits_output():
    agent, events = ready(budget=ExecutionBudget(max_steps=1))
    captured = []
    agent.llm.chat = lambda **kwargs: captured.append(kwargs) or _completion(_message('done'))
    assert agent.run('hi') == 'done'
    assert captured[0]['max_tokens'] == 512
    assert any(e.name == 'budget.warning' for e in events)
    assert any(e.data.get('route') == 'simple' for e in events)


def test_side_effect_failure_is_never_replayed():
    class WriteTool(BaseTool):
        name = 'write'
        def __init__(self):
            self.keys = []
        def run(self, **kwargs):
            raise AssertionError('idempotency adapter required')
        def run_idempotent(self, idempotency_key, **kwargs):
            self.keys.append(idempotency_key)
            raise TimeoutError('outcome unknown')
    tool = WriteTool()
    agent, _ = ready()
    agent.tool_registry.register(tool)
    response = _completion(_message(tool_calls=[_tool_call('write1', 'write')]))
    agent.llm.chat = lambda **_: response
    agent.run('hi')
    assert agent.last_run.state == AgentState.WAITING_APPROVAL
    agent.approve('write1')
    assert len(tool.keys) == 1
    # Same logical write is requested again: even another approval cannot replay it.
    agent.approve('write1')
    assert len(tool.keys) == 1
    assert agent.last_run.state == AgentState.FAILED


def test_tool_cost_cap_blocks_dispatch():
    class PaidTool(BaseTool):
        name = 'paid'
        side_effects = False
        cost_per_call = 2.0
        def run(self, **kwargs):
            pytest.fail('unfunded tool was dispatched')
    agent, _ = ready(budget=ExecutionBudget(max_cost=1,
                     input_price_per_million=1, output_price_per_million=1))
    agent.tool_registry.register(PaidTool())
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call('p', 'paid')]))
    agent.run('hi')
    assert agent.last_run.state == AgentState.EXHAUSTED
    assert agent.last_run.tool_calls == 0


def test_unknown_tool_cost_is_rejected_when_cost_limited():
    class UnknownTool(BaseTool):
        name = 'unknown'
        side_effects = False
        def run(self, **kwargs):
            pytest.fail('unpriced tool was dispatched')
    agent, _ = ready(budget=ExecutionBudget(max_cost=1,
                     input_price_per_million=1, output_price_per_million=1))
    agent.tool_registry.register(UnknownTool())
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call('p', 'unknown')]))
    assert 'cost_per_call' in agent.run('hi')
    assert agent.last_run.tool_calls == 0


def test_permanent_api_failure_is_not_retried():
    agent, events = ready()
    attempts = []
    def fail(**kwargs):
        attempts.append(kwargs)
        raise ValueError('API key invalid')
    agent.llm.chat = fail
    agent.run('hi')
    assert len(attempts) == 1
    assert agent.last_run.retries == 0
    assert any(e.data.get('category') == 'permanent' for e in events)


def test_recovery_limit_stops_context_retry():
    agent, _ = ready(budget=ExecutionBudget(max_recoveries=0))
    agent.memory.add_user_message('old')
    agent.memory.add_assistant_message('old')
    attempts = []
    def fail(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError('context length exceeded')
    agent.llm.chat = fail
    agent.run('new')
    assert len(attempts) == 1
    assert agent.last_run.recoveries == 0


def test_completed_task_duration_is_frozen():
    agent, _ = ready()
    agent.run('hi')
    before = agent.budget_snapshot()['used']['seconds']
    agent._task['finished_at'] += 0  # No wall-clock dependence in this assertion.
    assert agent.budget_snapshot()['used']['seconds'] == before
