from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

from api_config import EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL_NAME
from config import (
    RETRIEVAL_ENABLE_EMBEDDING,
    RETRIEVAL_VECTOR_BATCH_SIZE,
    RETRIEVAL_VECTOR_CANDIDATES,
)

from .base import BaseRetriever
from .loader import load_knowledge_base
from .utils import content_digest, cosine_similarity, safe_chunk_index, tokenize

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency guard
    OpenAI = None


class OpenAIEmbeddingRetriever(BaseRetriever):
    """Optional dense vector retriever backed by an OpenAI-compatible embedding API."""

    def __init__(
        self,
        enabled: bool = RETRIEVAL_ENABLE_EMBEDDING,
        api_key: str = EMBEDDING_API_KEY,
        base_url: str = EMBEDDING_BASE_URL,
        model: str = EMBEDDING_MODEL_NAME,
        candidate_k: int = RETRIEVAL_VECTOR_CANDIDATES,
        batch_size: int = RETRIEVAL_VECTOR_BATCH_SIZE,
    ):
        self.enabled = bool(enabled and api_key and model and OpenAI is not None)
        self.model = model
        self.candidate_k = max(1, candidate_k)
        self.batch_size = max(1, batch_size)
        self._client = OpenAI(api_key=api_key, base_url=base_url) if self.enabled else None
        self._indexed_items = None
        self._entries: list[dict[str, Any]] = []
        self._vectors_by_key: dict[str, list[float]] = {}
        self._term_to_doc_indices: dict[str, set[int]] = {}

    def _tokenize(self, text: str) -> list[str]:
        return tokenize(text)

    def _item_vector_key(self, item: dict) -> str:
        digest = content_digest(str(item.get("content") or ""))
        chunk_id = item.get("chunk_id")
        if chunk_id:
            return f"{self.model}:{chunk_id}:{digest}"
        return "|".join([
            self.model,
            str(item.get("doc_id", "")),
            str(item.get("page_number", "")),
            str(item.get("chunk_index", "")),
            digest,
        ])

    def _embedding_input(self, item: dict) -> str:
        title = str(item.get("title") or "")
        content = str(item.get("content") or "")
        return f"{title}\n\n{content}".strip()

    def _ensure_index(self, knowledge_items: list[dict]):
        if knowledge_items is self._indexed_items:
            return
        entries = []
        term_to_doc = {}
        for doc_index, item in enumerate(knowledge_items):
            text = self._embedding_input(item)
            title_tokens = self._tokenize(str(item.get("title") or ""))
            content_tokens = self._tokenize(str(item.get("content") or ""))
            tokens = title_tokens + content_tokens
            for token in set(tokens):
                term_to_doc.setdefault(token, set()).add(doc_index)
            entries.append({
                "item": item,
                "key": self._item_vector_key(item),
                "text": text,
                "title_tokens": set(title_tokens),
                "tokens": set(tokens),
                "vector": None,
            })
        self._entries = entries
        self._term_to_doc_indices = term_to_doc
        self._indexed_items = knowledge_items

    def _candidate_indices(self, query: str) -> list[int]:
        query_tokens = set(self._tokenize(query))
        candidates = set()
        for token in query_tokens:
            candidates.update(self._term_to_doc_indices.get(token, ()))
        if not candidates:
            if len(self._entries) <= self.candidate_k:
                return list(range(len(self._entries)))
            return []
        ranked = sorted(
            candidates,
            key=lambda index: (
                -self._candidate_overlap_score(query_tokens, self._entries[index]),
                safe_chunk_index(self._entries[index]["item"]),
            ),
        )
        return ranked[: self.candidate_k]

    def _candidate_overlap_score(self, query_tokens: set[str], entry: dict) -> float:
        if not query_tokens:
            return 0.0
        title_overlap = len(query_tokens & entry["title_tokens"])
        body_overlap = len(query_tokens & entry["tokens"])
        coverage = body_overlap / max(len(query_tokens), 1)
        return title_overlap * 2.0 + body_overlap + coverage

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self._client:
            return []
        try:
            response = self._client.embeddings.create(model=self.model, input=texts)
        except Exception:
            logger.warning("Embedding API call failed for %d texts", len(texts), exc_info=True)
            return []
        return [self._normalize_vector(list(item.embedding)) for item in response.data]

    def _ensure_doc_vectors(self, candidate_indices: list[int]):
        missing = [
            index for index in candidate_indices
            if self._entries[index]["key"] not in self._vectors_by_key
        ]
        for offset in range(0, len(missing), self.batch_size):
            batch_indices = missing[offset: offset + self.batch_size]
            batch_texts = [self._entries[index]["text"] for index in batch_indices]
            batch_vectors = self._embed_texts(batch_texts)
            for index, vector in zip(batch_indices, batch_vectors):
                key = self._entries[index]["key"]
                self._vectors_by_key[key] = vector
                self._entries[index]["vector"] = vector
        for index in candidate_indices:
            key = self._entries[index]["key"]
            if key in self._vectors_by_key:
                self._entries[index]["vector"] = self._vectors_by_key[key]

    def _cosine(self, left: list[float], right: list[float]) -> float:
        return cosine_similarity(left, right)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.enabled or top_k <= 0 or not query.strip():
            return []
        knowledge_items = load_knowledge_base()
        self._ensure_index(knowledge_items)
        candidate_indices = self._candidate_indices(query)
        if not candidate_indices:
            return []
        query_vectors = self._embed_texts([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]
        self._ensure_doc_vectors(candidate_indices)
        scored = []
        for index in candidate_indices:
            entry = self._entries[index]
            score = self._cosine(query_vector, entry.get("vector") or [])
            if score > 0:
                scored.append({"item": entry["item"], "score": score})
        scored.sort(key=lambda x: (-x["score"], safe_chunk_index(x["item"])))
        return scored[:top_k]


_default_retriever = None


def search_vector(query: str, top_k: int = 3) -> list[dict]:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = OpenAIEmbeddingRetriever()
    return _default_retriever.search(query, top_k)
