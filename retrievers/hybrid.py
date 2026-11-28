from __future__ import annotations

from config import RETRIEVAL_ENABLE_EMBEDDING, RETRIEVAL_HYBRID_CANDIDATES

from .base import BaseRetriever
from .keyword import KeywordRetriever
from .semantic import SemanticHasherRetriever
from .utils import result_key, safe_chunk_index
from .vector import OpenAIEmbeddingRetriever


class HybridRetriever(BaseRetriever):
    """Fuse lexical, local semantic, and optional dense vector retrieval."""

    def __init__(
        self,
        keyword_weight: float = 0.50,
        semantic_weight: float = 0.15,
        vector_weight: float = 0.35,
        vector_enabled: bool = RETRIEVAL_ENABLE_EMBEDDING,
        rrf_k: int = 50,
    ):
        self.keyword = KeywordRetriever()
        self.semantic = SemanticHasherRetriever()
        self.vector = OpenAIEmbeddingRetriever(enabled=vector_enabled)
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight
        self.vector_weight = vector_weight
        self.rrf_k = max(1, rrf_k)

    def _add_source(self, fused: dict, results: list[dict], weight: float, source_name: str):
        # Reciprocal Rank Fusion — only ranks matter, raw scores are recorded
        # separately for transparency / debugging.
        for rank, result in enumerate(results, start=1):
            key = result_key(result)
            bucket = fused.setdefault(key, {
                "item": result["item"],
                "score": 0.0,
                "sources": {},
            })
            bucket["score"] += weight * (1.0 / (self.rrf_k + rank))
            bucket["sources"][source_name] = result.get("score", 0.0)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if top_k <= 0:
            return []
        candidate_k = max(top_k, RETRIEVAL_HYBRID_CANDIDATES)
        keyword_results = self.keyword.search(query, top_k=candidate_k)
        semantic_results = self.semantic.search(query, top_k=candidate_k)
        vector_results = self.vector.search(query, top_k=candidate_k) if self.vector.enabled else []

        active_sources = [
            results for results in (keyword_results, semantic_results, vector_results) if results
        ]
        if not active_sources:
            return []
        if len(active_sources) == 1:
            # Single-source path still needs a deterministic sort key for parity
            # with multi-source fusion.
            return sorted(
                [{"item": r["item"], "score": r.get("score", 0.0)} for r in active_sources[0]],
                key=lambda x: (-x["score"], safe_chunk_index(x["item"])),
            )[:top_k]

        fused = {}
        self._add_source(fused, keyword_results, self.keyword_weight, "keyword")
        self._add_source(fused, semantic_results, self.semantic_weight, "semantic")
        self._add_source(fused, vector_results, self.vector_weight, "vector")
        ranked = sorted(
            fused.values(),
            key=lambda x: (-x["score"], safe_chunk_index(x["item"])),
        )
        return [{"item": result["item"], "score": result["score"]} for result in ranked[:top_k]]


_default_retriever = None


def search_hybrid(query: str, top_k: int = 3) -> list[dict]:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = HybridRetriever()
    return _default_retriever.search(query, top_k)
