import json
import threading
from types import SimpleNamespace

import pytest

from agent import Agent, CheckpointStore, EventBus
from agent.observability import Redactor, TraceStore, metrics
from agent.debugging import fork_checkpoint
from test_agent_core import _completion, _message, _route_decision, _tool_call


def ready(tmp_path, **kwargs):
    store = TraceStore(tmp_path / "trace.sqlite")
    agent = Agent("sys", checkpoint_store=CheckpointStore(tmp_path / "checkpoints"), trace_store=store, **kwargs)
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message("done"))
    return agent, store


def test_nested_spans_requests_metrics_and_export(tmp_path):
    agent, store = ready(tmp_path)
    response = _completion(_message("visible answer", reasoning_content="private internal reasoning"))
    response.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13)
    agent.llm.chat = lambda **_: response
    assert agent.run("hello") == "visible answer"
    events = store.all_events(agent.last_run.run_id)
    assert len({e["trace_id"] for e in events}) == 1
    root = next(e["span_id"] for e in events if e["name"] == "run.started")
    starts = {e["span_id"]: e for e in events if e["name"] == "span.started"}
    for event in starts.values():
        assert event["parent_span_id"] in starts or event["parent_span_id"] == root
    assert {e["span_id"] for e in events if e["name"] == "span.ended"} == set(starts)
    assert any(e["data"].get("operation") == "context.assembly" for e in starts.values())
    assert any(e["name"] == "model.request" and e["data"]["request"]["messages"] for e in events)
    result = metrics(events)
    assert result["input_tokens"] == 10 and result["output_tokens"] == 3
    assert result["ttft_ms"] is None
    assert result["model_latency_ms"][0] >= 0
    assert result["total_duration_ms"] >= 0
    assert "private internal reasoning" not in store.export(agent.last_run.run_id)
    assert len(store.export(agent.last_run.run_id).splitlines()) == len(events)


def test_redaction_handles_nested_payloads_and_literal_secrets(tmp_path):
    redactor = Redactor(["provider-secret"])
    raw = {
        "api_key": "abc",
        "nested": [{"Authorization": "Bearer secret"}],
        "result": 'provider-secret Bearer abc.def {"password":"embedded"}',
    }
    output = json.dumps(redactor(raw))
    assert "provider-secret" not in output and "embedded" not in output and "abc.def" not in output
    assert "[REDACTED]" in output
    agent, store = ready(tmp_path)
    agent.trace.redact.add("private-query-secret")
    agent.run("private-query-secret")
    assert "private-query-secret" not in store.export(agent.last_run.run_id)


def test_concurrent_shared_bus_traces_are_isolated(tmp_path):
    bus = EventBus()
    first, store1 = ready(tmp_path / "a", event_bus=bus)
    second, store2 = ready(tmp_path / "b", event_bus=bus)
    barrier = threading.Barrier(2)

    def chat(**_):
        barrier.wait(timeout=3)
        return _completion(_message("done"))

    first.llm.chat = second.llm.chat = chat
    threads = [threading.Thread(target=a.run, args=("hello",)) for a in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(4)
        assert not thread.is_alive()
    assert store1.runs()[0]["run_id"] == first.last_run.run_id and len(store1.runs()) == 1
    assert store2.runs()[0]["run_id"] == second.last_run.run_id and len(store2.runs()) == 1
    assert not second.checkpoint_store._path(first.last_run.run_id).exists()


def test_history_survives_reopen_and_event_ids_deduplicate(tmp_path):
    agent, store = ready(tmp_path)
    agent.run("hi")
    run_id = agent.last_run.run_id
    rows = store.all_events(run_id)
    store.append(rows[0])
    assert len(store.all_events(run_id)) == len(rows)
    other = TraceStore(tmp_path / "trace.sqlite")
    assert len(other.all_events(run_id)) == len(rows)


def test_offline_read_replay_does_not_call_tools(tmp_path):
    agent, store = ready(tmp_path)
    agent.run("hi")
    agent.llm.chat = lambda **_: pytest.fail("replay executed LLM")
    for event in store.all_events(agent.last_run.run_id):
        assert event["event_id"]
    metrics(store.all_events(agent.last_run.run_id))
    store.export(agent.last_run.run_id)


def test_safe_branch_edits_tool_without_replaying_prior_work(tmp_path):
    parent, store = ready(tmp_path)
    parent.llm.chat = lambda **_: _completion(
        _message(tool_calls=[_tool_call("a", "calculator", '{"expression":"1+1"}')])
    )
    parent.approval_tools = {"calculator"}
    parent.run("calculate")
    candidates = [c for c in store.checkpoints(parent.last_run.run_id) if c["phase"] == "tools"]
    assert candidates
    child = Agent("sys", checkpoint_store=CheckpointStore(tmp_path / "checkpoints"), trace_store=store)
    child.llm.chat = lambda **_: _completion(_message("branch done"))
    run_id = fork_checkpoint(
        child, store, parent.last_run.run_id, candidates[-1]["id"], arguments={"expression": "3+4"}, model="simple"
    )
    assert run_id != parent.last_run.run_id and child.last_run.state.value == "paused"
    assert child.last_route_decision.route_name == "simple"
    assert child.memory.scope != parent.memory.scope
    child.resume()  # approval remains required, no actual tool invocation yet
    assert child.last_run.state.value == "waiting_approval"
    assert child.approve("a") == "branch done"
    assert any(m.get("role") == "tool" and "7" in m["content"] for m in child.memory.messages)
    assert parent.last_run.state.value == "waiting_approval"


def test_branch_rejects_side_effect_tools_even_after_restart(tmp_path):
    from tools.base import BaseTool

    class Write(BaseTool):
        name = "write"

        def run(self, **_):
            pytest.fail("side effect executed")

    parent, store = ready(tmp_path)
    parent.tool_registry.register(Write())
    parent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call("w", "write")]))
    parent.run("write")
    checkpoint = next(c for c in reversed(store.checkpoints(parent.last_run.run_id)) if c["phase"] == "tools")
    child = Agent("sys", checkpoint_store=parent.checkpoint_store, trace_store=store)
    child.tool_registry.register(Write())
    with pytest.raises(ValueError):
        fork_checkpoint(child, store, parent.last_run.run_id, checkpoint["id"], arguments={})
    fork_checkpoint(child, store, parent.last_run.run_id, checkpoint["id"])
    run_id = child.last_run.run_id
    restored = Agent("sys", checkpoint_store=parent.checkpoint_store, trace_store=store)
    restored.tool_registry.register(Write())
    restored.restore(run_id)
    restored.resume()
    if restored.last_run.state.value == "waiting_approval":
        restored.approve("w")
    assert restored.last_run.state.value == "failed"


def test_metrics_count_real_usage_cache_hits_and_configured_cost(tmp_path):
    from agent import ExecutionBudget

    agent, store = ready(tmp_path, budget=ExecutionBudget(input_price_per_million=2, output_price_per_million=4))
    agent.tool_registry.execute_strict = lambda *args: "tool result"
    tool = _completion(_message(tool_calls=[_tool_call("a", "calculator", '{"expression":"1+1"}')]))
    final = _completion(_message("done"))
    for response in (tool, final):
        response.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13)
    responses = iter([tool, tool, final])
    agent.llm.chat = lambda **_: next(responses)
    agent.run("hello")
    result = metrics(store.all_events(agent.last_run.run_id))
    assert result["input_tokens"] == 30 and result["output_tokens"] == 9
    assert result["cache_hits"] == 1 and result["tool_requests"] == 1
    assert result["cache_hit_rate"] == 0.5
    assert result["cost_estimate"] == pytest.approx(0.000096)
    assert len(result["model_latency_ms"]) == 3


def test_missing_metrics_are_unavailable_not_fabricated_zero(tmp_path):
    agent, store = ready(tmp_path)
    response = _completion(_message("done"))
    response.usage = {}
    agent.llm.chat = lambda **_: response
    agent.run("hello")
    result = metrics(store.all_events(agent.last_run.run_id))
    assert result["missing_usage"] == 1 and result["usage_responses"] == 0
    assert result["token_source"] == "unavailable"
    assert result["cost_estimate"] is None and result["ttft_ms"] is None


def test_span_context_is_reset_even_when_persistence_observer_fails():
    from agent.observability import TraceRuntime

    def fail(*args, **kwargs):
        raise OSError("disk full")

    tracer = TraceRuntime(TraceStore(":memory:"), fail)
    with pytest.raises(OSError):
        with tracer.span("run", "operation"):
            pytest.fail("operation must not start")
    assert tracer.metadata("run")["parent_span_id"] is None


def test_usage_is_recorded_even_when_actual_response_exhausts_budget(tmp_path):
    from agent import ExecutionBudget

    agent, store = ready(tmp_path, budget=ExecutionBudget(max_tokens=5000))
    response = _completion(_message("done"))
    response.usage = SimpleNamespace(prompt_tokens=9000, completion_tokens=5, total_tokens=9005)
    agent.llm.chat = lambda **_: response
    agent.run("hello")
    assert agent.last_run.state.value == "exhausted"
    result = metrics(store.all_events(agent.last_run.run_id))
    assert result["input_tokens"] == 9000 and result["output_tokens"] == 5
    assert result["usage_responses"] == 1


def test_branch_context_excludes_information_created_after_checkpoint(tmp_path):
    parent, store = ready(tmp_path)
    parent.approval_tools = {"calculator"}
    parent.llm.chat = lambda **_: _completion(
        _message(tool_calls=[_tool_call("a", "calculator", '{"expression":"1"}')])
    )
    parent.run("calculate")
    checkpoint = next(c for c in reversed(store.checkpoints(parent.last_run.run_id)) if c["phase"] == "tools")
    parent.memory.store.put(parent.memory.scope, {"content": "futureonlyevidenceuniqueterm"}, "tool:x", 20, 0.5)
    child = Agent("sys", checkpoint_store=parent.checkpoint_store, trace_store=store)
    fork_checkpoint(child, store, parent.last_run.run_id, checkpoint["id"])
    assert child.memory.store.search(child.memory.scope, "futureonlyevidenceuniqueterm") == []


def test_persistence_failure_stops_initialization_and_allows_retry_after_repair(tmp_path):
    agent, store = ready(tmp_path)
    original = store.append

    def fail(event):
        raise OSError("disk full")

    store.append = fail
    with pytest.raises(Exception):
        agent.run("must not execute")
    assert agent.last_run.state.value == "failed" and agent.last_run.llm_calls == 0
    store.append = original
    assert agent.run("retry after storage repair") == "done"


def test_transient_state_record_failure_is_terminal_without_invalid_transition(tmp_path):
    agent, store = ready(tmp_path)
    original = store.append
    failed = []

    def once(event):
        if not failed and event["name"] == "state.changed" and event["data"].get("current") == "thinking":
            failed.append(True)
            raise OSError("temporary disk failure")
        original(event)

    store.append = once
    result = agent.run("hello")
    assert agent.last_run.state.value == "failed"
    assert agent.last_run.llm_calls == 0
    assert "Terminal task cannot transition" not in result
    ended = [e for e in store.all_events(agent.last_run.run_id) if e["name"] == "span.ended" and e["data"].get("error")]
    assert any("temporary disk failure" in json.dumps(e["data"]) for e in ended)


def test_branch_parameter_edit_preserves_older_batches_reusing_a_call_id(tmp_path):
    parent, store = ready(tmp_path)
    parent.approval_tools = {"calculator"}
    responses = iter(
        [
            _completion(_message(tool_calls=[_tool_call("same", "calculator", '{"expression":"1"}')])),
            _completion(_message(tool_calls=[_tool_call("same", "calculator", '{"expression":"2"}')])),
        ]
    )
    parent.llm.chat = lambda **_: next(responses)
    parent.run("calculate")
    parent.approve("same")
    checkpoint = next(c for c in reversed(store.checkpoints(parent.last_run.run_id)) if c["phase"] == "tools")
    child = Agent("sys", checkpoint_store=parent.checkpoint_store, trace_store=store)
    fork_checkpoint(child, store, parent.last_run.run_id, checkpoint["id"], arguments={"expression": "3"})
    calls = [call for message in child.memory.messages for call in message.get("tool_calls", [])]
    assert json.loads(calls[0]["function"]["arguments"]) == {"expression": "1"}
    assert json.loads(calls[-1]["function"]["arguments"]) == {"expression": "3"}


def test_history_list_contains_recorded_task_title_and_terminal_state():
    from test_agent_core import _route_decision, _completion, _message
    from agent.core import Agent
    agent = Agent('sys')
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message('actual test answer'))
    agent.run('a searchable research task')
    rows = agent.trace.store.runs('searchable research')
    assert len(rows) == 1
    assert rows[0]['task_title'] == 'a searchable research task'
    assert rows[0]['state'] == 'completed'
    assert rows[0]['run_id'] == agent.last_run.run_id
