"""Local structured traces, redaction and derived metrics; no external exporter."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from uuid import uuid4

_ACTIVE = ContextVar("agent_span", default=None)
_SECRET_KEY = re.compile(
    r"api[_-]?key|authorization|password|secret|access[_-]?token|credential|cookie|private[_-]?key",
    re.I,
)


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = set(
            value for value in secrets if isinstance(value, str) and value
        )
        self.lock = threading.RLock()

    def add(self, value):
        if isinstance(value, str) and value:
            with self.lock:
                self.secrets.add(value)

    def stream_text(self, value, final=False):
        """Withhold incomplete credential prefixes before exposing a cumulative snapshot."""
        if not final:
            with self.lock:
                prefixes = list(self.secrets) + [
                    "sk-",
                    "Bearer ",
                    "api_key=",
                    "password=",
                    "secret=",
                ]
            hold = 0
            for secret in prefixes:
                for length in range(1, min(len(value), len(secret) - 1) + 1):
                    if value.endswith(secret[:length]):
                        hold = max(hold, length)
            if hold:
                value = value[:-hold]
        return self(value)

    def __call__(self, value):
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else self(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self(item) for item in value]
        if isinstance(value, str):
            with self.lock:
                for secret in sorted(self.secrets, key=len, reverse=True):
                    value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[REDACTED]", value)
            value = re.sub(
                r"(?i)((?:api[_-]?key|password|secret|access_token)[\"\']?\s*[=:]\s*[\"\']?)[^\s\"\',;}]+",
                r"\1[REDACTED]",
                value,
            )
            value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
            value = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
            value = re.sub(
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                "[REDACTED PRIVATE KEY]",
                value,
                flags=re.S,
            )
            return value
        return value


class TraceStore:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,run_id TEXT,trace_id TEXT,name TEXT,timestamp REAL,body TEXT)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS events_run ON events(run_id,sequence)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY,run_id TEXT,run_sequence INTEGER,phase TEXT,state TEXT,body TEXT)"
        )
        self.db.commit()
        if str(path) != ":memory:":
            Path(path).chmod(0o600)

    def append(self, event):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO events(event_id,run_id,trace_id,name,timestamp,body) VALUES (?,?,?,?,?,?)",
                (
                    event["event_id"],
                    event["run_id"],
                    event["trace_id"],
                    event["name"],
                    event["timestamp"],
                    json.dumps(event, ensure_ascii=False),
                ),
            )

    def append_many(self, events):
        with self.lock, self.db:
            for event in events:
                self.db.execute(
                    "INSERT OR IGNORE INTO events(event_id,run_id,trace_id,name,timestamp,body) VALUES (?,?,?,?,?,?)",
                    (
                        event["event_id"],
                        event["run_id"],
                        event["trace_id"],
                        event["name"],
                        event["timestamp"],
                        json.dumps(event, ensure_ascii=False),
                    ),
                )

    def events(self, run_id, after=0, limit=1000):
        with self.lock:
            rows = self.db.execute(
                "SELECT sequence,body FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (run_id, after, min(1000, max(1, limit))),
            ).fetchall()
        return [dict(json.loads(body), sequence=seq) for seq, body in rows]

    def runs(self, query="", limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT run_id,trace_id,MIN(timestamp),MAX(timestamp),COUNT(*) FROM events WHERE run_id IN (SELECT run_id FROM events WHERE run_id LIKE ? OR body LIKE ?) GROUP BY run_id ORDER BY MAX(sequence) DESC LIMIT ?",
                ("%" + query + "%", "%" + query + "%", min(100, max(1, limit))),
            ).fetchall()
        result = []
        with self.lock:
            for r, t, a, b, n in rows:
                starts = self.db.execute(
                    "SELECT body FROM events WHERE run_id=? AND name='span.started' ORDER BY sequence LIMIT 100",
                    (r,),
                ).fetchall()
                title = next(
                    (
                        e["data"].get("inputs", {}).get("input", "")
                        for (body,) in starts
                        for e in [json.loads(body)]
                        if e["data"].get("operation") == "run"
                        and isinstance(e["data"].get("inputs"), dict)
                    ),
                    "",
                )
                latest = self.db.execute(
                    "SELECT body FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                    (r,),
                ).fetchone()
                result.append(
                    dict(
                        run_id=r,
                        trace_id=t,
                        started_at=a,
                        updated_at=b,
                        event_count=n,
                        task_title=title[:240] if isinstance(title, str) else "",
                        state=json.loads(latest[0]).get("state") if latest else None,
                    )
                )
        return result

    def all_events(self, run_id):
        result = []
        cursor = 0
        while True:
            batch = self.events(run_id, cursor)
            if not batch:
                return sorted(
                    result,
                    key=lambda event: event.get("run_sequence", event["sequence"]),
                )
            result.extend(batch)
            cursor = batch[-1]["sequence"]

    def save_snapshot(self, event):
        data = deepcopy(event.data["checkpoint"])
        data["debug_snapshot_time"] = event.timestamp
        phase = data["task"]["phase"]
        if phase not in {
            "route",
            "think",
            "llm",
            "tools",
            "final",
        } or event.state.value in {
            "completed",
            "failed",
            "cancelled",
            "exhausted",
        }:
            return
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.run_id,
                    event.run_sequence,
                    phase,
                    event.state.value,
                    json.dumps(data),
                ),
            )

    def checkpoints(self, run_id):
        with self.lock:
            rows = self.db.execute(
                "SELECT id,run_sequence,phase,state FROM snapshots WHERE run_id=? ORDER BY run_sequence",
                (run_id,),
            ).fetchall()
        return [dict(id=i, run_sequence=s, phase=p, state=t) for i, s, p, t in rows]

    def snapshot(self, run_id, snapshot_id):
        with self.lock:
            row = self.db.execute(
                "SELECT body FROM snapshots WHERE run_id=? AND id=?",
                (run_id, snapshot_id),
            ).fetchone()
        if row is None:
            raise ValueError("No safe checkpoint at this historical node")
        return json.loads(row[0])

    def export(self, run_id):
        return "\n".join(
            json.dumps(event, ensure_ascii=False) for event in self.all_events(run_id)
        )


def visible_response(result):
    return [
        dict(
            content=getattr(c.message, "content", None),
            tool_calls=[
                dict(
                    id=getattr(t, "id", None),
                    name=t.function.name,
                    arguments=t.function.arguments,
                )
                for t in (getattr(c.message, "tool_calls", None) or [])
            ],
        )
        for c in getattr(result, "choices", [])
    ]


class TraceRuntime:
    def __init__(self, store, emit, secrets=()):
        self.store, self.emit = store, emit
        self.redact = Redactor(secrets)
        self.lock = threading.RLock()
        self.identities = {}
        self.sequence = {}
        self.pending = []

    def identity(self, run_id):
        with self.lock:
            return self.identities.setdefault(run_id, (uuid4().hex, uuid4().hex[:16]))

    def metadata(self, run_id):
        trace, root = self.identity(run_id)
        active = _ACTIVE.get()
        with self.lock:
            self.sequence[run_id] = self.sequence.get(run_id, 0) + 1
            seq = self.sequence[run_id]
        if active and active["run_id"] == run_id:
            return dict(
                trace_id=trace,
                span_id=active["id"],
                parent_span_id=active["parent"],
                run_sequence=seq,
                monotonic_ns=time.monotonic_ns(),
            )
        return dict(
            trace_id=trace,
            span_id=root,
            parent_span_id=None,
            run_sequence=seq,
            monotonic_ns=time.monotonic_ns(),
        )

    def __call__(self, event):
        if event.run_id not in self.identities:
            return
        if event.name == "checkpoint.requested":
            self.store.save_snapshot(event)
            return
        safe = self.redact(event.to_dict())
        with self.lock:
            if event.name in {"llm.stream.delta", "llm.stream.tool_delta"}:
                self.pending.append(safe)
                if len(self.pending) < 16:
                    return
            else:
                self.pending.append(safe)
            batch, self.pending = self.pending, []
            if len(batch) == 1:
                self.store.append(batch[0])
            else:
                self.store.append_many(batch)

    @contextmanager
    def span(self, run_id, operation, inputs=None):
        _, root = self.identity(run_id)
        previous = _ACTIVE.get()
        parent = previous["id"] if previous and previous["run_id"] == run_id else root
        token = _ACTIVE.set(dict(run_id=run_id, id=uuid4().hex[:16], parent=parent))
        started = time.monotonic_ns()
        status = "ok"
        error = None
        try:
            self.emit("span.started", operation=operation, inputs=inputs)
            yield
        except BaseException as exc:
            status = (
                "interrupted"
                if type(exc).__name__ in {"TaskSuspended", "TaskCancelled"}
                else "error"
            )
            causes = []
            cause = exc.__cause__ or exc.__context__
            visited = {id(exc)}
            while cause is not None and id(cause) not in visited and len(causes) < 5:
                visited.add(id(cause))
                causes.append(dict(type=type(cause).__name__, message=str(cause)))
                cause = cause.__cause__ or cause.__context__
            error = dict(type=type(exc).__name__, message=str(exc), causes=causes)
            raise
        finally:
            try:
                self.emit(
                    "span.ended",
                    operation=operation,
                    status=status,
                    error=error,
                    duration_ms=(time.monotonic_ns() - started) / 1e6,
                )
            finally:
                _ACTIVE.reset(token)

    def middleware(self, context, operation, payload, call_next):
        if isinstance(payload, dict):
            self.redact.add(payload.get("api_key"))
        with self.span(
            context.run_id,
            operation,
            payload if operation != "run" else {"input": payload},
        ):
            result = call_next(payload)
            if operation in {"llm", "route"}:
                # Visible completion fields only; never persist reasoning_content.
                if operation == "llm":
                    response = visible_response(result)
                else:
                    response = dict(
                        model=getattr(result, "model_name", None),
                        route=getattr(result, "route_name", None),
                        confidence=getattr(result, "confidence", None),
                        reason=getattr(result, "reason", None),
                    )
                self.emit("operation.response", operation=operation, response=response)
            return result


def metrics(events):
    """Derived from recorded events. Null means unavailable, not zero latency."""
    values = dict(
        input_tokens=0,
        output_tokens=0,
        usage_responses=0,
        missing_usage=0,
        cache_hits=0,
        tool_requests=0,
        retries=0,
        cost_estimate=None,
        context_utilization_estimate=None,
        ttft_ms=None,
        ttft_source="unavailable_non_streaming",
        model_latency_ms=[],
        tool_latency_ms=[],
        total_duration_ms=None,
        cache_hit_rate=None,
        budget=None,
    )
    reported_attempts = {
        (e["run_id"], e["data"].get("attempt"))
        for e in events
        if e["name"] == "model.usage"
    }
    start = None
    end = None
    values["inherited_budget"] = None
    for event in events:
        data = event["data"]
        name = event["name"]
        if name == "run.started":
            start = event["timestamp"]
        if name in {"run.finished", "run.cancelled"}:
            end = event["timestamp"]
        if name == "model.usage" or (
            name == "llm.completed"
            and data.get("api_called", True)
            and (event["run_id"], data.get("attempt")) not in reported_attempts
        ):
            usage = data.get("usage")
            if not isinstance(usage, dict) or any(
                not isinstance(usage.get(key), int)
                or isinstance(usage.get(key), bool)
                or usage[key] < 0
                for key in ("prompt_tokens", "completion_tokens")
            ):
                values["missing_usage"] += 1
            else:
                values["usage_responses"] += 1
                values["input_tokens"] += usage.get("prompt_tokens") or 0
                values["output_tokens"] += usage.get("completion_tokens") or 0
        if name == "trace.branch.created":
            values["inherited_budget"] = data.get("inherited_budget")
        if name == "llm.stream.started":
            for key in (
                "ttft_ms",
                "ttfr_ms",
                "first_visible_ms",
                "duration_ms",
                "output_tokens_per_second",
            ):
                values[key] = None
            values["ttft_source"] = "unavailable_until_meaningful_delta"
        if name == "llm.stream.metrics":
            for key in (
                "ttft_ms",
                "ttfr_ms",
                "first_visible_ms",
                "duration_ms",
                "output_tokens_per_second",
                "latency_source",
                "throughput_source",
            ):
                values[key] = data.get(key)
            values["ttft_source"] = data.get("latency_source")
        if name == "llm.stream.first_output":
            values["ttft_ms"] = data["latency_ms"]
            values["ttft_source"] = "client_monotonic_delta"
        if name == "llm.stream.first_reasoning":
            values["ttfr_ms"] = data["latency_ms"]
        if name == "llm.stream.first_content":
            values["first_visible_ms"] = data["latency_ms"]
        if name == "tool.started":
            values["tool_requests"] += 1
        if name == "recovery.applied" and data.get("strategy") == "tool_cache_hit":
            values["cache_hits"] += 1
        if name == "retry.scheduled":
            values["retries"] += 1
        if name == "budget.updated":
            values["budget"] = data
            values["cost_estimate"] = (
                data["used"].get("cost")
                if data["limits"].get("input_price_per_million", 0) > 0
                and data["limits"].get("output_price_per_million", 0) > 0
                else None
            )
        if name == "context.assembled":
            values["context_utilization_estimate"] = (
                data["used"] + data["reserved"]
            ) / data["window"]
        if name == "span.ended" and data["operation"] in {"llm.api", "tool"}:
            values[
                (
                    "model_latency_ms"
                    if data["operation"] == "llm.api"
                    else "tool_latency_ms"
                )
            ].append(data["duration_ms"])
    if start is not None and end is not None:
        values["total_duration_ms"] = (end - start) * 1000
    denominator = values["cache_hits"] + values["tool_requests"]
    if denominator:
        values["cache_hit_rate"] = values["cache_hits"] / denominator
    values["token_source"] = (
        "provider_reported" if values["usage_responses"] else "unavailable"
    )
    values["active_duration_ms"] = (
        values["budget"]["used"].get("seconds", 0) * 1000 if values["budget"] else None
    )
    values["retry_source"] = "scheduled_retry_events; not confirmed provider execution"
    values["latency_source"] = (
        "local_monotonic_span; API roundtrip and tool operation including hooks"
    )
    return values
