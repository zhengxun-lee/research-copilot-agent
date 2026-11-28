import os
from types import SimpleNamespace
from llm.streaming import StreamControl, StreamInterrupted
from tools.validation import validate
from pathlib import Path
from copy import deepcopy
import random
import math
import hashlib
import json
from agent.recovery import ErrorKind, classify, rewrite_query
import time
import threading
from typing import Any, Optional

from api_config import OPENAI_API_KEY, OPENAI_BASE_URL
from config import MAX_STEPS
from llm.client import LLMClient
from tools.registry import ToolRegistry
from agent.observability import TraceStore, TraceRuntime, visible_response
from agent.context import ContextMemory, ContextStore, count_tokens
from tools.context_recall import ContextRecallTool
from routing import ComplexityModelRouter

from agent.task import TaskControls, TaskCancelled, TaskSuspended
from agent.runtime import (
    AgentState,
    BudgetExceeded,
    AbortExecution,
    RequiredSubscriberError,
    Event,
    EventBus,
    ExecutionBudget,
    HookManager,
    RunContext,
)


class Agent(TaskControls):
    """ReAct-style agent that iteratively reasons, calls tools, and produces a final answer."""

    def __init__(
        self,
        system_prompt: str,
        tool_registry: Optional[ToolRegistry] = None,
        *,
        budget: Optional[ExecutionBudget] = None,
        event_bus: Optional[EventBus] = None,
        middleware=(),
        checkpoint_store=None,
        approval_tools=(),
        context_window=32768,
        context_store=None,
        context_counter=None,
        trace_store=None,
        streaming=True,
        stream_usage=True,
    ):
        self.streaming = streaming
        self.stream_usage = stream_usage
        self.llm = LLMClient(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.tool_registry = tool_registry or ToolRegistry()
        self.model_router = ComplexityModelRouter()
        self.last_route_decision = None
        self._run_lock = threading.Lock()
        self._event_lock = threading.RLock()
        self.budget = budget or ExecutionBudget(max_steps=MAX_STEPS)
        self.event_bus = event_bus or EventBus()
        self.hooks = HookManager(
            middleware, protected_errors=(TaskCancelled, TaskSuspended)
        )
        self.last_run = None
        self._init_controls(checkpoint_store, approval_tools)
        store = context_store or ContextStore(
            checkpoint_store.directory / "context.sqlite3"
            if checkpoint_store
            else Path(
                os.environ.get(
                    "RESEARCH_COPILOT_STATE_DIR",
                    Path(__file__).resolve().parents[1] / "data",
                )
            )
            / "context.sqlite3"
        )
        self.memory = ContextMemory(
            system_prompt,
            store,
            context_window,
            emit=lambda name, **data: (
                self._emit(name, **data) if self.last_run else None
            ),
            counter=context_counter or count_tokens,
        )
        self.tool_registry.register(ContextRecallTool(self.memory))
        from api_config import (
            SIMPLE_MODEL_API_KEY,
            COMPLEX_MODEL_API_KEY,
            EMBEDDING_API_KEY,
        )

        self.trace = TraceRuntime(
            trace_store
            or TraceStore(
                checkpoint_store.directory / "traces.sqlite3"
                if checkpoint_store
                else Path(
                    os.environ.get(
                        "RESEARCH_COPILOT_STATE_DIR",
                        Path(__file__).resolve().parents[1] / "data",
                    )
                )
                / "traces.sqlite3"
            ),
            self._emit,
            (
                OPENAI_API_KEY,
                SIMPLE_MODEL_API_KEY,
                COMPLEX_MODEL_API_KEY,
                EMBEDDING_API_KEY,
            ),
        )
        self.event_bus.subscribe("*", self.trace, required=True)
        self.hooks.middleware.insert(0, self.trace.middleware)

    def run(self, user_input: str) -> str:
        """Run until completion or a durable suspension at a safe boundary."""
        with self._run_lock:
            with self._control_lock:
                if self._worker_busy.is_set():
                    raise ValueError("Previous cancelled operation is still draining")
                if self.last_run and self.last_run.state not in {
                    AgentState.COMPLETED,
                    AgentState.FAILED,
                    AgentState.EXHAUSTED,
                    AgentState.CANCELLED,
                }:
                    raise ValueError("An active task exists; resume or cancel it first")
                self.last_run = RunContext(self.budget)
                self.last_route_decision = None
                self._pause_requested.clear()
                self._cancel_requested.clear()
                self._task = {
                    "input": user_input,
                    "phase": "route",
                    "snapshot": deepcopy(self.memory.messages),
                    "cache": {},
                    "calls": [],
                    "index": 0,
                    "repeats": 0,
                }
                try:
                    self._emit("run.started")
                    self._transition(AgentState.ROUTING)
                    self._save()
                except Exception as exc:
                    self.last_run.error = str(exc)
                    if self.last_run.state not in {
                        AgentState.COMPLETED,
                        AgentState.FAILED,
                        AgentState.EXHAUSTED,
                        AgentState.CANCELLED,
                    }:
                        self.last_run.transition(AgentState.FAILED)
                    self._task["result"] = "Error: initialization persistence failed"
                    raise
            return self._drive()

    def _emit(self, event_name, **data):
        with self._event_lock:
            self.event_bus.publish(
                Event(
                    event_name,
                    self.last_run.run_id,
                    self.last_run.state,
                    data,
                    **self.trace.metadata(self.last_run.run_id),
                )
            )

    def _transition(self, target):
        try:
            with self.trace.span(
                self.last_run.run_id, "state.transition", {"target": target.value}
            ):
                previous = self.last_run.state
                self.last_run.transition(target)
                self._emit(
                    "state.changed", previous=previous.value, current=target.value
                )
        except RequiredSubscriberError as exc:
            self.last_run.error = str(exc)
            if self.last_run.state not in {
                AgentState.COMPLETED,
                AgentState.FAILED,
                AgentState.EXHAUSTED,
                AgentState.CANCELLED,
            }:
                self.last_run.transition(AgentState.FAILED)
            raise

    def _chat(self, **kwargs):
        executed_model = [kwargs.get("model_name")]
        while True:
            api_called = [False]
            try:

                def request(payload):
                    payload = deepcopy(payload)
                    self._boundary()
                    if self.last_run.llm_calls >= self.budget.max_llm_calls:
                        self._consume("llm_calls")
                    if self._task.get("conserve"):
                        self._switch_model("simple", "budget_warning")
                        decision = self.last_route_decision
                        payload.update(
                            model_name=decision.model_name,
                            api_key=decision.api_key,
                            base_url=decision.base_url,
                        )
                    executed_model[0] = payload.get("model_name")
                    self.trace.redact.add(payload.get("api_key"))
                    with self.trace.span(self.last_run.run_id, "context.assembly"):
                        payload["messages"] = self.memory.assemble(
                            payload["messages"],
                            payload.get("tools"),
                            self.budget.max_output_tokens,
                            phase=self._task["phase"],
                            task_state={
                                "phase": self._task["phase"],
                                "steps": self.last_run.steps,
                                "tool_calls": self.last_run.tool_calls,
                            },
                        )
                    self._emit(
                        "model.prepared", request=payload, dispatch="not_yet_sent"
                    )
                    reservation = self._reserve_request(payload)
                    self._consume("llm_calls")
                    if self._task.get("conserve"):
                        payload["tools"] = None
                    self._task["unreported_requests"] = (
                        self._task.get("unreported_requests", 0) + 1
                    )
                    self._emit(
                        "llm.started",
                        model=payload.get("model_name"),
                        attempt=self.last_run.llm_calls,
                    )
                    self._save()
                    timeout = min(60.0, self.last_run.remaining_seconds())
                    messages = deepcopy(payload)
                    self._emit(
                        "model.request",
                        request={
                            **payload,
                            "max_tokens": reservation["output"],
                            "timeout": timeout,
                            "max_retries": 0,
                        },
                        dispatch="attempt",
                    )
                    api_called[0] = True
                    control = StreamControl()
                    stream_id = __import__("uuid").uuid4().hex
                    partial = {"content": "", "reasoning": ""}

                    def on_stream(name, data):
                        with self._event_lock:
                            if (
                                self._cancel_requested.is_set()
                                or self.last_run.state
                                in {
                                    AgentState.CANCELLED,
                                    AgentState.FAILED,
                                    AgentState.EXHAUSTED,
                                }
                            ):
                                control.close()
                                return
                            if name == "delta":
                                partial[data["kind"]] += data["text"]
                                safe = {
                                    kind: self.trace.redact.stream_text(text)
                                    for kind, text in partial.items()
                                }
                                self._task["partial_output"] = {
                                    "stream_id": stream_id,
                                    **safe,
                                    "model": payload.get("model_name"),
                                    "complete": False,
                                    "sequence": data["sequence"],
                                }
                                # Public events use redacted cumulative snapshots. Reconnect/replay is idempotent.
                                data = {
                                    key: value
                                    for key, value in data.items()
                                    if key != "text"
                                }
                                data["snapshot"] = safe[data["kind"]]
                            elif name == "tool_delta":
                                # Incomplete JSON cannot be safely redacted. Publish progress, final args are inspected after validation.
                                data = {
                                    key: value
                                    for key, value in data.items()
                                    if key != "arguments_delta"
                                }
                            self._emit(
                                "llm.stream." + name,
                                stream_id=stream_id,
                                attempt=self.last_run.llm_calls,
                                **data,
                            )

                    self._emit(
                        (
                            "llm.stream.started"
                            if self.streaming
                            else "llm.nonstream.started"
                        ),
                        stream_id=stream_id,
                        model=payload.get("model_name"),
                    )
                    reported = False

                    def report_usage(usage, settle=True):
                        nonlocal reported
                        if reported:
                            return
                        reported = True
                        normalized = (
                            {
                                key: (
                                    usage.get(key)
                                    if isinstance(usage, dict)
                                    else getattr(usage, key, None)
                                )
                                for key in (
                                    "prompt_tokens",
                                    "completion_tokens",
                                    "total_tokens",
                                )
                            }
                            if usage is not None
                            else None
                        )
                        self._emit(
                            "model.usage",
                            usage=normalized,
                            attempt=self.last_run.llm_calls,
                            api_called=True,
                        )
                        if settle:
                            self._settle_request(
                                SimpleNamespace(usage=usage), reservation
                            )

                    try:
                        with self.trace.span(self.last_run.run_id, "llm.api"):
                            response = self._interruptible(
                                lambda: self.llm.chat(
                                    **messages,
                                    max_retries=0,
                                    timeout=timeout,
                                    max_tokens=reservation["output"],
                                    **(
                                        {
                                            "stream": True,
                                            "on_stream": on_stream,
                                            "stream_control": control,
                                            "include_stream_usage": self.stream_usage,
                                        }
                                        if self.streaming
                                        else {}
                                    ),
                                )
                            )
                        report_usage(getattr(response, "usage", None))
                        if getattr(response, "streaming", False):
                            for call in response.choices[0].message.tool_calls:
                                tool = getattr(self.tool_registry, "tools", {}).get(
                                    call.function.name
                                )
                                if tool is None:
                                    raise StreamInterrupted(
                                        "Unknown streamed tool", partial
                                    )
                                try:
                                    validate(
                                        json.loads(call.function.arguments),
                                        tool.parameters,
                                    )
                                except ValueError as exc:
                                    raise StreamInterrupted(
                                        "Streamed tool schema validation failed",
                                        partial,
                                    ) from exc
                            safe = {
                                kind: self.trace.redact.stream_text(text, final=True)
                                for kind, text in partial.items()
                            }
                            self._task["partial_output"] = {
                                "stream_id": stream_id,
                                **safe,
                                "model": payload.get("model_name"),
                                "complete": True,
                                "sequence": self._task.get("partial_output", {}).get(
                                    "sequence", 0
                                )
                                + 1,
                            }
                            self._emit(
                                "llm.stream.accepted", stream_id=stream_id, output=safe
                            )
                            self._emit(
                                "llm.stream.metrics",
                                stream_id=stream_id,
                                **response.stream_timing,
                            )
                    except StreamInterrupted as exc:
                        safe = {
                            kind: self.trace.redact.stream_text(
                                exc.partial.get(kind, partial[kind]), final=True
                            )
                            for kind in partial
                        }
                        self._task["partial_output"] = {
                            "stream_id": stream_id,
                            **safe,
                            "model": payload.get("model_name"),
                            "complete": False,
                            "interrupted": True,
                        }
                        self._emit(
                            "llm.stream.interrupted",
                            stream_id=stream_id,
                            reason=str(exc),
                            partial=safe,
                        )
                        report_usage(
                            exc.partial.get("usage"),
                            settle=exc.partial.get("usage") is not None,
                        )
                        raise AbortExecution(str(exc)) from exc
                    except BaseException:
                        if not reported:
                            report_usage(None, settle=False)
                        raise
                    finally:
                        control.close()
                    self._emit("model.response", response=visible_response(response))
                    return response

                response = self.hooks.invoke(self.last_run, "llm", kwargs, request)
                self.last_run.remaining_seconds()
                usage = getattr(response, "usage", None)
                fields = ("prompt_tokens", "completion_tokens", "total_tokens")
                usage = (
                    {
                        key: (
                            usage.get(key)
                            if isinstance(usage, dict)
                            else getattr(usage, key, None)
                        )
                        for key in fields
                    }
                    if usage is not None
                    else None
                )
                self._emit(
                    "llm.completed",
                    model=executed_model[0],
                    usage=usage,
                    api_called=api_called[0],
                    attempt=self.last_run.llm_calls,
                )
                return response
            except (
                BudgetExceeded,
                TaskCancelled,
                TaskSuspended,
                RequiredSubscriberError,
                AbortExecution,
            ):
                raise
            except Exception as exc:
                kind = classify(exc)
                self._emit(
                    "exception.raised",
                    category=kind.value,
                    operation="llm",
                    reason=str(exc),
                )
                self._emit("llm.failed", error=str(exc), category=kind.value)
                if kind == ErrorKind.CONTEXT:
                    if not self.memory.pressure and self._recover(
                        "context_pressure_offload"
                    ):
                        self.memory.pressure = True
                        kwargs["messages"] = self.memory.get_messages()
                        self._save()
                        continue
                if (
                    kind
                    not in {
                        ErrorKind.TIMEOUT,
                        ErrorKind.RATE_LIMIT,
                        ErrorKind.TRANSIENT,
                    }
                    or self.last_run.retries >= self.budget.max_retries
                ):
                    raise
                if not self._recover("exponential_backoff", category=kind.value):
                    raise
                self.last_run.retries += 1
                self._budget_event()
                if self.last_run.retries >= 2:
                    if self._switch_model("simple", "transient_api_failure"):
                        decision = self.last_route_decision
                        kwargs.update(
                            model_name=decision.model_name,
                            api_key=decision.api_key,
                            base_url=decision.base_url,
                        )
                self._transition(AgentState.RECOVERING)
                delay = min(
                    30.0, 2 ** (self.last_run.retries - 1) + random.uniform(0, 0.25)
                )
                headers = getattr(getattr(exc, "response", None), "headers", {})
                try:
                    delay = max(delay, min(60.0, float(headers.get("retry-after", 0))))
                except (TypeError, ValueError):
                    pass
                if delay >= self.last_run.remaining_seconds():
                    raise BudgetExceeded("Insufficient time budget for retry")
                self._emit("retry.scheduled", delay=delay)
                with self.trace.span(
                    self.last_run.run_id,
                    "recovery.backoff",
                    {"planned_delay": delay, "category": kind.value},
                ):
                    deadline = time.monotonic() + delay
                    while time.monotonic() < deadline:
                        if self._cancel_requested.wait(
                            min(0.05, deadline - time.monotonic())
                        ):
                            raise TaskCancelled()
                self._transition(AgentState.THINKING)

    def _execute_tool(self, name, arguments):
        expected = deepcopy({"name": name, "arguments": arguments})

        def execute(payload):
            if payload != expected:
                raise AbortExecution("Tool middleware cannot change an approved call")
            if self._cancel_requested.is_set():
                raise TaskCancelled()
            if self._task.get("debug_read_only") and self._side_effectful(name):
                raise AbortExecution("Debug branches forbid side-effectful tools")
            tool = getattr(self.tool_registry, "tools", {}).get(name)
            charge = getattr(tool, "cost_per_call", None)
            if self.budget.max_cost is not None:
                if charge is None:
                    raise AbortExecution(
                        "Cost-limited tasks require tool cost_per_call metadata"
                    )
                if charge < 0 or not math.isfinite(charge):
                    raise AbortExecution("Invalid tool cost_per_call")
                if self.last_run.cost + charge > self.budget.max_cost:
                    raise BudgetExceeded("Tool cost budget exhausted")
            self._consume("tool_calls")
            if charge is not None:
                self.last_run.cost += charge
                self._budget_event()
            self._save()
            self._emit(
                "tool.started",
                name=payload["name"],
                call_id=self._pending_call()["id"],
                arguments=deepcopy(payload["arguments"]),
            )
            execute_tool = getattr(
                self.tool_registry, "execute_strict", self.tool_registry.execute
            )
            key = hashlib.sha256(
                (self.last_run.run_id + json.dumps(expected, sort_keys=True)).encode()
            ).hexdigest()
            execute_context = getattr(self.tool_registry, "execute_with_context", None)
            self._emit(
                "tool.idempotency",
                call_id=self._pending_call()["id"],
                key=key,
                side_effects=self._side_effectful(name),
            )
            with self.trace.span(
                self.last_run.run_id,
                "retrieval.search" if name == "search_knowledge" else "tool.dispatch",
                {"name": name},
            ):
                raw_result = self._interruptible(
                    lambda: (
                        execute_context(
                            payload["name"], deepcopy(payload["arguments"]), key
                        )
                        if execute_context
                        else execute_tool(
                            payload["name"], deepcopy(payload["arguments"])
                        )
                    )
                )
            self._emit(
                "tool.response",
                name=name,
                call_id=self._pending_call()["id"],
                result=raw_result,
            )
            return raw_result

        if name == "search_knowledge" and (
            self.budget.max_tokens is not None or self.budget.max_cost is not None
        ):
            expected["arguments"]["mode"] = "keyword"
            self._emit("recovery.applied", strategy="local_retrieval_for_budget")
        attempts = 0
        while True:
            try:
                result = self.hooks.invoke(
                    self.last_run, "tool", deepcopy(expected), execute
                )
                break
            except (
                BudgetExceeded,
                TaskCancelled,
                TaskSuspended,
                RequiredSubscriberError,
                AbortExecution,
            ):
                raise
            except Exception as exc:
                kind = classify(exc, "tool")
                self._emit(
                    "exception.raised",
                    category=kind.value,
                    operation="tool",
                    reason=str(exc),
                )
                if self._side_effectful(name) or attempts >= 2:
                    raise
                if name == "search_knowledge" and kind == ErrorKind.EMPTY:
                    if not self._recover(
                        "query_rewrite" if attempts == 0 else "retrieval_mode_switch"
                    ):
                        raise
                    if attempts == 0:
                        expected["arguments"]["query"] = rewrite_query(
                            expected["arguments"]["query"]
                        )
                    else:
                        expected["arguments"]["mode"] = "semantic"
                elif (
                    kind in {ErrorKind.TIMEOUT, ErrorKind.TRANSIENT, ErrorKind.TOOL}
                    and attempts == 0
                ):
                    if not self._recover("read_only_tool_retry"):
                        raise
                else:
                    raise
                attempts += 1
                self._boundary()
        self.last_run.remaining_seconds()
        self._emit(
            "tool.completed",
            name=name,
            call_id=self._pending_call()["id"],
            result=result,
        )
        return result

    @staticmethod
    def _extract_final_text(message: Any) -> str:
        """Extract the user-visible answer from a chat-completion message.

        Reasoning models (DeepSeek-Reasoner, OpenAI o1/o3, etc.) sometimes
        return an empty ``content`` field and place their visible answer in
        ``reasoning_content``.  When that happens we fall back to the tail of
        ``reasoning_content`` so the user still sees a response instead of
        "No response generated."
        """
        content = (getattr(message, "content", None) or "").strip()
        if content:
            return content
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            stripped = reasoning.strip()
            if stripped:
                # Prefer the last paragraph — it usually contains the final answer.
                tail = stripped.rsplit("\n\n", 1)[-1].strip()
                return tail or stripped
        return "No response generated."
