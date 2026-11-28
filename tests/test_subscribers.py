from types import SimpleNamespace

import pytest

from agent import Agent, CheckpointStore, EventBus
from agent.runtime import AgentState, Event, RequiredSubscriberError
from agent.subscribers import EventStreamSubscriber, LoggingSubscriber, TokenUsageSubscriber
from test_agent_core import _completion, _message, _route_decision, _tool_call


def test_multiple_consumers_receive_independent_payloads():
    bus = EventBus()
    stream = EventStreamSubscriber()
    usage = TokenUsageSubscriber()
    bus.subscribe('*', lambda event: event.data.clear())
    bus.subscribe('*', stream)
    bus.subscribe('llm.completed', usage)
    event = Event('llm.completed', 'run', AgentState.THINKING,
                  {'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14}})
    bus.publish(event)
    assert usage.snapshot('run')['total_tokens'] == 14
    assert stream.get()['data']['usage']['total_tokens'] == 14
    assert event.data['usage']['total_tokens'] == 14


def test_usage_from_actual_completion_and_missing_usage():
    bus = EventBus()
    usage = TokenUsageSubscriber()
    bus.subscribe('llm.completed', usage)
    agent = Agent('sys', event_bus=bus)
    agent.model_router.route = lambda _: _route_decision()
    response = _completion(_message('done'))
    response.usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)
    agent.llm.chat = lambda **_: response
    assert agent.run('hi') == 'done'
    assert usage.snapshot(agent.last_run.run_id)['total_tokens'] == 7
    del response.usage
    agent.run('hi')
    assert usage.snapshot(agent.last_run.run_id)['missing_usage'] == 1


def test_stream_is_bounded_and_does_not_forward_checkpoints():
    stream = EventStreamSubscriber(max_events=1, run_id='a')
    stream(Event('one', 'a', AgentState.THINKING))
    stream(Event('two', 'a', AgentState.THINKING))
    stream(Event('checkpoint.requested', 'a', AgentState.THINKING, {'secret': 'private'}))
    stream(Event('other', 'b', AgentState.THINKING))
    assert stream.dropped == 1
    frame = stream.get_sse()
    assert 'event: two\n' in frame
    assert 'id: ' in frame
    assert 'private' not in frame


def test_required_failure_still_notifies_other_subscribers():
    bus = EventBus()
    events = []
    def fail(event):
        raise OSError('disk full')
    bus.subscribe('checkpoint.requested', fail, required=True)
    bus.subscribe('*', events.append)
    with pytest.raises(RequiredSubscriberError):
        bus.publish(Event('checkpoint.requested', 'a', AgentState.THINKING))
    assert len(events) == 1


def test_checkpoint_failure_prevents_tool_dispatch(tmp_path):
    store = CheckpointStore(tmp_path)
    original = store.save
    def save(run_id, data):
        if data['task']['phase'] == 'tool_inflight':
            raise OSError('disk full')
        original(run_id, data)
    store.save = save
    agent = Agent('sys', checkpoint_store=store)
    agent.model_router.route = lambda _: _route_decision()
    agent.llm.chat = lambda **_: _completion(_message(tool_calls=[_tool_call()]))
    agent.tool_registry.execute_strict = lambda *args: pytest.fail('unsafe dispatch')
    # Failure cannot be swallowed as a recoverable tool observation.
    with pytest.raises(RequiredSubscriberError):
        agent.run('hi')
    assert agent.last_run.state == AgentState.FAILED


def test_logging_does_not_include_payload(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger='agent.events'):
        LoggingSubscriber()(Event('tool.completed', 'a', AgentState.EXECUTING,
                                  {'result': 'private-result'}))
    assert 'tool.completed' in caplog.text
    assert 'private-result' not in caplog.text
