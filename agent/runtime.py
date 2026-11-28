"""Synchronous execution primitives; no network or framework dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import logging
import math
import threading
import time
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    IDLE = 'idle'
    ROUTING = 'routing'
    THINKING = 'thinking'
    EXECUTING = 'executing'
    RECOVERING = 'recovering'
    PAUSED = 'paused'
    WAITING_APPROVAL = 'waiting_approval'
    RETRIEVING = 'retrieving'
    CANCELLED = 'cancelled'
    COMPLETED = 'completed'
    FAILED = 'failed'
    EXHAUSTED = 'exhausted'


TERMINAL = {AgentState.COMPLETED, AgentState.FAILED, AgentState.EXHAUSTED, AgentState.CANCELLED}
TRANSITIONS = {
    AgentState.IDLE: {AgentState.ROUTING},
    AgentState.ROUTING: {AgentState.THINKING, AgentState.COMPLETED},
    AgentState.THINKING: {AgentState.EXECUTING, AgentState.RECOVERING, AgentState.COMPLETED},
    AgentState.EXECUTING: {AgentState.THINKING},
    AgentState.RECOVERING: {AgentState.THINKING},
}


@dataclass(frozen=True)
class Event:
    name: str
    run_id: str
    state: AgentState
    data: dict = field(default_factory=dict)
    trace_id: str = ''
    span_id: str = ''
    parent_span_id: Any = None
    run_sequence: int = 0
    monotonic_ns: int = 0
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {'event_id': self.event_id, 'timestamp': self.timestamp,
                'name': self.name, 'run_id': self.run_id,
                'state': self.state.value, 'data': deepcopy(self.data),
                'trace_id': self.trace_id, 'span_id': self.span_id, 'parent_span_id': self.parent_span_id,
                'run_sequence': self.run_sequence, 'monotonic_ns': self.monotonic_ns}


class RequiredSubscriberError(RuntimeError):
    """A required durability subscriber failed; execution must not proceed."""


class EventBus:
    """Ordered synchronous subscribers; observer failures are isolated."""
    def __init__(self):
        self._subscribers = {}
        self._lock = threading.RLock()

    def subscribe(self, name: str, callback: Callable, *, required=False):
        with self._lock:
            subscription = (callback, required)
            self._subscribers.setdefault(name, []).append(subscription)
        def unsubscribe():
            with self._lock:
                callbacks = self._subscribers.get(name, [])
                if subscription in callbacks:
                    callbacks.remove(subscription)
        return unsubscribe

    def publish(self, event: Event):
        with self._lock:
            callbacks = list(self._subscribers.get(event.name, []))
            callbacks += list(self._subscribers.get('*', []))
        failure = None
        for callback, required in callbacks:
            try:
                callback(deepcopy(event))
            except Exception as exc:
                if required and failure is None:
                    failure = exc
                logger.error('Event subscriber failed: event=%s error_type=%s', event.name, type(exc).__name__)
        if failure is not None:
            raise RequiredSubscriberError(f'Required subscriber failed for {event.name}') from failure


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionBudget:
    max_steps: int = 5
    max_llm_calls: int = 20
    max_tool_calls: int = 20
    max_seconds: float = 300.0
    max_retries: int = 3
    max_tokens: Any = None
    max_cost: Any = None
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    max_output_tokens: int = 2048
    warning_ratio: float = 0.8
    max_recoveries: int = 6
    max_repeated_calls: int = 4

    def __post_init__(self):
        for name in ('max_steps', 'max_llm_calls', 'max_tool_calls', 'max_retries', 'max_output_tokens', 'max_recoveries', 'max_repeated_calls'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'{name} must be a non-negative integer')
        if self.max_tokens is not None and (isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens < 0):
            raise ValueError('max_tokens must be a non-negative integer or null')
        for name in ('max_cost', 'input_price_per_million', 'output_price_per_million', 'warning_ratio'):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError(f'Invalid {name}')
        if not 0 < self.warning_ratio <= 1 or self.max_output_tokens < 1 or self.max_repeated_calls < 1:
            raise ValueError('Invalid output/loop/warning limits')
        if self.max_cost is not None and (self.input_price_per_million <= 0 or self.output_price_per_million <= 0):
            raise ValueError('Cost limits require positive input and output prices')
        if not math.isfinite(self.max_seconds) or self.max_seconds <= 0:
            raise ValueError('max_seconds must be finite and positive')


@dataclass
class RunContext:
    budget: ExecutionBudget
    run_id: str = field(default_factory=lambda: uuid4().hex)
    state: AgentState = AgentState.IDLE
    steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    started_at: float = field(default_factory=time.monotonic)
    error: str = ''
    tokens: int = 0
    cost: float = 0.0
    estimated_usage: bool = False
    recoveries: int = 0

    def remaining_seconds(self):
        remaining = self.budget.max_seconds - (time.monotonic() - self.started_at)
        if remaining <= 0:
            raise BudgetExceeded('Execution time budget exhausted')
        return remaining

    def consume(self, resource):
        self.remaining_seconds()
        if getattr(self, resource) >= getattr(self.budget, 'max_' + resource):
            raise BudgetExceeded(f'{resource} budget exhausted')
        setattr(self, resource, getattr(self, resource) + 1)

    def transition(self, target):
        if self.state in TERMINAL:
            raise ValueError(f'Terminal task cannot transition: {self.state}')
        if target in {AgentState.PAUSED, AgentState.WAITING_APPROVAL, AgentState.CANCELLED}:
            self.state = target
            return
        if self.state in {AgentState.PAUSED, AgentState.WAITING_APPROVAL} and target in {
                AgentState.ROUTING, AgentState.THINKING, AgentState.EXECUTING, AgentState.RETRIEVING}:
            self.state = target
            return
        if self.state == AgentState.THINKING and target == AgentState.RETRIEVING:
            self.state = target
            return
        if self.state == AgentState.RETRIEVING and target in {AgentState.THINKING, AgentState.EXECUTING}:
            self.state = target
            return
        if self.state == AgentState.EXECUTING and target == AgentState.RETRIEVING:
            self.state = target
            return
        allowed = TRANSITIONS.get(self.state, set())
        if target not in allowed and not (self.state not in TERMINAL and target in {AgentState.FAILED, AgentState.EXHAUSTED}):
            raise ValueError(f'Invalid state transition: {self.state} -> {target}')
        self.state = target


class AbortExecution(RuntimeError):
    """Explicit policy abort, never converted to a tool observation or retried."""


@dataclass(frozen=True)
class Recovery:
    """Explicit result returned by an error hook to recover an ordinary error."""
    value: Any


class HookManager:
    """Ordered before/after/error hooks plus onion middleware.

    Before/after returning None retain the input/result; error recovery must
    return Recovery(value). Control-plane exceptions are never recoverable.
    """
    OPERATIONS = {'run', 'route', 'llm', 'tool.prepare', 'tool'}

    def __init__(self, middleware=(), protected_errors=()):
        self.middleware = list(middleware)
        self.protected_errors = (BudgetExceeded, RequiredSubscriberError, AbortExecution) + tuple(protected_errors)
        self._hooks = {}
        self._lock = threading.RLock()

    def register(self, operation, stage, callback):
        if operation not in self.OPERATIONS or stage not in {'before', 'after', 'error'}:
            raise ValueError('Unknown hook operation or stage')
        with self._lock:
            entry = object(), callback
            self._hooks.setdefault((operation, stage), []).append(entry)
        def remove():
            with self._lock:
                entries = self._hooks.get((operation, stage), [])
                if entry in entries:
                    entries.remove(entry)
        return remove

    def invoke(self, context, operation, payload, action):
        if operation not in self.OPERATIONS:
            raise ValueError('Unknown hook operation')
        with self._lock:
            hooks = {stage: [cb for _, cb in self._hooks.get((operation, stage), [])]
                     for stage in ('before', 'after', 'error')}
            middleware = list(self.middleware)
        # Context is diagnostic data; control requests use the Agent API.
        view = deepcopy(context)
        def dispatch(index, value):
            if index == len(middleware):
                return action(value)
            called = False
            active = True
            def call_next(updated):
                nonlocal called
                if not active:
                    raise AbortExecution("call_next cannot be deferred beyond middleware return")
                if called:
                    raise AbortExecution('call_next may only be called once per middleware invocation')
                called = True
                return dispatch(index + 1, updated)
            try:
                return middleware[index](view, operation, value, call_next)
            finally:
                active = False
        try:
            for callback in hooks['before']:
                updated = callback(view, payload)
                if updated is not None:
                    payload = updated
            result = dispatch(0, payload)
        except self.protected_errors:
            raise
        except Exception as exc:
            for callback in hooks['error']:
                recovery = callback(view, exc)
                if isinstance(recovery, Recovery):
                    result = recovery.value
                    break
            else:
                raise
        for callback in hooks['after']:
            updated = callback(view, result)
            if updated is not None:
                result = updated
        return result
