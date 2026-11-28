import json
import time
from http.client import HTTPConnection
from urllib.parse import urlparse

import web_app
from agent import Agent, CheckpointStore
from agent.observability import TraceStore
from test_agent_core import _completion, _message, _route_decision
from test_web_app import http_server, _get, _post_json
from web_runtime import attach_inspector


def install(monkeypatch, tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite")
    monkeypatch.setattr(web_app, "TRACE_STORE", store)
    agent = attach_inspector(
        Agent("sys", checkpoint_store=CheckpointStore(tmp_path / "checkpoints"), trace_store=store)
    )
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message("actual test completion"))
    monkeypatch.setattr(web_app, "create_agent", lambda: agent)
    return agent


def test_live_sse_and_durable_history_have_same_run(http_server, monkeypatch, tmp_path):
    agent = install(monkeypatch, tmp_path)
    code, payload = _post_json(http_server, "/api/tasks/start", {"message": "hello"})
    assert code == 202
    until = time.monotonic() + 3
    while agent.last_run is None or agent._web_running:
        assert time.monotonic() < until
        time.sleep(0.01)
    url = urlparse(http_server)
    conn = HTTPConnection(url.hostname, url.port, timeout=3)
    conn.request("GET", "/api/events?session_id=" + payload["session_id"])
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
    frame = {}
    for _ in range(4):
        line = response.readline().decode()
        if line.startswith("data: "):
            frame = json.loads(line[6:])
            break
    assert frame["run_id"] == agent.last_run.run_id
    assert frame["events"] and frame["metrics"]["ttft_ms"] is None
    conn.close()
    _, history = _get(http_server, "/api/traces")
    assert history["runs"][0]["run_id"] == frame["run_id"]
    _, detail = _get(http_server, "/api/traces/detail?run_id=" + frame["run_id"])
    assert detail["replay_mode"] == "offline"
    assert any(event["name"] == "model.request" for event in detail["events"])


def test_history_export_is_jsonl(http_server, monkeypatch, tmp_path):
    import urllib.request

    agent = install(monkeypatch, tmp_path)
    agent.run("hello")
    with urllib.request.urlopen(http_server + "/api/traces/export?run_id=" + agent.last_run.run_id) as response:
        lines = response.read().decode().splitlines()
    assert all(json.loads(line)["run_id"] == agent.last_run.run_id for line in lines)


def test_invalid_branch_is_rejected_without_model_call(http_server, monkeypatch, tmp_path):
    install(monkeypatch, tmp_path)
    code, _ = _post_json(http_server, "/api/traces/branch", {"run_id": "unknown", "checkpoint_id": "unknown"})
    assert code == 400


def test_safe_branch_endpoint_creates_paused_child_and_reuses_no_write(http_server, monkeypatch, tmp_path):
    from test_agent_core import _tool_call

    store = TraceStore(tmp_path / "traces.sqlite")
    monkeypatch.setattr(web_app, "TRACE_STORE", store)

    def create():
        agent = attach_inspector(
            Agent("sys", checkpoint_store=CheckpointStore(tmp_path / "checkpoints"), trace_store=store)
        )
        agent.model_router.route = lambda _: _route_decision()
        agent.llm.chat = lambda **_: _completion(_message("branch completed"))
        return agent

    monkeypatch.setattr(web_app, "create_agent", create)
    parent = create()
    parent.approval_tools = {"calculator"}
    parent.llm.chat = lambda **_: _completion(
        _message(tool_calls=[_tool_call("a", "calculator", '{"expression":"1+1"}')])
    )
    parent.run("calculate")
    checkpoint = next(c for c in reversed(store.checkpoints(parent.last_run.run_id)) if c["phase"] == "tools")
    code, child = _post_json(
        http_server,
        "/api/traces/branch",
        {
            "run_id": parent.last_run.run_id,
            "checkpoint_id": checkpoint["id"],
            "arguments": {"expression": "9+1"},
            "model": "simple",
        },
    )
    assert code == 201 and child["state"] == "paused" and child["run_id"] != parent.last_run.run_id
    target = web_app.SESSION_STORE.find(child["session_id"])
    assert target.last_run.llm_calls == parent.last_run.llm_calls  # inherited accounting, no new API call
    assert _post_json(http_server, "/api/tasks/resume", {"session_id": child["session_id"]})[0] == 202
    deadline = time.monotonic() + 2
    while target._web_running:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert target.status()["state"] == "waiting_approval"
    assert target.status()["pending_tool"]["arguments"] == {"expression": "9+1"}
