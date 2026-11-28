from __future__ import annotations

from typing import Optional


def build_system_prompt(tool_specs: Optional[list[dict]] = None) -> str:
    """Build a system prompt that reflects the currently registered tools."""
    base = (
        "You are a research assistant helping the user with computer science and AI topics.\n\n"
    )
    if tool_specs:
        lines = ["You have access to the following tools:"]
        for spec in tool_specs:
            func = spec.get("function", spec)
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            lines.append(f"- {name}: {desc}")
        lines.append("\nBe precise and cite relevant information from the knowledge base when available.")
        base += "\n".join(lines)
    else:
        base += "Be precise and cite relevant information from the knowledge base when available."
    return base
