"""End-to-end ReAct loop tests for ``agent.core.Agent``.

These tests stub out the LLM and tool registry so the loop control flow can be
exercised without external dependencies."""

from types import SimpleNamespace

from agent.core import Agent


def _route_decision():
    return SimpleNamespace(
        route_name="simple",
        model_name="test-model",
        confidence=1.0,
        reason="test",
        api_key=None,
        base_url=None,
    )


def _message(content="", tool_calls=None, reasoning_content=None):
    msg = SimpleNamespace(content=content)
    if tool_calls is not None:
        msg.tool_calls = tool_calls
    if reasoning_content is not None:
        msg.reasoning_content = reasoning_content
    return msg


def _completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(call_id="c1", name="search_knowledge", arguments="{}"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_agent_returns_error_string_when_llm_call_fails():
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()

    def fail_chat(**_kwargs):
        raise RuntimeError("boom")

    agent.llm.chat = fail_chat

    result = agent.run("hello")

    assert result.startswith("Error: LLM call failed — boom")
    # Error responses must NOT be stored in conversation memory; the user
    # message added by ``_run_impl`` should be rolled back as well.
    roles = [m["role"] for m in agent.memory.get_messages()]
    assert roles == ["system"], f"Memory not rolled back: {roles}"


def test_authentication_failure_explains_profile_without_provider_payload():
    import httpx
    from openai import AuthenticationError

    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()
    attempts = []

    def fail_chat(**kwargs):
        attempts.append(kwargs)
        raise AuthenticationError(
            "Authentication Fails, Your api key: private-test-key is invalid",
            response=httpx.Response(401, request=httpx.Request("POST", "https://example.com")),
            body={"error": "provider details"},
        )

    agent.llm.chat = fail_chat
    result = agent.run("hello")

    assert "认证失败（401）" in result
    assert "简单模型" in result
    assert "设置 → 模型配置" in result
    assert "继承密钥" in result
    assert "private-test-key" not in result
    assert "private-test-key" not in agent.status()["error"]
    assert len(attempts) == 1
    assert [m["role"] for m in agent.memory.get_messages()] == ["system"]


def test_agent_returns_error_string_when_llm_returns_empty_choices():
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()
    agent.llm.chat = lambda **_kwargs: SimpleNamespace(choices=[])

    result = agent.run("hello")

    assert result == "Error: LLM returned an empty response. Please try again."
    # User message added before the failed LLM call should also be rolled back.
    roles = [m["role"] for m in agent.memory.get_messages()]
    assert roles == ["system"], f"Memory not rolled back: {roles}"


def test_agent_returns_final_answer_when_no_tool_call():
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()
    agent.llm.chat = lambda **_kwargs: _completion(_message(content="final answer"))

    result = agent.run("hi")

    assert result == "final answer"
    roles = [m["role"] for m in agent.memory.get_messages()]
    assert roles == ["system", "user", "assistant"]


def test_agent_falls_back_to_reasoning_content_when_content_empty():
    """Reasoning models (DeepSeek-Reasoner, o1) often return empty ``content``
    with the answer tucked into ``reasoning_content``.  Make sure we surface
    that to the user instead of dropping it."""
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()
    agent.llm.chat = lambda **_kwargs: _completion(
        _message(
            content="",
            reasoning_content="Thinking hard.\n\nFinal answer: 42",
        )
    )

    result = agent.run("what is the answer?")

    assert "42" in result
    assert "Final answer" in result


def test_agent_executes_tool_and_returns_answer_on_second_step():
    """LLM first calls a tool, gets a result, then produces a final answer."""
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()

    tool_response = _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')]))
    final_response = _completion(_message(content="all done"))
    responses = iter([tool_response, final_response])
    agent.llm.chat = lambda **_kwargs: next(responses)

    # Stub the registry to record execution and return a fixed result.
    class FakeRegistry:
        def __init__(self):
            self.calls = []
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            self.calls.append((name, arguments))
            return "tool-result"

    agent.tool_registry = FakeRegistry()
    result = agent.run("hi")

    assert result == "all done"
    assert agent.tool_registry.calls == [("search_knowledge", {"query": "x"})]
    roles = [m["role"] for m in agent.memory.get_messages()]
    # system, user, assistant(tool_call), tool, assistant(final)
    assert roles == ["system", "user", "assistant", "tool", "assistant"]


def test_agent_returns_max_steps_error_when_loop_never_completes():
    from agent import ExecutionBudget
    agent = Agent(system_prompt="sys", tool_registry=None, budget=ExecutionBudget(max_repeated_calls=10))
    agent.model_router.route = lambda _text: _route_decision()

    call_count = {"n": 0}

    def chat(**_kwargs):
        call_count["n"] += 1
        return _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')]))

    agent.llm.chat = chat

    class FakeRegistry:
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            return "tool-result"

    agent.tool_registry = FakeRegistry()
    # MAX_STEPS default is 5
    result = agent.run("hi")

    assert "Reached maximum reasoning steps" in result
    assert call_count["n"] == 5


def test_agent_reuses_cached_tool_result_for_repeated_call():
    """Same tool call signature should not re-execute the tool."""
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()

    tool_response = _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')]))
    final_response = _completion(_message(content="done"))
    responses = iter([tool_response, tool_response, final_response])
    agent.llm.chat = lambda **_kwargs: next(responses)

    class FakeRegistry:
        def __init__(self):
            self.execute_calls = 0
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            self.execute_calls += 1
            return "tool-result"

    agent.tool_registry = FakeRegistry()
    result = agent.run("hi")

    assert result == "done"
    # The second identical call should be served from cache, not re-executed.
    assert agent.tool_registry.execute_calls == 1


def test_agent_appends_system_notice_when_loop_detected():
    """After 2 identical tool calls, the agent appends a notice to nudge the LLM."""
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()

    final_response = _completion(_message(content="ok"))
    responses = iter([
        _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')])),
        _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')])),
        _completion(_message(tool_calls=[_tool_call(arguments='{"query":"x"}')])),
        final_response,
    ])
    agent.llm.chat = lambda **_kwargs: next(responses)

    class FakeRegistry:
        def __init__(self):
            self.execute_calls = 0
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            self.execute_calls += 1
            return "tool-result"

    agent.tool_registry = FakeRegistry()
    agent.run("hi")

    # The loop-detection notice should appear in the most recent assistant msg.
    assistant_contents = [
        m.get("content", "") for m in agent.memory.get_messages()
        if m["role"] == "assistant"
    ]
    assert any("System notice" in c for c in assistant_contents), assistant_contents


def test_agent_records_route_decision():
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()
    agent.llm.chat = lambda **_kwargs: _completion(_message(content="ok"))

    agent.run("hi")
    assert agent.last_route_decision is not None
    assert agent.last_route_decision.model_name == "test-model"


def test_agent_handles_tool_call_with_invalid_json_arguments():
    """Malformed JSON in tool arguments → error observation, no exception bubbles up."""
    agent = Agent(system_prompt="sys")
    agent.model_router.route = lambda _text: _route_decision()

    bad = _completion(_message(tool_calls=[_tool_call(arguments='{not json')]))
    ok = _completion(_message(content="recovered"))
    responses = iter([bad, ok])
    agent.llm.chat = lambda **_kwargs: next(responses)

    class FakeRegistry:
        def __init__(self):
            self.execute_calls = 0
        def get_tool_specs(self):
            return []
        def execute(self, name, arguments):
            self.execute_calls += 1
            return "should-not-run"

    agent.tool_registry = FakeRegistry()
    result = agent.run("hi")
    assert result == "recovered"
    assert agent.tool_registry.execute_calls == 0
    # Tool observation must include the parse error
    tool_msgs = [m for m in agent.memory.get_messages() if m["role"] == "tool"]
    assert any("JSON parse failed" in m["content"] for m in tool_msgs)
