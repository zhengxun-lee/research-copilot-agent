from types import SimpleNamespace

from agent.parser import parse_tool_calls


def test_parse_tool_calls_reports_bad_json():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                type="function",
                function=SimpleNamespace(name="calculator", arguments="{bad"),
            )
        ]
    )

    parsed = parse_tool_calls(message)

    assert parsed[0]["name"] == "calculator"
    assert parsed[0]["parse_error"].startswith("JSON parse failed")


def test_parse_tool_calls_handles_missing_function_attribute():
    """Some malformed responses send a tool_call without a ``function`` field."""
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(id="call-1", type="function"),
        ]
    )

    parsed = parse_tool_calls(message)

    assert parsed[0]["name"] == "unknown"
    assert "malformed" in parsed[0]["parse_error"].lower()
    assert parsed[0]["arguments"] == {}


def test_parse_tool_calls_returns_empty_list_when_no_tool_calls():
    message = SimpleNamespace(content="hello", tool_calls=None)
    assert parse_tool_calls(message) == []


def test_parse_tool_calls_parses_valid_arguments():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-2",
                type="function",
                function=SimpleNamespace(
                    name="calculator",
                    arguments='{"expression": "1 + 2"}',
                ),
            )
        ]
    )

    parsed = parse_tool_calls(message)

    assert parsed[0]["name"] == "calculator"
    assert parsed[0]["arguments"] == {"expression": "1 + 2"}
    assert parsed[0]["parse_error"] is None
    assert parsed[0]["raw_arguments"] == '{"expression": "1 + 2"}'


def test_parse_tool_calls_treats_empty_arguments_as_empty_object():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-3",
                type="function",
                function=SimpleNamespace(name="ping", arguments=""),
            )
        ]
    )

    parsed = parse_tool_calls(message)

    assert parsed[0]["arguments"] == {}
    assert parsed[0]["parse_error"] is None
