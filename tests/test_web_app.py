"""HTTP endpoint tests for ``web_app.ResearchCopilotHandler``.

Uses ``http.server``'s ``ThreadingHTTPServer`` against a real socket on
127.0.0.1 with a random free port so we exercise the actual handler, not a
mocked version."""

import json
import socket
import threading
import urllib.error
import urllib.request
from http.client import HTTPConnection

import pytest

import web_app
from web_app import AgentSessionStore, ResearchCopilotHandler, build_kb_stats_from_items


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------


def test_build_kb_stats_from_items_groups_documents():
    stats = build_kb_stats_from_items([
        {
            "doc_id": "paper-1",
            "title": "Paper One",
            "source_rel_path": "paper-one.pdf",
            "page_number": 1,
        },
        {
            "doc_id": "paper-1",
            "title": "Paper One",
            "source_rel_path": "paper-one.pdf",
            "page_number": 2,
        },
        {
            "doc_id": "paper-2",
            "title": "Paper Two",
            "source_rel_path": "paper-two.pdf",
            "page_number": 1,
        },
    ])

    assert stats["exists"] is True
    assert stats["chunk_count"] == 3
    assert stats["document_count"] == 2
    assert stats["documents"][0]["title"] == "Paper One"
    assert stats["documents"][0]["chunks"] == 2
    assert stats["documents"][0]["page_count"] == 2


def test_build_kb_stats_from_items_handles_zero_and_mixed_page_values():
    stats = build_kb_stats_from_items([
        {
            "doc_id": "paper-1",
            "title": "Paper One",
            "source_rel_path": "paper-one.pdf",
            "page_number": 0,
        },
        {
            "doc_id": "paper-1",
            "title": "Paper One",
            "source_rel_path": "paper-one.pdf",
            "page": "appendix",
        },
    ])

    assert stats["document_count"] == 1
    assert stats["documents"][0]["chunks"] == 2
    assert stats["documents"][0]["page_count"] == 2


def test_agent_session_store_eviction_keeps_recently_used_session(monkeypatch):
    created_agents = []

    def fake_create_agent():
        agent = object()
        created_agents.append(agent)
        return agent

    monkeypatch.setattr(web_app, "create_agent", fake_create_agent)
    store = AgentSessionStore(max_sessions=2)

    first_id, first_agent = store.create()
    second_id, _second_agent = store.create()
    assert store.get_or_create(first_id) == (first_id, first_agent)

    third_id, _third_agent = store.create()

    assert first_id in store._sessions
    assert second_id not in store._sessions
    assert third_id in store._sessions
    assert store.get_or_create(first_id) == (first_id, first_agent)


def test_agent_session_store_get_or_create_with_empty_session_id(monkeypatch):
    """Empty string session_id should not raise UnboundLocalError (regression test)."""
    created_agents = []

    def fake_create_agent():
        agent = object()
        created_agents.append(agent)
        return agent

    monkeypatch.setattr(web_app, "create_agent", fake_create_agent)
    store = AgentSessionStore(max_sessions=2)

    # Empty string is falsy — should create a new session without error.
    new_id, agent = store.get_or_create("")
    assert isinstance(new_id, str) and len(new_id) > 0
    assert new_id in store._sessions

    # None should also create a new session.
    new_id2, _agent2 = store.get_or_create(None)
    assert new_id2 in store._sessions


def test_get_or_create_returns_existing_session(monkeypatch):
    created_agents = []

    def fake_create_agent():
        agent = object()
        created_agents.append(agent)
        return agent

    monkeypatch.setattr(web_app, "create_agent", fake_create_agent)
    store = AgentSessionStore(max_sessions=5)
    session_id, agent = store.create()
    result_id, result_agent = store.get_or_create(session_id)
    assert result_id == session_id
    assert result_agent is agent


# ---------------------------------------------------------------------------
# HTTP endpoint integration tests (real socket, real handler)
# ---------------------------------------------------------------------------


class _StubAgent:
    """Minimal Agent-like object sufficient for ``web_app._handle_chat``."""

    def __init__(self, answer="OK", error=None):
        self._answer = answer
        self._error = error
        self.last_route_decision = type("RD", (), {
            "model_name": "stub-model",
            "route_name": "simple",
        })()

    def run(self, _message):
        if self._error:
            raise self._error
        return self._answer


@pytest.fixture
def http_server(monkeypatch):
    """Spin up a real ThreadingHTTPServer on a random port for the duration of
    a single test.  Returns the base URL (e.g. ``http://127.0.0.1:54321``)."""
    from http.server import ThreadingHTTPServer

    # Reset the session store between tests so they don't bleed into each other.
    monkeypatch.setattr(web_app, "SESSION_STORE", AgentSessionStore())

    # Find a free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = ThreadingHTTPServer(("127.0.0.1", port), ResearchCopilotHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post_json(base_url, path, body, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    request = urllib.request.Request(
        base_url + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _get(base_url, path):
    with urllib.request.urlopen(base_url + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def test_health_endpoint_returns_ok(http_server):
    status, payload = _get(http_server, "/api/health")
    assert status == 200
    assert payload == {"ok": True}


def test_session_create_returns_uuid(http_server):
    status, payload = _post_json(http_server, "/api/session", {})
    assert status == 200
    assert "session_id" in payload
    assert len(payload["session_id"]) >= 16


def test_chat_returns_answer_and_session_id(http_server, monkeypatch):
    monkeypatch.setattr(web_app, "create_agent", lambda: _StubAgent(answer="42"))

    status, payload = _post_json(
        http_server, "/api/chat", {"message": "what is the answer?", "session_id": "x"}
    )
    assert status == 200
    assert payload["answer"] == "42"
    assert payload["session_id"]
    assert payload["model"] == "stub-model"
    assert payload["route"] == "simple"


def test_chat_rejects_empty_message(http_server):
    status, payload = _post_json(http_server, "/api/chat", {"message": ""})
    assert status == 400
    assert "required" in payload["error"].lower()


def test_chat_rejects_missing_content_length(http_server):
    """Send a POST without Content-Length and verify the handler rejects it.

    ``urllib.request`` always sets Content-Length, so we use a raw
    HTTPConnection to exercise the missing-header branch.
    """
    port = int(http_server.rsplit(":", 1)[-1])
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        # chunked body without Content-Length
        conn.putrequest("POST", "/api/chat", skip_host=False, skip_accept_encoding=True)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        body = b"{}"
        conn.send(b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body))
        resp = conn.getresponse()
        assert resp.status == 400
        assert "Content-Length" in resp.read().decode("utf-8")
    finally:
        conn.close()


def test_chat_rejects_oversized_body(http_server):
    """Use a raw connection so we don't depend on urllib's response parsing
    when the server deliberately closes the request after the size check."""
    port = int(http_server.rsplit(":", 1)[-1])
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        big = b"x" * (128 * 1024 + 10)
        conn.request(
            "POST", "/api/chat", body=big,
            headers={"Content-Type": "application/json", "Content-Length": str(len(big))},
        )
        resp = conn.getresponse()
        assert resp.status == 400
        body_text = resp.read().decode("utf-8")
        assert "too large" in body_text.lower()
    finally:
        conn.close()


def test_chat_resets_session_on_agent_failure(http_server, monkeypatch):
    failing = _StubAgent(error=RuntimeError("boom"))
    monkeypatch.setattr(web_app, "create_agent", lambda: failing)

    status, payload = _post_json(http_server, "/api/chat", {"message": "hi"})
    assert status == 500
    assert "boom" in payload["error"]
    # A new session_id should be returned so the client can retry cleanly.
    assert payload["session_id"]


def test_chat_rejects_unknown_route(http_server):
    request = urllib.request.Request(
        http_server + "/api/nonexistent", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_session_reset_creates_fresh_session(http_server, monkeypatch):
    monkeypatch.setattr(web_app, "create_agent", lambda: _StubAgent())

    status, first = _post_json(http_server, "/api/session", {})
    assert status == 200
    first_id = first["session_id"]

    status, second = _post_json(http_server, "/api/session/reset", {"session_id": first_id})
    assert status == 200
    assert second["session_id"]
    assert second["session_id"] != first_id


def test_session_delete_returns_deleted_flag(http_server, monkeypatch):
    monkeypatch.setattr(web_app, "create_agent", lambda: _StubAgent())

    status, first = _post_json(http_server, "/api/session", {})
    sid = first["session_id"]

    status, payload = _post_json(http_server, "/api/session/delete", {"session_id": sid})
    assert status == 200
    assert payload["deleted"] is True


def test_session_delete_returns_false_for_unknown_id(http_server):
    status, payload = _post_json(http_server, "/api/session/delete", {"session_id": "nope"})
    assert status == 200
    assert payload["deleted"] is False


def test_cors_preflight_returns_204(http_server, monkeypatch):
    monkeypatch.setattr(web_app, "WEB_CORS_ORIGIN", "http://localhost:3000")

    conn = HTTPConnection("127.0.0.1", http_server.rsplit(":", 1)[-1])
    try:
        conn.request("OPTIONS", "/api/chat", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        })
        resp = conn.getresponse()
        assert resp.status == 204
        assert resp.getheader("Access-Control-Allow-Origin") == "http://localhost:3000"
        assert resp.getheader("Vary") == "Origin"
    finally:
        conn.close()


def test_kb_document_endpoint_returns_chunks(http_server, tmp_path, monkeypatch):
    """The new ``/api/kb/document/<doc_id>`` endpoint must return chunk metadata."""
    import json
    from retrievers import loader

    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps([
        {
            "doc_id": "paper-x",
            "title": "Paper X",
            "content": "intro text",
            "page_number": 1,
            "chunk_id": "paper-x::chunk-00000",
            "chunk_index": 0,
        },
        {
            "doc_id": "paper-x",
            "title": "Paper X",
            "content": "second page",
            "page_number": 2,
            "chunk_id": "paper-x::chunk-00001",
            "chunk_index": 1,
            "prev_chunk_id": "paper-x::chunk-00000",
        },
    ]), encoding="utf-8")
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    monkeypatch.setattr(web_app, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    status, payload = _get(http_server, "/api/kb/document/paper-x")
    assert status == 200
    assert payload["exists"] is True
    assert payload["chunk_count"] == 2
    assert payload["returned"] == 2
    assert payload["chunks"][0]["chunk_id"] == "paper-x::chunk-00000"


def test_kb_document_endpoint_rejects_unknown_doc(http_server):
    status, payload = _get(http_server, "/api/kb/document/no-such-doc")
    assert status == 200
    assert payload["exists"] is False
    assert payload.get("doc_id") == "no-such-doc"


def test_kb_document_endpoint_rejects_empty_doc_id(http_server):
    """``/api/kb/document/`` (empty after slash) should 400, not crash."""
    try:
        with urllib.request.urlopen(http_server + "/api/kb/document/", timeout=5):
            pass
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
