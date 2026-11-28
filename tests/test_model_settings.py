import json
import os
import stat
import time
from copy import deepcopy
from http.client import HTTPConnection
from urllib.parse import urlparse

import pytest
import yaml

from model_settings import ModelSettings, resolved_api_key
from test_web_app import http_server


def profiles():
    return {
        role: dict(
            model_name="unit-" + role,
            base_url="https://api.example.test/v1",
            api_key="unit-private-secret",
            key_mode="set",
        )
        for role in ("default", "simple", "complex", "embedding")
    }


def payload(store):
    return dict(
        revision=store.revision,
        router_enabled=True,
        profiles={
            role: dict(
                model_name=p["model_name"], base_url=p["base_url"], key_action="keep"
            )
            for role, p in store.profiles.items()
        },
    )


def test_atomic_private_save_preserves_unrelated_settings_and_never_returns_keys(
    tmp_path,
):
    path = tmp_path / "config.local.yaml"
    path.write_text("retrieval:\n  mode: hybrid\n")
    store = ModelSettings(path, profiles=profiles())
    change = payload(store)
    change["profiles"]["simple"].update(
        model_name="new-simple", key_action="set", api_key="unit-replacement-secret"
    )
    token = store.unlock()["edit_token"]
    view = store.save(change, token)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    data = yaml.safe_load(path.read_text())
    assert data["retrieval"]["mode"] == "hybrid"
    assert data["api"]["simple"]["api_key"] == "unit-replacement-secret"
    assert view["profiles"]["simple"]["key_configured"]
    assert "unit-replacement-secret" not in json.dumps(view)
    assert "unit-private-secret" not in json.dumps(store.public())
    with pytest.raises(PermissionError):
        store.save(payload(store), token)


def test_key_clear_and_inheritance_survive_configuration_reload(tmp_path, monkeypatch):
    from config_loader import load_project_config

    (tmp_path / "config.yaml").write_text("api: {}")
    store = ModelSettings(tmp_path / "config.local.yaml", profiles=profiles())
    change = payload(store)
    change["profiles"]["simple"]["key_action"] = "inherit"
    change["profiles"]["complex"]["key_action"] = "clear"
    store.save(change, store.unlock()["edit_token"])
    for name in (
        "OPENAI_API_KEY",
        "SIMPLE_MODEL_API_KEY",
        "COMPLEX_MODEL_API_KEY",
        "OPENAI_API_KEY_MODE",
        "SIMPLE_MODEL_API_KEY_MODE",
        "COMPLEX_MODEL_API_KEY_MODE",
        "EMBEDDING_API_KEY",
        "EMBEDDING_API_KEY_MODE",
        "MODEL_NAME",
        "SIMPLE_MODEL_NAME",
        "COMPLEX_MODEL_NAME",
        "EMBEDDING_MODEL_NAME",
        "OPENAI_BASE_URL",
        "SIMPLE_MODEL_BASE_URL",
        "COMPLEX_MODEL_BASE_URL",
        "EMBEDDING_BASE_URL",
        "MODEL_ROUTER_ENABLED",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    load_project_config(tmp_path)
    default = resolved_api_key("OPENAI_API_KEY")
    assert resolved_api_key("SIMPLE_MODEL_API_KEY", default) == default
    assert resolved_api_key("COMPLEX_MODEL_API_KEY", default) == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", "“secret”"),
        ("api_key", "secret\nvalue"),
        ("base_url", "http://remote.example/v1"),
        ("base_url", "https://user:password@example.com/v1"),
        ("base_url", "https://example.com/?api_key=secret"),
        ("model_name", ""),
    ],
)
def test_invalid_values_rejected_without_revealing_secret(tmp_path, field, value):
    store = ModelSettings(tmp_path / "config.local.yaml", profiles=profiles())
    change = payload(store)
    change["profiles"]["default"][field] = value
    if field == "api_key":
        change["profiles"]["default"]["key_action"] = "set"
    with pytest.raises(ValueError) as error:
        store.save(change, store.unlock()["edit_token"])
    if value:
        assert value not in str(error.value)
    assert not store.path.exists()


def test_failed_atomic_write_does_not_change_memory_or_existing_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "config.local.yaml"
    path.write_text("retrieval: {mode: keyword}")
    store = ModelSettings(path, profiles=profiles())
    change = payload(store)
    change["profiles"]["default"]["model_name"] = "changed"
    token = store.unlock()["edit_token"]
    monkeypatch.setattr(
        "model_settings.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("disk failure")),
    )
    with pytest.raises(OSError):
        store.save(change, token)
    assert store.revision == 0
    assert store.profiles["default"]["model_name"] == "unit-default"
    assert path.read_text() == "retrieval: {mode: keyword}"
    assert not list(tmp_path.glob(".model-settings-*"))


def test_stale_revision_and_expired_token_rejected(tmp_path):
    store = ModelSettings(tmp_path / "config.local.yaml", profiles=profiles())
    change = payload(store)
    token = store.unlock()["edit_token"]
    change["revision"] = 99
    with pytest.raises(ValueError):
        store.save(change, token)
    store.expires = time.monotonic() - 1
    with pytest.raises(PermissionError):
        store.save(payload(store), token)


@pytest.fixture
def model_store(tmp_path, monkeypatch):
    import web_app

    store = ModelSettings(tmp_path / "config.local.yaml", profiles=profiles())
    monkeypatch.setattr(web_app, "MODEL_SETTINGS", store)
    return store


def request(base, path, body=None, headers=None, method=None):
    url = urlparse(base)
    conn = HTTPConnection(url.hostname, url.port, timeout=3)
    conn.request(
        method or ("POST" if body is not None else "GET"),
        path,
        body=json.dumps(body) if body is not None else None,
        headers=headers or {},
    )
    response = conn.getresponse()
    result = (response.status, json.loads(response.read()), dict(response.getheaders()))
    conn.close()
    return result


def test_http_authorization_origin_host_and_secret_response(
    http_server, model_store, monkeypatch
):
    import web_app

    monkeypatch.setattr(web_app, "WEB_CORS_ORIGIN", "*")
    code, view, headers = request(http_server, "/api/settings/models")
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert "unit-private-secret" not in json.dumps(view)
    assert "Access-Control-Allow-Origin" not in headers
    base = {"Content-Type": "application/json", "X-Requested-With": "research-copilot"}
    assert (
        request(http_server, "/api/settings/models", payload(model_store), base)[0]
        == 403
    )
    assert (
        request(
            http_server,
            "/api/settings/models/unlock",
            {},
            {**base, "Origin": "https://evil.example"},
        )[0]
        == 403
    )
    assert (
        request(http_server, "/api/settings/models", headers={"Host": "evil.example"})[
            0
        ]
        == 403
    )
    assert (
        request(
            http_server,
            "/api/settings/models/unlock",
            {},
            {"Content-Type": "application/json"},
        )[0]
        == 403
    )
    code, grant, _ = request(http_server, "/api/settings/models/unlock", {}, base)
    assert code == 200
    code, result, _ = request(
        http_server,
        "/api/settings/models",
        payload(model_store),
        {**base, "X-Config-Token": grant["edit_token"]},
    )
    assert code == 200 and result["revision"] == 1
    assert "unit-private-secret" not in json.dumps(result)


def test_profile_application_only_at_new_run_boundary(tmp_path):
    from agent.core import Agent
    from web_runtime import attach_inspector, launch
    from test_agent_core import _completion, _message

    store = ModelSettings(tmp_path / "config.local.yaml", profiles=profiles())
    agent = attach_inspector(Agent("sys"))
    agent.llm.chat = lambda **_: _completion(_message("done"))
    # Route override is test-only; production uses the configured router.
    store.apply(agent)
    assert agent.model_router.simple_model == "unit-simple"
    assert agent.llm.api_key == "unit-private-secret"
    before = agent.model_router.simple_model
    change = payload(store)
    change["profiles"]["simple"]["model_name"] = "new-simple"
    store.save(change, store.unlock()["edit_token"])
    assert agent.model_router.simple_model == before
    called = []
    original = store.apply

    def apply(target):
        called.append(target)
        original(target)

    launch(agent, "start", {"message": "hi"}, prepare=apply)
    deadline = time.monotonic() + 2
    while agent._web_running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert called == [agent]
    assert agent.model_router.simple_model == "new-simple"


def test_symlink_config_target_is_rejected(tmp_path):
    target = tmp_path / "target.yaml"
    target.write_text("safe: value")
    path = tmp_path / "config.local.yaml"
    path.symlink_to(target)
    store = ModelSettings(path, profiles=profiles())
    with pytest.raises(ValueError, match="符号链接"):
        store.save(payload(store), store.unlock()["edit_token"])
    assert target.read_text() == "safe: value"


def test_active_approval_task_cannot_be_reconfigured(tmp_path):
    from agent.core import Agent
    from test_agent_core import _completion, _message, _route_decision, _tool_call
    from web_runtime import attach_inspector, launch

    agent = attach_inspector(Agent("sys", approval_tools=["calculator"]))
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(
        _message(tool_calls=[_tool_call("a", "calculator", '{"expression":"2+2"}')])
    )
    agent.run("calculate")
    assert agent.status()["state"] == "waiting_approval"
    prepared = []
    with pytest.raises(ValueError, match="Resume or cancel"):
        launch(
            agent,
            "start",
            {"message": "new task"},
            prepare=lambda _: prepared.append(True),
        )
    assert prepared == []


def test_key_preview_masks_each_character_and_resolves_inheritance(tmp_path):
    records = profiles()
    records["default"]["api_key"] = "123456"
    records["simple"].update(key_mode="inherit", api_key="ignored-secret")
    records["complex"].update(key_mode="clear", api_key="ignored-secret")
    records["embedding"]["api_key"] = "ab"
    view = ModelSettings(tmp_path / "config.local.yaml", profiles=records).public()
    assert view["profiles"]["default"]["key_preview"] == "******"
    assert view["profiles"]["simple"]["key_preview"] == "******"
    assert view["profiles"]["complex"]["key_preview"] == ""
    assert view["profiles"]["embedding"]["key_preview"] == "**"
    assert "123456" not in json.dumps(view)
    assert "ignored-secret" not in json.dumps(view)


def test_explicit_reveal_requires_local_nonce_and_resolves_inherited_key(http_server, model_store):
    path = '/api/settings/models/reveal'
    body = {'role': 'simple', 'revision': 0}
    base = {'Content-Type': 'application/json', 'X-Requested-With': 'research-copilot'}
    assert request(http_server, path, body, base)[0] == 403
    token = model_store.unlock()['edit_token']
    headers = {**base, 'X-Config-Token': token}
    assert request(http_server, path, body, {**headers, 'Origin': 'https://evil.example'})[0] == 403
    assert request(http_server, path, body, {**headers, 'Host': 'evil.example'})[0] == 403
    assert request(http_server, path, body, {**headers, 'Sec-Fetch-Site': 'cross-site'})[0] == 403
    assert request(http_server, path, body, {'Content-Type': 'application/json', 'X-Config-Token': token})[0] == 403
    assert request(http_server, path, {**body, 'revision': 99}, headers)[0] == 400
    assert request(http_server, path, {**body, 'role': '../config'}, headers)[0] == 400
    model_store.profiles['simple'].update(key_mode='inherit', api_key='ignored-key')
    code, data, response_headers = request(http_server, path, body, headers)
    assert code == 200 and data == {'api_key': 'unit-private-secret'}
    assert response_headers['Cache-Control'] == 'no-store'
    assert 'Access-Control-Allow-Origin' not in response_headers
    assert request(http_server, path, body, headers)[0] == 403
    assert 'unit-private-secret' not in json.dumps(model_store.public())
    model_store.profiles['simple']['key_mode'] = 'clear'
    assert model_store.reveal(body, model_store.unlock()['edit_token']) == {'api_key': ''}
    token = model_store.unlock()['edit_token']
    model_store.expires = time.monotonic() - 1
    with pytest.raises(PermissionError):
        model_store.reveal(body, token)
