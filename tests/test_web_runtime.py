import threading
import time

import pytest

import web_app
from agent import Agent, CheckpointStore
from test_agent_core import _completion, _message, _route_decision, _tool_call
from test_web_app import http_server, _post_json, _get
from web_runtime import attach_inspector, InspectorHistory


def install(monkeypatch, tmp_path, chat):
    agent = attach_inspector(Agent('sys', checkpoint_store=CheckpointStore(tmp_path)))
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = chat
    monkeypatch.setattr(web_app, 'create_agent', lambda: agent)
    return agent


def wait_status(base, session_id, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        _, status = _get(base, '/api/tasks/status?session_id=' + session_id)
        if predicate(status):
            return status
        time.sleep(0.01)
    pytest.fail('task did not reach expected state: ' + str(status))


@pytest.mark.parametrize('mode', ['keyword', 'semantic', 'hybrid'])
def test_http_selected_retrieval_reaches_tool(http_server, monkeypatch, tmp_path, mode):
    import api_config
    import config
    monkeypatch.setattr(api_config, 'EMBEDDING_API_KEY', 'fixture-embedding-key')
    monkeypatch.setattr(config, 'RETRIEVAL_ENABLE_EMBEDDING', True)
    from tools import knowledge
    observed = []
    def search(query, top_k, mode):
        observed.append(mode)
        return [{'item': {'content': 'matched', 'title': 'Doc'}, 'score': 1}]
    monkeypatch.setattr(knowledge, 'search', search)
    replies = iter([_completion(_message(tool_calls=[_tool_call(arguments='{"query":"test"}')])),
                    _completion(_message('done'))])
    install(monkeypatch, tmp_path, lambda **_: next(replies))
    code, payload = _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'retrieval_mode': mode})
    assert code == 202
    wait_status(http_server, payload['session_id'], lambda s: s['state'] == 'completed' and not s['running'])
    assert observed == [mode]


def test_http_hybrid_without_embedding_rejected(http_server, monkeypatch, tmp_path):
    import api_config
    monkeypatch.setattr(api_config, 'EMBEDDING_API_KEY', '')
    agent = install(monkeypatch, tmp_path, lambda **_: pytest.fail('request executed'))
    code, body = _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'retrieval_mode': 'hybrid'})
    assert code == 400
    assert 'Embedding API' in body['error']
    assert agent.last_run is None
    _, config = _get(http_server, '/api/config/public')
    assert config['retrieval']['hybrid_available'] is False


def test_http_invalid_retrieval_rejected(http_server, monkeypatch, tmp_path):
    agent = install(monkeypatch, tmp_path, lambda **_: pytest.fail('request executed'))
    assert _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'retrieval_mode': 'invalid'})[0] == 400
    assert agent.last_run is None


def test_http_start_usage_and_event_cursor(http_server, monkeypatch, tmp_path):
    from types import SimpleNamespace
    response = _completion(_message('completed via runtime'))
    response.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12)
    install(monkeypatch, tmp_path, lambda **_: response)
    code, payload = _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'budget': {'max_tokens': 10000}})
    assert code == 202
    status = wait_status(http_server, payload['session_id'], lambda s: s['state'] == 'completed' and not s['running'])
    assert status['result'] == 'completed via runtime'
    assert status['budget']['used']['tokens'] == 12
    assert any(e['name'] == 'budget.updated' for e in status['events'])
    assert not any(e['name'] == 'checkpoint.requested' for e in status['events'])
    _, empty = _get(http_server, '/api/tasks/status?session_id=' + payload['session_id'] + '&after=' + str(status['cursor']))
    assert empty['events'] == []


def test_http_cancel_blocking_request_and_active_session_protection(http_server, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def chat(**kwargs):
        entered.set()
        release.wait(3)
        return _completion(_message('late'))
    agent = install(monkeypatch, tmp_path, chat)
    _, payload = _post_json(http_server, '/api/tasks/start', {'message': 'hi'})
    session_id = payload['session_id']
    assert entered.wait(1)
    assert _post_json(http_server, '/api/session/delete', {'session_id': session_id})[0] == 409
    assert _post_json(http_server, '/api/tasks/start', {'session_id': session_id, 'message': 'duplicate'})[0] == 400
    assert _post_json(http_server, '/api/tasks/cancel', {'session_id': session_id})[0] == 202
    status = wait_status(http_server, session_id, lambda s: s['state'] == 'cancelled')
    assert status['budget']['used']['tool_calls'] == 0
    release.set()


def test_http_approval_pause_resume_and_restore(http_server, monkeypatch, tmp_path):
    responses = iter([_completion(_message(tool_calls=[_tool_call('a', 'calculator', '{"expression":"1+1"}')])),
                      _completion(_message('done'))])
    agent = install(monkeypatch, tmp_path, lambda **_: next(responses))
    _, payload = _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'approval_tools': ['calculator']})
    session_id = payload['session_id']
    status = wait_status(http_server, session_id, lambda s: s['state'] == 'waiting_approval' and not s['running'])
    assert status['pending_tool']['id'] == 'a'
    assert _post_json(http_server, '/api/tasks/approve', {'session_id': session_id, 'call_id': 'wrong', 'approved': True})[0] == 400
    assert _post_json(http_server, '/api/tasks/approve', {'session_id': session_id, 'call_id': 'a', 'approved': True})[0] == 202
    done = wait_status(http_server, session_id, lambda s: s['state'] == 'completed' and not s['running'])
    assert done['result'] == 'done'
    run_id = done['run_id']
    assert _post_json(http_server, '/api/tasks/restore', {'session_id': session_id, 'run_id': run_id})[0] == 202
    assert _post_json(http_server, '/api/tasks/resume', {'session_id': session_id})[0] == 400


@pytest.mark.parametrize('budget', [{'max_cost': 1}, {'max_tokens': -10}, {'max_steps': 'bad'}, {'unknown': 3}])
def test_http_rejects_invalid_budget(http_server, monkeypatch, tmp_path, budget):
    agent = install(monkeypatch, tmp_path, lambda **_: pytest.fail('request executed'))
    code, _ = _post_json(http_server, '/api/tasks/start', {'message': 'hi', 'budget': budget})
    assert code == 400
    assert agent.last_run is None


def test_event_history_is_bounded_and_reports_gaps():
    from agent.runtime import Event, AgentState
    history = InspectorHistory(2)
    for i in range(4):
        history(Event('test', 'a', AgentState.THINKING, {'i': i}))
    result = history.since(1)
    assert result['gap']
    assert [e['data']['i'] for e in result['events']] == [2, 3]


def test_http_pause_at_safe_node_then_resume(http_server, monkeypatch, tmp_path):
    response = _completion(_message('paused final answer'))
    agent = install(monkeypatch, tmp_path, lambda **_: response)
    agent.event_bus.subscribe('llm.completed', lambda _: agent.pause())
    _, payload = _post_json(http_server, '/api/tasks/start', {'message': 'hi'})
    session_id = payload['session_id']
    paused = wait_status(http_server, session_id, lambda s: s['state'] == 'paused' and not s['running'])
    assert paused['phase'] == 'final'
    assert _post_json(http_server, '/api/tasks/resume', {'session_id': session_id})[0] == 202
    done = wait_status(http_server, session_id, lambda s: s['state'] == 'completed' and not s['running'])
    assert done['result'] == 'paused final answer'
    assert done['budget']['used']['llm_calls'] == 1
