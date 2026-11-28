"""Optional event consumers. Register at application composition time."""
from collections import defaultdict
import json
import logging
import queue
import threading


class LoggingSubscriber:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('agent.events')

    def __call__(self, event):
        # Avoid logging prompts, tool results, and full checkpoint contents.
        self.logger.info('event=%s run_id=%s state=%s event_id=%s',
                         event.name, event.run_id, event.state.value, event.event_id)


class TokenUsageSubscriber:
    """Aggregate provider-reported usage. Missing usage is counted, never estimated."""
    def __init__(self):
        self._usage = defaultdict(lambda: dict(prompt_tokens=0, completion_tokens=0,
                                              total_tokens=0, responses=0, missing_usage=0))
        self._lock = threading.Lock()

    def __call__(self, event):
        if event.name != 'llm.completed' or event.data.get('api_called') is False:
            return
        with self._lock:
            totals = self._usage[event.run_id]
            totals['responses'] += 1
            usage = event.data.get('usage')
            if usage is None:
                totals['missing_usage'] += 1
                return
            for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                value = usage.get(name)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    totals[name] += value

    def snapshot(self, run_id):
        with self._lock:
            return dict(self._usage[run_id])

    def discard(self, run_id):
        with self._lock:
            self._usage.pop(run_id, None)


class CheckpointSubscriber:
    def __init__(self, store):
        self.store = store

    def __call__(self, event):
        if event.name == 'checkpoint.requested':
            self.store.save(event.run_id, event.data['checkpoint'])


class EventStreamSubscriber:
    """Bounded non-blocking transport adapter for a UI, SSE, WebSocket or trace worker.

    Overflow drops the oldest event. This is a live feed, not a durable event log.
    Checkpoint payloads are private and are never forwarded to the live feed.
    """
    def __init__(self, max_events=256, run_id=None):
        if max_events < 1:
            raise ValueError('max_events must be positive')
        self.queue = queue.Queue(maxsize=max_events)
        self.run_id = run_id
        self.dropped = 0
        self._lock = threading.Lock()

    def __call__(self, event):
        if event.name == 'checkpoint.requested' or (self.run_id and event.run_id != self.run_id):
            return
        with self._lock:
            if self.queue.full():
                self.queue.get_nowait()
                self.dropped += 1
            self.queue.put_nowait(event.to_dict())

    def get(self, timeout=None):
        return self.queue.get(timeout=timeout)

    def get_sse(self, timeout=None):
        event = self.get(timeout)
        return ('id: ' + event['event_id'] + '\nevent: ' + event['name'] +
                '\ndata: ' + json.dumps(event, ensure_ascii=False) + '\n\n')
