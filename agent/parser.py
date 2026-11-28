import json
from typing import Any, Dict, List


def parse_tool_calls(message: Any) -> List[Dict[str, Any]]:
    """Extract tool-call requests from an OpenAI chat-completion *message*.

    Returns a list of dicts, each containing ``id``, ``type``, ``name``,
    ``raw_arguments``, ``arguments`` (parsed JSON, or ``{}`` on failure),
    and ``parse_error`` (``None`` or a human-readable error string).
    """
    result = []
    tool_calls = getattr(message, "tool_calls", None) or []

    for call in tool_calls:
        func = getattr(call, "function", None)
        if func is None:
            result.append({
                "id": getattr(call, "id", ""),
                "type": getattr(call, "type", "function"),
                "name": "unknown",
                "raw_arguments": "{}",
                "arguments": {},
                "parse_error": "Tool call missing 'function' attribute — malformed response.",
            })
            continue
        raw_args = func.arguments or "{}"
        parse_error = None
        arguments = {}

        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as e:
            parse_error = f"JSON parse failed: {e}"

        result.append({
            "id": getattr(call, "id", ""),
            "type": getattr(call, "type", "function"),
            "name": getattr(func, "name", "unknown"),
            "raw_arguments": raw_args,
            "arguments": arguments,
            "parse_error": parse_error,
        })

    return result