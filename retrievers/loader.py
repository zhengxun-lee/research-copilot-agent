from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from config import KNOWLEDGE_BASE_PATH

_CACHE_SIGNATURE = None
_CACHE_DATA: Optional[list[dict]] = None
_CHUNK_INDEX: Optional[dict[str, dict]] = None


def _get_signature(path: Path):
    stat = path.stat()
    # Use st_mtime (float, seconds) instead of st_mtime_ns for portability
    # across all platforms (st_mtime_ns is not available everywhere).
    return (str(path.resolve()), stat.st_mtime, stat.st_size)


def _build_chunk_index(items: list[dict]) -> dict[str, dict]:
    """Map ``chunk_id`` → chunk dict for O(1) neighbour lookups.

    Skips items without a chunk_id so we don't pollute the index with
    legacy / malformed entries.
    """
    index: dict[str, dict] = {}
    for item in items:
        chunk_id = item.get("chunk_id")
        if chunk_id:
            index[chunk_id] = item
    return index


def load_knowledge_base(path: Optional[Union[str, Path]] = None) -> list[dict]:
    """Load the knowledge base from *path* (defaults to ``KNOWLEDGE_BASE_PATH``).

    Results are cached by file signature so repeated calls during the same
    process are cheap.  Call :func:`clear_knowledge_base_cache` after writing
    a new knowledge base to force a re-read.
    """
    global _CACHE_SIGNATURE, _CACHE_DATA, _CHUNK_INDEX

    resolved = Path(path or KNOWLEDGE_BASE_PATH)
    if not resolved.exists():
        raise FileNotFoundError(
            f"Knowledge base not found at {resolved}. Run `python3 -m ingest` first."
        )

    signature = _get_signature(resolved)
    if signature == _CACHE_SIGNATURE and _CACHE_DATA is not None:
        return _CACHE_DATA

    with resolved.open("r", encoding="utf-8") as file:
        raw_data = json.load(file)

    if isinstance(raw_data, dict):
        data = raw_data.get("chunks") or raw_data.get("items") or []
    elif isinstance(raw_data, list):
        data = raw_data
    else:
        data = []

    _CACHE_SIGNATURE = signature
    _CACHE_DATA = data
    _CHUNK_INDEX = _build_chunk_index(data)
    return data


def get_chunk_index(path: Optional[Union[str, Path]] = None) -> dict[str, dict]:
    """Return the cached ``chunk_id`` → chunk dict index.

    Triggers a knowledge-base load if the cache is cold; otherwise returns
    the already-built index without re-reading or rebuilding.  Used by tools
    that need to walk the prev/next chunk chain (e.g. neighbour context).
    """
    global _CHUNK_INDEX
    if _CHUNK_INDEX is None:
        load_knowledge_base(path)
    return _CHUNK_INDEX or {}


def clear_knowledge_base_cache():
    global _CACHE_SIGNATURE, _CACHE_DATA, _CHUNK_INDEX
    _CACHE_SIGNATURE = None
    _CACHE_DATA = None
    _CHUNK_INDEX = None
