from agent.memory import Memory


def test_memory_starts_with_system_prompt():
    memory = Memory(system_prompt="You are helpful.")
    assert memory.get_messages() == [{"role": "system", "content": "You are helpful."}]


def test_memory_adds_user_and_assistant_messages():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("hello")
    memory.add_assistant_message(content="hi there")

    msgs = memory.get_messages()
    assert len(msgs) == 3
    assert msgs[1] == {"role": "user", "content": "hello"}
    assert msgs[2] == {"role": "assistant", "content": "hi there"}


def test_memory_adds_tool_calls_and_results():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("calc")
    memory.add_assistant_message(
        content="",
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "calc", "arguments": "{}"}}],
    )
    memory.add_tool_message(tool_call_id="c1", content="42")

    msgs = memory.get_messages()
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "calc", "arguments": "{}"}}
    ]
    assert msgs[3]["role"] == "tool"
    assert msgs[3]["tool_call_id"] == "c1"
    assert msgs[3]["content"] == "42"


def test_append_to_last_assistant_targets_correct_message():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q")
    memory.add_assistant_message(content="thinking", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}])
    memory.add_tool_message(tool_call_id="c1", content="result")

    memory.append_to_last_assistant("System notice: stop looping")

    msgs = memory.get_messages()
    # The assistant message (index 2) should contain the notice, NOT the tool result (index 3)
    assert "System notice: stop looping" in msgs[2]["content"]
    assert "System notice" not in msgs[3]["content"]


def test_memory_enforces_max_turns():
    memory = Memory(system_prompt="sys", max_turns=2)

    # Turn 1
    memory.add_user_message("q1")
    memory.add_assistant_message(content="a1")
    # Turn 2
    memory.add_user_message("q2")
    memory.add_assistant_message(content="a2")
    # Turn 3 (should evict turn 1)
    memory.add_user_message("q3")
    memory.add_assistant_message(content="a3")

    msgs = memory.get_messages()
    contents = [m["content"] for m in msgs if m["role"] == "user"]
    assert "q1" not in contents
    assert "q2" in contents
    assert "q3" in contents
    # system prompt always preserved
    assert msgs[0]["role"] == "system"


def test_memory_enforces_limit_with_tool_calls():
    memory = Memory(system_prompt="sys", max_turns=1)

    # Full turn with tool calls
    memory.add_user_message("q1")
    memory.add_assistant_message(content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}])
    memory.add_tool_message(tool_call_id="c1", content="r1")
    memory.add_assistant_message(content="final a1")

    # This should evict the first turn
    memory.add_user_message("q2")
    memory.add_assistant_message(content="a2")

    msgs = memory.get_messages()
    contents = [m["content"] for m in msgs if m["role"] == "user"]
    assert "q1" not in contents
    assert "q2" in contents


def test_empty_assistant_content_defaults_to_empty_string():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("hi")
    memory.add_assistant_message()  # no content, no tool_calls
    msgs = memory.get_messages()
    assert msgs[2]["content"] == ""


def test_add_user_message_drops_orphaned_previous_user():
    """When an LLM call fails and rollback is NOT performed, the user message
    stays in memory without an assistant response.  The next add_user_message
    should silently drop the orphaned user message to avoid consecutive user
    messages."""
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q1")
    # LLM fails — Agent calls pop_last_user_message to roll back; here we
    # skip rollback intentionally to verify the defensive drop in add_user.
    memory.add_user_message("q2")
    msgs = memory.get_messages()
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user"], f"Expected [system, user] got {roles}"
    assert msgs[-1]["content"] == "q2"


def test_pop_last_user_message_removes_unanswered_user():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q1")
    # No assistant added → simulate a failed LLM call rolling back.
    removed = memory.pop_last_user_message()
    assert removed is True
    msgs = memory.get_messages()
    assert [m["role"] for m in msgs] == ["system"]


def test_pop_last_user_message_preserves_prior_assistant_pairs():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q1")
    memory.add_assistant_message(content="a1")
    memory.add_user_message("q2")
    memory.pop_last_user_message()
    msgs = memory.get_messages()
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert msgs[-1]["content"] == "a1"


def test_pop_last_user_message_returns_false_when_no_user():
    memory = Memory(system_prompt="sys")
    assert memory.pop_last_user_message() is False
    # System prompt must never be removed.
    msgs = memory.get_messages()
    assert [m["role"] for m in msgs] == ["system"]


def test_pop_last_user_message_preserves_system_prompt():
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q1")
    memory.pop_last_user_message()
    msgs = memory.get_messages()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"


def test_add_user_message_does_not_drop_when_assistant_present():
    """Normal flow: user → assistant → user should preserve all messages."""
    memory = Memory(system_prompt="sys")
    memory.add_user_message("q1")
    memory.add_assistant_message(content="a1")
    memory.add_user_message("q2")
    msgs = memory.get_messages()
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
