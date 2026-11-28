from llm.prompts import build_system_prompt


def test_build_system_prompt_without_tools():
    prompt = build_system_prompt(tool_specs=None)
    assert "research assistant" in prompt.lower()
    assert "precise" in prompt.lower()


def test_build_system_prompt_includes_tool_names_and_descriptions():
    specs = [
        {
            "type": "function",
            "function": {"name": "search", "description": "Search the knowledge base."},
        },
        {
            "type": "function",
            "function": {"name": "calc", "description": "Evaluate math expressions."},
        },
    ]
    prompt = build_system_prompt(tool_specs=specs)
    assert "search" in prompt
    assert "Search the knowledge base" in prompt
    assert "calc" in prompt
    assert "Evaluate math expressions" in prompt


def test_build_system_prompt_handles_empty_tool_list():
    prompt = build_system_prompt(tool_specs=[])
    assert "research assistant" in prompt.lower()
    # With empty list, falls through to the no-tools path
    assert "precise" in prompt.lower()
