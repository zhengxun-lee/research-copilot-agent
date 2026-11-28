"""Strict OpenAI-compatible stream aggregation. Never execute partial tool calls."""

import json
import threading
import time
from types import SimpleNamespace as NS


def field(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


class StreamInterrupted(RuntimeError):
    def __init__(self, message, partial=None):
        super().__init__(message)
        self.partial = partial or {}


class StreamControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.stream = None
        self.closed = False

    def attach(self, stream):
        with self.lock:
            self.stream = stream
        if self.cancelled.is_set():
            self.close()
            raise StreamInterrupted("Client stream cancelled")

    def close(self):
        self.cancelled.set()
        with self.lock:
            stream = self.stream
            if stream is None or self.closed:
                return
            self.closed = True

        def release():
            try:
                stream.close()
            except Exception:
                pass

        # Transport close may wait on an in-flight socket read.
        threading.Thread(target=release, daemon=True).start()


def aggregate(
    stream, callback=None, control=None, started=None, max_buffer_bytes=8 * 1024 * 1024
):
    started = started if started is not None else time.monotonic()
    control = control or StreamControl()
    control.attach(stream)
    content, reasoning, calls = [], [], {}
    usage = None
    buffered_bytes = 0
    finish = None
    first_output = first_content = first_reasoning = None
    seen = set()
    sequence = 0
    pending = {"content": "", "reasoning": ""}
    last_flush = time.monotonic()

    def emit(event_name, **data):
        nonlocal sequence
        if control.cancelled.is_set():
            raise StreamInterrupted("Client stream cancelled", partial())
        sequence += 1
        if callback:
            callback(event_name, dict(sequence=sequence, **data))

    def partial():
        return dict(
            content="".join(content),
            reasoning="".join(reasoning),
            tool_calls=calls,
            usage=usage,
        )

    def flush():
        nonlocal last_flush
        for kind in ("content", "reasoning"):
            if pending[kind]:
                emit("delta", kind=kind, text=pending[kind])
                pending[kind] = ""
        last_flush = time.monotonic()

    try:
        for chunk in stream:
            if control.cancelled.is_set():
                raise StreamInterrupted("Client stream cancelled", partial())
            # completion.id repeats for every chunk; only an explicit event ID can deduplicate.
            event_id = field(chunk, "event_id")
            if event_id:
                if event_id in seen:
                    continue
                seen.add(event_id)
            if field(chunk, "usage") is not None:
                usage = field(chunk, "usage")
            for choice in field(chunk, "choices", []) or []:
                if field(choice, "index", 0) != 0:
                    raise StreamInterrupted(
                        "Multiple completion choices are unsupported", partial()
                    )
                delta = field(choice, "delta", {}) or {}
                if finish is not None and any(
                    field(delta, k)
                    for k in ("content", "reasoning_content", "reasoning", "tool_calls")
                ):
                    raise StreamInterrupted(
                        "Delta received after finish reason", partial()
                    )
                for kind, text in (
                    ("content", field(delta, "content")),
                    (
                        "reasoning",
                        field(delta, "reasoning_content") or field(delta, "reasoning"),
                    ),
                ):
                    if not isinstance(text, str) or not text:
                        continue
                    elapsed = (time.monotonic() - started) * 1000
                    if first_output is None and text.strip():
                        first_output = elapsed
                        emit("first_output", latency_ms=elapsed)
                    if kind == "content" and first_content is None and text.strip():
                        first_content = elapsed
                        emit("first_content", latency_ms=elapsed)
                    if kind == "reasoning" and first_reasoning is None and text.strip():
                        first_reasoning = elapsed
                        emit("first_reasoning", latency_ms=elapsed)
                    (content if kind == "content" else reasoning).append(text)
                    pending[kind] += text
                    buffered_bytes += len(text.encode("utf-8"))
                    if buffered_bytes > max_buffer_bytes:
                        raise StreamInterrupted(
                            "Client response byte safety limit exceeded", partial()
                        )
                for call in field(delta, "tool_calls", []) or []:
                    index = field(call, "index")
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or index < 0
                    ):
                        raise StreamInterrupted(
                            "Tool delta has no valid index", partial()
                        )
                    item = calls.setdefault(index, dict(id="", name="", arguments=""))
                    call_id = field(call, "id")
                    if call_id:
                        if item["id"] and item["id"] != call_id:
                            raise StreamInterrupted(
                                "Conflicting tool call ID", partial()
                            )
                        item["id"] = call_id
                    function = field(call, "function", {}) or {}
                    for key in ("name", "arguments"):
                        value = field(function, key)
                        if value is not None and not isinstance(value, str):
                            raise StreamInterrupted(
                                "Invalid tool delta field", partial()
                            )
                        if value:
                            item[key] += value
                            buffered_bytes += len(value.encode("utf-8"))
                            if buffered_bytes > max_buffer_bytes:
                                raise StreamInterrupted(
                                    "Client response byte safety limit exceeded",
                                    partial(),
                                )
                    emit(
                        "tool_delta",
                        index=index,
                        call_id=item["id"],
                        name=item["name"],
                        arguments_delta=field(function, "arguments") or "",
                    )
                reason = field(choice, "finish_reason")
                if reason is not None:
                    if finish is not None and finish != reason:
                        raise StreamInterrupted("Conflicting finish reasons", partial())
                    finish = reason
            if (
                time.monotonic() - last_flush >= 0.04
                or sum(map(len, pending.values())) >= 1024
            ):
                flush()
        flush()
        if finish not in {"stop", "tool_calls"}:
            raise StreamInterrupted(
                "Stream ended without a successful finish reason", partial()
            )
        if calls and finish != "tool_calls":
            raise StreamInterrupted(
                "Tool batch did not finish with tool_calls", partial()
            )
        if finish == "tool_calls" and not calls:
            raise StreamInterrupted("Empty streamed tool batch", partial())
        tool_calls = []
        ids = set()
        for index, item in sorted(calls.items()):
            if not item["id"] or item["id"] in ids or not item["name"]:
                raise StreamInterrupted("Incomplete/duplicate tool identity", partial())
            ids.add(item["id"])
            try:
                arguments = json.loads(item["arguments"])
            except (ValueError, TypeError) as exc:
                raise StreamInterrupted(
                    "Incomplete tool JSON arguments", partial()
                ) from exc
            if not isinstance(arguments, dict):
                raise StreamInterrupted(
                    "Tool arguments must be a JSON object", partial()
                )
            tool_calls.append(
                NS(
                    id=item["id"],
                    type="function",
                    function=NS(name=item["name"], arguments=item["arguments"]),
                )
            )
        elapsed = (time.monotonic() - started) * 1000
        completion = field(usage, "completion_tokens")
        throughput = (
            completion / (elapsed / 1000)
            if isinstance(completion, int)
            and not isinstance(completion, bool)
            and completion >= 0
            and elapsed > 0
            else None
        )
        timing = dict(
            ttft_ms=first_output,
            ttfr_ms=first_reasoning,
            first_visible_ms=first_content,
            duration_ms=elapsed,
            output_tokens_per_second=throughput,
            latency_source="client_monotonic_first_nonempty_delta",
            throughput_source=(
                "provider_completion_tokens/full_client_duration"
                if throughput is not None
                else "unavailable"
            ),
        )
        emit("finished", finish_reason=finish, timing=timing)
        return NS(
            choices=[
                NS(
                    message=NS(content="".join(content), tool_calls=tool_calls),
                    finish_reason=finish,
                )
            ],
            usage=usage,
            streaming=True,
            stream_timing=timing,
        )
    except StreamInterrupted:
        raise
    except Exception as exc:
        try:
            flush()
        except Exception:
            pass
        if content or reasoning or calls:
            raise StreamInterrupted(
                f"Stream interrupted: {type(exc).__name__}", partial()
            ) from exc
        raise
    finally:
        control.close()
