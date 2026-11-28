import threading
import time

import pytest

from agent import Agent, AgentState, CheckpointStore, EventBus
from test_agent_core import _completion, _message, _route_decision, _tool_call


def make(store=None, approval_tools=()):
    agent = Agent('sys', checkpoint_store=store, approval_tools=approval_tools)
    agent.model_router.route = lambda _: _route_decision()
    responses = iter([_completion(_message(tool_calls=[
        _tool_call('a', 'calculator', '{"expression":"1+1"}'),
        _tool_call('b', 'calculator', '{"expression":"2+2"}')
    ])), _completion(_message('done'))])
    agent.llm.chat = lambda **_: next(responses)
    return agent


def test_pause_resume_keeps_tool_queue_and_does_not_replay(tmp_path):
    agent = make(CheckpointStore(tmp_path))
    calls = []
    def completed(e):
        calls.append(e.data['name'])
        if len(calls) == 1:
            agent.pause()
    agent.event_bus.subscribe('tool.completed', completed)
    assert 'suspended' in agent.run('hi')
    assert agent.status()['state'] == 'paused'
    assert agent.status()['pending_tool']['id'] == 'b'
    assert agent.resume() == 'done'
    assert len(calls) == 2
    assert agent.last_run.tool_calls == 2


def test_approval_deny_and_stale_confirmation():
    agent = make(approval_tools=['calculator'])
    assert 'suspended' in agent.run('hi')
    assert agent.last_run.tool_calls == 0
    with pytest.raises(ValueError):
        agent.approve('wrong')
    assert 'suspended' in agent.approve('a', False)
    assert agent.last_run.tool_calls == 0
    assert agent.approve('b') == 'done'
    assert agent.last_run.tool_calls == 1
    assert any('denied' in m['content'] for m in agent.memory.messages if m['role'] == 'tool')


def test_cancel_blocking_llm_returns_promptly_and_no_tools():
    agent = make()
    entered, release = threading.Event(), threading.Event()
    def chat(**_):
        entered.set()
        release.wait(5)
        return _completion(_message(tool_calls=[_tool_call()]))
    agent.llm.chat = chat
    results = []
    thread = threading.Thread(target=lambda: results.append(agent.run('hi')))
    thread.start()
    assert entered.wait(2)
    agent.cancel()
    thread.join(1)
    assert not thread.is_alive()
    assert agent.status()['state'] == 'cancelled'
    assert agent.last_run.tool_calls == 0
    with pytest.raises(ValueError):
        agent.resume()
    release.set()


def test_cancel_on_tool_started_prevents_dispatch():
    agent = make()
    agent.event_bus.subscribe('tool.started', lambda _: agent.cancel())
    agent.tool_registry.execute_strict = lambda *args: pytest.fail('cancelled tool dispatched')
    assert agent.run('hi') == 'Task cancelled.'
    assert agent.last_run.state == AgentState.CANCELLED


def test_restore_approval_in_new_agent(tmp_path):
    store = CheckpointStore(tmp_path)
    first = make(store, ['calculator'])
    first.run('hi')
    run_id = first.last_run.run_id
    second = make(store)
    second.llm.chat = lambda **_: _completion(_message('restored'))
    status = second.restore(run_id)
    assert status['state'] == 'waiting_approval'
    assert 'suspended' in second.approve('a')
    assert second.approve('b') == 'restored'
    assert second.last_run.tool_calls == 2
    assert second.last_run.steps == 2


def test_restore_cancelled_task_cannot_resume(tmp_path):
    store = CheckpointStore(tmp_path)
    first = make(store, ['calculator'])
    first.run('hi')
    first.cancel()
    second = make(store)
    second.restore(first.last_run.run_id)
    with pytest.raises(ValueError):
        second.approve('a')
    with pytest.raises(ValueError):
        second.resume()
    assert second.last_run.tool_calls == 0


def test_restore_interrupted_tool_requires_verified_result(tmp_path):
    store = CheckpointStore(tmp_path)
    first = make(store)
    saved = []
    def capture(event):
        # Mimic a process exit after tool intent was persisted, before result commit.
        saved.append(store.load(first.last_run.run_id))
    first.event_bus.subscribe('tool.started', capture)
    assert first.run('hi') == 'done'
    store.save(first.last_run.run_id, saved[0])
    second = make(store)
    second.llm.chat = lambda **_: _completion(_message('resolved'))
    assert second.restore(first.last_run.run_id)['state'] == 'waiting_approval'
    with pytest.raises(ValueError):
        second.approve('a')
    with pytest.raises(ValueError):
        second.resume()
    assert second.resolve_tool('a', 'verified: 2') == 'resolved'
    assert second.last_run.tool_calls == 2


def test_checkpoint_has_no_api_credentials(tmp_path):
    store = CheckpointStore(tmp_path)
    agent = make(store, ['calculator'])
    decision = _route_decision()
    decision.api_key = 'secret-test-key'
    agent.model_router.route = lambda _: decision
    agent.run('hi')
    assert 'secret-test-key' not in (tmp_path / (agent.last_run.run_id + '.json')).read_text()


def test_pause_before_llm_and_restore_preserves_step_budget(tmp_path):
    store = CheckpointStore(tmp_path)
    first = make(store)
    first.event_bus.subscribe('step.started', lambda _: first.pause())
    first.run('hi')
    assert first.last_run.state == AgentState.PAUSED
    assert first.last_run.steps == 1
    assert first.last_run.llm_calls == 0
    second = make(store)
    second.restore(first.last_run.run_id)
    assert second.resume() == 'done'
    assert second.last_run.steps == 2
    assert second.last_run.llm_calls == 2


def test_cancel_mid_batch_never_runs_second_tool():
    agent = make()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def execute(name, arguments):
        calls.append(name)
        entered.set()
        release.wait(5)
        return 'result'
    agent.tool_registry.execute_strict = execute
    thread = threading.Thread(target=lambda: agent.run('hi'))
    thread.start()
    assert entered.wait(2)
    agent.cancel()
    thread.join(1)
    assert not thread.is_alive()
    release.set()
    assert len(calls) == 1
    assert agent.status()['state'] == 'cancelled'


def test_cancelled_state_is_terminal():
    from agent.runtime import RunContext, ExecutionBudget
    context = RunContext(ExecutionBudget(), state=AgentState.CANCELLED)
    for state in (AgentState.EXECUTING, AgentState.THINKING, AgentState.PAUSED):
        with pytest.raises(ValueError):
            context.transition(state)


def test_checkpoint_restores_in_separate_process(tmp_path):
    import subprocess
    import sys
    first = make(CheckpointStore(tmp_path), ['calculator'])
    first.run('hi')
    script = '''
import sys
from types import SimpleNamespace as NS
from agent import Agent, CheckpointStore
agent = Agent('sys', checkpoint_store=CheckpointStore(sys.argv[1]))
agent.model_router.route = lambda _: NS(model_name='test', api_key=None, base_url=None)
agent.llm.chat = lambda **_: NS(choices=[NS(message=NS(content='resumed in new process'))])
assert agent.restore(sys.argv[2])['state'] == 'waiting_approval'
assert 'suspended' in agent.approve('a')
assert agent.approve('b') == 'resumed in new process'
assert agent.last_run.tool_calls == 2
'''
    subprocess.run([sys.executable, '-c', script, str(tmp_path), first.last_run.run_id],
                   check=True, timeout=10, capture_output=True, text=True)
