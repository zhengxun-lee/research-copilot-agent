"""Unified retrieval API — :func:`search` dispatches to the active retrieval
mode (keyword / semantic / vector / hybrid) based on configuration."""

from __future__ import annotations

import logging
from typing import Optional

from config import _KNOWN_RETRIEVAL_MODES, RETRIEVAL_ENABLE_EMBEDDING, RETRIEVAL_MODE

from .base import BaseRetriever
from .formatter import format_results
from .hybrid import HybridRetriever, search_hybrid
from .keyword import KeywordRetriever, search as search_keyword
from .loader import load_knowledge_base
from .semantic import SemanticHasherRetriever, search_semantic
from .vector import OpenAIEmbeddingRetriever, search_vector

logger = logging.getLogger(__name__)


def search(query: str, top_k: int = 3, mode: Optional[str] = None) -> list[dict]:
    """Dispatch to the active retrieval mode.

    Returns a list of ``{"item": ..., "score": ..., "mode": ...}`` dicts so the
    caller can see which mode actually ran (important for "vector → semantic"
    fallbacks that previously happened silently).
    """
    retrieval_mode = (mode or RETRIEVAL_MODE).strip().lower()
    fallback_reason: Optional[str] = None
    if retrieval_mode not in _KNOWN_RETRIEVAL_MODES:
        logger.warning(
            "Unknown retrieval mode '%s' (known: %s), falling back to keyword",
            retrieval_mode,
            ", ".join(sorted(_KNOWN_RETRIEVAL_MODES)),
        )
        fallback_reason = f"unknown mode {retrieval_mode!r}"
        retrieval_mode = "keyword"
    if retrieval_mode == "vector" and not RETRIEVAL_ENABLE_EMBEDDING:
        logger.warning(
            "RETRIEVAL_MODE=vector but RETRIEVAL_ENABLE_EMBEDDING=false; "
            "falling back to local semantic retrieval. Set RETRIEVAL_ENABLE_EMBEDDING=true "
            "and configure EMBEDDING_API_KEY to use vector mode."
        )
        fallback_reason = "embedding disabled"
        retrieval_mode = "semantic"

    runners = {
        "hybrid": search_hybrid,
        "semantic": search_semantic,
        "vector": search_vector,
    }
    runner = runners.get(retrieval_mode, search_keyword)
    results = runner(query, top_k=top_k)
    if fallback_reason:
        for result in results:
            result.setdefault("mode", retrieval_mode)
            result.setdefault("fallback_reason", fallback_reason)
    return results


__all__ = [
    "BaseRetriever",
    "HybridRetriever",
    "KeywordRetriever",
    "OpenAIEmbeddingRetriever",
    "SemanticHasherRetriever",
    "format_results",
    "load_knowledge_base",
    "search",
    "search_hybrid",
    "search_keyword",
    "search_semantic",
    "search_vector",
]
