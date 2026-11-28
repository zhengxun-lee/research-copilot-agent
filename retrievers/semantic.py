from __future__ import annotations

import math
from typing import Optional

from .base import BaseRetriever
from .loader import load_knowledge_base
from .utils import cosine_similarity, expand_with_synonyms, hash_token_index, hash_token_sign, safe_chunk_index, tokenize


class SemanticHasherRetriever(BaseRetriever):
    """Dependency-free semantic retriever using stable hashed token vectors."""

    def __init__(self, dimensions: int = 256, extra_synonyms: Optional[dict] = None):
        self.dimensions = max(64, dimensions)
        self._indexed_items = None
        self._entries = []
        self._doc_count = 0
        self._doc_freq = {}
        self._term_to_doc_indices = {}
        self._synonyms = {
            "rag": ["retrieval", "augmented", "generation", "检索增强生成"],
            "llm": ["large", "language", "model", "大语言模型"],
            "cnn": ["convolutional", "network", "卷积神经网络"],
            "rcnn": ["region", "cnn", "目标检测"],
            "attention": ["self", "attend", "注意力"],
            "transformer": ["encoder", "decoder", "attention", "变换器"],
            "bert": ["bidirectional", "encoder", "预训练"],
            "resnet": ["residual", "skip", "残差网络"],
        }
        if extra_synonyms:
            for key, values in extra_synonyms.items():
                existing = self._synonyms.setdefault(key, [])
                existing.extend(values)

    def _tokenize(self, text: str) -> list[str]:
        return tokenize(text)

    def _expand_query_tokens(self, query_tokens: list[str]) -> list[str]:
        return expand_with_synonyms(query_tokens, self._synonyms)

    def _ensure_index(self, knowledge_items: list[dict]):
        if knowledge_items is self._indexed_items:
            return
        entries = []
        doc_freq = {}
        term_to_doc = {}
        for doc_index, item in enumerate(knowledge_items):
            title_tokens = self._tokenize(str(item.get("title") or ""))
            content_tokens = self._tokenize(str(item.get("content") or ""))
            weighted_tokens = title_tokens + title_tokens + content_tokens
            for term in set(weighted_tokens):
                doc_freq[term] = doc_freq.get(term, 0) + 1
                term_to_doc.setdefault(term, set()).add(doc_index)
            entries.append({"item": item, "tokens": weighted_tokens, "vector": None})
        self._entries = entries
        self._doc_count = len(entries)
        self._doc_freq = doc_freq
        self._term_to_doc_indices = term_to_doc
        for entry in self._entries:
            entry["vector"] = self._to_sparse_vector(entry["tokens"])
        self._indexed_items = knowledge_items

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        return math.log(1 + (self._doc_count - df + 0.5) / (df + 0.5))

    def _to_sparse_vector(self, tokens: list[str]) -> dict[int, float]:
        freq = {}
        for token in tokens:
            freq[token] = freq.get(token, 0) + 1
        vector = {}
        for token, count in freq.items():
            index = hash_token_index(token, self.dimensions)
            weight = (1.0 + math.log(count)) * self._idf(token)
            vector[index] = vector.get(index, 0.0) + hash_token_sign(token) * weight
        norm = math.sqrt(sum(v * v for v in vector.values()))
        if norm > 0:
            for index in list(vector.keys()):
                vector[index] /= norm
        return vector

    MAX_FALLBACK_CANDIDATES = 200

    def _candidate_indices(self, query_tokens: list[str]) -> list[int]:
        candidates = set()
        for token in query_tokens:
            candidates.update(self._term_to_doc_indices.get(token, ()))
        if candidates:
            return sorted(candidates)
        if self._doc_count <= self.MAX_FALLBACK_CANDIDATES:
            return list(range(self._doc_count))
        return sorted(
            range(self._doc_count),
            key=lambda i: len(self._entries[i]["tokens"]),
            reverse=True,
        )[: self.MAX_FALLBACK_CANDIDATES]

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if top_k <= 0:
            return []
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        query_tokens = self._expand_query_tokens(query_tokens)
        knowledge_items = load_knowledge_base()
        self._ensure_index(knowledge_items)
        query_vector = self._to_sparse_vector(query_tokens)
        scored = []
        for index in self._candidate_indices(query_tokens):
            entry = self._entries[index]
            score = cosine_similarity(query_vector, entry["vector"])
            if score > 0:
                scored.append({"item": entry["item"], "score": score})
        scored.sort(key=lambda x: (-x["score"], safe_chunk_index(x["item"])))
        return scored[:top_k]


_default_retriever = None


def search_semantic(query: str, top_k: int = 3) -> list[dict]:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = SemanticHasherRetriever()
    return _default_retriever.search(query, top_k)
