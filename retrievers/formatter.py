from __future__ import annotations


def _first_not_none(item: dict, *keys: str, default: str = "unknown") -> object:
    """Return the first *key* in *item* whose value is not ``None``."""
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return default


def _truncate(text: str, max_chars: int = 260) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


# Hard cap to prevent context-window overflow from very long knowledge results.
MAX_TOTAL_CHARS = 3200


def format_results(results: list[dict]) -> str:
    if not results:
        return "No relevant knowledge found."

    formatted = []
    total_chars = 0
    for result in results:
        # Scale per-result content budget by remaining total budget.
        remaining_budget = max(300, MAX_TOTAL_CHARS - total_chars)
        content_limit = min(1200, remaining_budget)
        field_limit = min(260, max(80, remaining_budget // 3))

        item = result["item"]
        score = result["score"]
        page = _first_not_none(item, "page_number", "page")
        source = _first_not_none(item, "source_path", "source_rel_path")

        block = (
            f"Score: {score:.2f}\n"
            f"Title: {_truncate(item.get('title', ''), max_chars=field_limit)}\n"
            f"Doc ID: {_truncate(item.get('doc_id', 'unknown'), max_chars=field_limit)}\n"
            f"Page: {page}\n"
            f"Source: {_truncate(source, max_chars=field_limit)}\n"
            f"Content: {_truncate(item.get('content', ''), max_chars=content_limit)}"
        )

        prev_content = item.get("prev_content", "")
        next_content = item.get("next_content", "")
        if prev_content:
            extra = f"\nPrev Context: {_truncate(prev_content, max_chars=field_limit)}"
            if total_chars + len(block) + len(extra) < MAX_TOTAL_CHARS:
                block += extra
        if next_content:
            extra = f"\nNext Context: {_truncate(next_content, max_chars=field_limit)}"
            if total_chars + len(block) + len(extra) < MAX_TOTAL_CHARS:
                block += extra

        formatted.append(block)
        total_chars += len(block)
        if total_chars >= MAX_TOTAL_CHARS:
            break

    return "\n\n".join(formatted)
