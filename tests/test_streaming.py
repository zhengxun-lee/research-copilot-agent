"""Protocol fixtures are test-only; production never fabricates deltas or timing."""

import json
import threading
import time
from types import SimpleNamespace as NS

import pytest

from agent.core import Agent
from agent.observability import metrics, Redactor
from agent.runtime import ExecutionBudget
from llm.client import LLMClient
from llm.streaming import aggregate, StreamControl, StreamInterrupted


def chunk(content=None, reasoning=None, tools=None, finish=None, **extras):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if tools is not None:
        delta["tool_calls"] = tools
    return dict(
        id="same-completion-id",
        choices=[dict(index=0, delta=delta, finish_reason=finish)],
        **extras,
    )


def call(index=0, name=None, arguments=None, id=None):
    return dict(index=index, id=id, function=dict(name=name, arguments=arguments))


class Stream:
    def __init__(self, items):
        self.items = items
        self.closed = threading.Event()

    def __iter__(self):
        for item in self.items:
            if isinstance(item, Exception):
                raise item
            yield item

    def close(self):
        self.closed.set()


def text_stream(text="answer", usage=True):
    items = [chunk(content=text), chunk(finish="stop")]
    if usage:
        items.append(
            dict(
                choices=[],
                usage=dict(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )
        )
    return Stream(items)


def agent_with_streams(*streams, **options):
    agent = Agent("system", **options)
    agent.model_router.route = lambda _: NS(
        route_name="simple",
        model_name="stream-test",
        confidence=1,
        reason="test",
        api_key=None,
        base_url=None,
    )
    requests = []
    responses = iter(streams)

    def chat(**kwargs):
        requests.append(kwargs)
        return aggregate(
            next(responses), kwargs.get("on_stream"), kwargs.get("stream_control")
        )

    agent.llm.chat = chat
    return agent, requests


def test_text_reasoning_usage_and_nonempty_clock_measurements():
    events = []
    stream = Stream(
        [
            chunk(),
            chunk(content=""),
            chunk(content=" "),
            chunk(reasoning="provided reasoning"),
            chunk(content="Hello"),
            chunk(content=" world"),
            chunk(finish="stop"),
            dict(
                choices=[],
                usage=dict(prompt_tokens=8, completion_tokens=5, total_tokens=13),
            ),
        ]
    )
    response = aggregate(stream, lambda name, data: events.append((name, data)))
    assert response.choices[0].message.content == " Hello world"
    assert response.usage["total_tokens"] == 13
    timing = response.stream_timing
    assert (
        0
        <= timing["ttft_ms"]
        <= timing["ttfr_ms"]
        <= timing["first_visible_ms"]
        <= timing["duration_ms"]
    )
    assert timing["output_tokens_per_second"] == pytest.approx(
        5 / (timing["duration_ms"] / 1000)
    )
    assert [name for name, _ in events].count("first_output") == 1
    assert stream.closed.wait(1)
    no_usage = aggregate(text_stream(usage=False))
    assert no_usage.stream_timing["output_tokens_per_second"] is None
    empty = aggregate(Stream([chunk(), chunk(content=""), chunk(finish="stop")]))
    assert empty.stream_timing["ttft_ms"] is None


def test_parallel_tools_fragmented_names_and_json_unicode():
    stream = Stream(
        [
            chunk(
                tools=[
                    call(1, "cal", '{"expression":', "b"),
                    call(0, "search_", '{"query":"', "a"),
                ]
            ),
            chunk(tools=[call(0, "knowledge", '中文"}'), call(1, "culator", '"2+2"}')]),
            chunk(finish="tool_calls"),
        ]
    )
    response = aggregate(stream)
    calls = response.choices[0].message.tool_calls
    assert [
        (c.id, c.function.name, json.loads(c.function.arguments)) for c in calls
    ] == [
        ("a", "search_knowledge", {"query": "中文"}),
        ("b", "calculator", {"expression": "2+2"}),
    ]


@pytest.mark.parametrize(
    "items",
    [
        [chunk(content="partial")],
        [chunk(content="partial"), RuntimeError("connection reset")],
        [
            chunk(tools=[call(0, "calculator", '{"expression":', "a")]),
            chunk(finish="tool_calls"),
        ],
        [chunk(tools=[call(0, "calculator", "[]", "a")]), chunk(finish="tool_calls")],
        [
            chunk(
                tools=[
                    call(0, "calculator", "{}", "a"),
                    call(1, "calculator", "{}", "a"),
                ]
            ),
            chunk(finish="tool_calls"),
        ],
        [
            chunk(tools=[call(0, "calculator", "{}", "a")]),
            chunk(tools=[call(0, None, None, "b")]),
            chunk(finish="tool_calls"),
        ],
        [
            chunk(tools=[call(None, "calculator", "{}", "a")]),
            chunk(finish="tool_calls"),
        ],
        [chunk(content="partial"), chunk(finish="length")],
        [chunk(finish="stop"), chunk(content="late")],
        [chunk(finish="tool_calls")],
    ],
)
def test_incomplete_or_invalid_stream_never_returns_executable_response(items):
    stream = Stream(items)
    with pytest.raises(StreamInterrupted):
        aggregate(stream)
    assert stream.closed.wait(1)


def test_explicit_event_ids_deduplicate_but_completion_id_does_not():
    a = chunk(content="a", event_id="one")
    response = aggregate(Stream([a, a, chunk(content="a"), chunk(finish="stop")]))
    assert response.choices[0].message.content == "aa"


def test_preoutput_failure_is_retryable_without_partial_wrapper():
    with pytest.raises(TimeoutError):
        aggregate(Stream([TimeoutError("timed out")]))


def test_close_before_attach_and_cleanup_failure_are_safe():
    control = StreamControl()
    control.close()
    stream = text_stream()
    with pytest.raises(StreamInterrupted):
        aggregate(stream, control=control)
    assert stream.closed.wait(1)

    class BrokenClose(Stream):
        def close(self):
            raise OSError("close failure")

    assert (
        aggregate(BrokenClose([chunk(content="ok"), chunk(finish="stop")]))
        .choices[0]
        .message.content
        == "ok"
    )


def test_response_memory_safety_cap_is_explicit_not_fake_token_usage():
    with pytest.raises(StreamInterrupted, match="byte safety limit"):
        aggregate(text_stream("abcdef"), max_buffer_bytes=3)


def test_client_stream_options_and_nonstream_compatibility():
    requests = []
    raw = NS(choices=[])

    def create(**kwargs):
        requests.append(kwargs)
        return text_stream() if kwargs.get("stream") else raw

    client = LLMClient("unit-key")
    client._client_for = lambda **_: NS(chat=NS(completions=NS(create=create)))
    assert client.chat([]) is raw
    assert client.chat([], stream=True, max_tokens=11).streaming
    assert requests[-1]["stream_options"] == {"include_usage": True}
    client.chat([], stream=True, include_stream_usage=False)
    assert "stream_options" not in requests[-1]
    assert requests[-2]["max_tokens"] == 11


def test_agent_stream_settles_usage_once_and_persists_replay():
    agent, requests = agent_with_streams(text_stream("genuine fixture"))
    assert agent.run("hi") == "genuine fixture"
    assert len(requests) == 1
    assert agent.last_run.tokens == 13
    assert not agent.last_run.estimated_usage
    events = agent.trace.store.all_events(agent.last_run.run_id)
    values = metrics(events)
    assert values["input_tokens"] == 10 and values["output_tokens"] == 3
    assert values["usage_responses"] == 1
    assert values["ttft_ms"] is not None
    assert values["throughput_source"].startswith("provider_")
    assert agent.status()["partial_output"]["content"] == "genuine fixture"
    assert any(e["name"] == "llm.stream.delta" for e in events)
    assert not agent.trace.pending


def test_partial_disconnect_aborts_without_retry_or_conversation_commit():
    agent, requests = agent_with_streams(
        Stream([chunk(content="retained"), OSError("connection reset")])
    )
    assert agent.run("hi").startswith("Error:")
    assert len(requests) == 1
    assert agent.status()["partial_output"]["content"] == "retained"
    assert agent.status()["partial_output"]["interrupted"]
    assert [m["role"] for m in agent.memory.get_messages()] == ["system"]
    assert agent.last_run.estimated_usage


def test_schema_rejects_entire_batch_before_any_tool_executes():
    stream = Stream(
        [
            chunk(
                tools=[
                    call(0, "calculator", '{"expression":"2+2"}', "a"),
                    call(1, "calculator", '{"expression":2}', "b"),
                ]
            ),
            chunk(finish="tool_calls"),
        ]
    )
    agent, requests = agent_with_streams(stream)
    executed = []
    agent.tool_registry.execute_with_context = lambda *args: executed.append(args)
    assert agent.run("hi").startswith("Error:")
    assert executed == []
    assert agent.last_run.tool_calls == 0
    assert len(requests) == 1


def test_valid_streamed_tool_obeys_approval_before_execution():
    stream = Stream(
        [
            chunk(tools=[call(0, "calculator", '{"expression":"2+2"}', "a")]),
            chunk(finish="tool_calls"),
        ]
    )
    agent, _ = agent_with_streams(
        stream, text_stream("four"), approval_tools=["calculator"]
    )
    agent.run("calculate")
    assert agent.status()["state"] == "waiting_approval"
    assert agent.last_run.tool_calls == 0
    assert agent.approve("a", True) == "four"
    assert agent.last_run.tool_calls == 1


def test_cancel_closes_blocked_transport_and_prevents_tools():
    entered = threading.Event()

    class Blocking(Stream):
        def __iter__(self):
            yield chunk(content="x" * 1100)
            entered.set()
            self.closed.wait(3)
            yield chunk(tools=[call(0, "calculator", '{"expression":"2+2"}', "a")])
            yield chunk(finish="tool_calls")

    stream = Blocking([])
    agent, requests = agent_with_streams(stream)
    result = []
    worker = threading.Thread(target=lambda: result.append(agent.run("hi")))
    worker.start()
    assert entered.wait(2)
    start = time.monotonic()
    agent.cancel()
    worker.join(1)
    assert not worker.is_alive()
    assert time.monotonic() - start < 1
    assert stream.closed.wait(1)
    assert agent.status()["state"] == "cancelled"
    assert agent.last_run.tool_calls == 0
    assert agent.status()["partial_output"]["content"] == "x" * 1100
    assert len(requests) == 1


def test_task_deadline_closes_stream_and_never_executes_tools():
    entered = threading.Event()

    class Blocking(Stream):
        def __iter__(self):
            entered.set()
            self.closed.wait(2)
            yield chunk(tools=[call(0, "calculator", '{"expression":"2+2"}', "a")])
            yield chunk(finish="tool_calls")

    stream = Blocking([])
    agent, _ = agent_with_streams(stream, budget=ExecutionBudget(max_seconds=0.15))
    agent.run("hi")
    assert entered.is_set()
    assert stream.closed.wait(1)
    assert agent.status()["state"] == "exhausted"
    assert agent.last_run.tool_calls == 0


def test_known_secrets_split_across_chunks_are_not_reconstructed_in_public_events():
    secret = "sk-this-is-a-test-credential-only"
    redactor = Redactor([secret])
    assert redactor.stream_text("prefix " + secret[:9]) == "prefix "
    agent, _ = agent_with_streams(
        Stream(
            [
                chunk(content="x" * 1100 + secret[:9]),
                chunk(content=secret[9:]),
                chunk(finish="stop"),
            ]
        )
    )
    agent.trace.redact.add(secret)
    agent.run("hi")
    events = agent.trace.store.all_events(agent.last_run.run_id)
    serialized = json.dumps(events)
    assert secret not in serialized
    assert secret[:9] not in serialized
    assert "[REDACTED]" in serialized
