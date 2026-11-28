from __future__ import annotations

import math
import re

from .base import BaseRetriever
from .loader import load_knowledge_base
from .utils import compact_text, result_key, safe_chunk_index, tokenize


class KeywordRetriever(BaseRetriever):
    """Keyword retriever with cached inverted index and BM25-style scoring."""

    def __init__(self):
        self._indexed_items = None
        self._index = []
        self._inverted_index = {}
        self._doc_freq = {}
        self._doc_count = 0
        self._avg_content_len = 1.0

    def _tokenize(self, text: str, for_query: bool = False) -> list[str]:
        return tokenize(text, for_query=for_query)

    def _normalize_query_terms(self, query: str) -> list[str]:
        tokens = self._tokenize(query, for_query=True)
        terms = []
        seen = set()
        for token in tokens:
            if token in seen:
                continue
            terms.append(token)
            seen.add(token)
        return terms

    def _count_term_frequency(self, tokens: list[str]) -> dict[str, int]:
        freq = {}
        for token in tokens:
            freq[token] = freq.get(token, 0) + 1
        return freq

    def _make_index_entry(self, item: dict) -> dict:
        title = str(item.get("title") or "")
        content = str(item.get("content") or "")
        title_tokens = self._tokenize(title)
        content_tokens = self._tokenize(content)
        return {
            "item": item,
            "title_lower": title.lower(),
            "content_lower": content.lower(),
            "title_compact": compact_text(title),
            "content_compact": compact_text(content),
            "title_freq": self._count_term_frequency(title_tokens),
            "content_freq": self._count_term_frequency(content_tokens),
            "content_terms": set(content_tokens),
            "title_len": max(1, len(title_tokens)),
            "content_len": max(1, len(content_tokens)),
        }

    def _ensure_index(self, knowledge_items: list[dict]):
        if knowledge_items is self._indexed_items:
            return
        self._index = [self._make_index_entry(item) for item in knowledge_items]
        self._doc_count = len(self._index)
        self._avg_content_len = (
            sum(entry["content_len"] for entry in self._index) / self._doc_count
            if self._doc_count
            else 1.0
        )
        doc_freq = {}
        inverted_index = {}
        for index, entry in enumerate(self._index):
            item_terms = set(entry["title_freq"]) | set(entry["content_freq"])
            for term in item_terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1
                inverted_index.setdefault(term, set()).add(index)
        self._doc_freq = doc_freq
        self._inverted_index = inverted_index
        self._indexed_items = knowledge_items

    def _candidate_indices(self, query_terms: list[str]) -> list[int]:
        candidates = set()
        for term in query_terms:
            candidates.update(self._inverted_index.get(term, ()))
        return sorted(candidates)

    def _extract_query_phrases(self, query: str, query_terms: list[str]) -> list[str]:
        phrases = []
        seen_raw = set()
        seen_compact = set()

        def add_phrase(candidate: str):
            candidate = candidate.strip()
            comp = compact_text(candidate)
            if len(comp) < 2 or comp in seen_compact or candidate in seen_raw:
                return
            seen_raw.add(candidate)
            seen_compact.add(comp)
            phrases.append(candidate)

        for part in re.split(r"[，。！？；;,.!?\n]+", query.lower()):
            if len(part.strip()) >= 4:
                add_phrase(part)
        if len(query_terms) >= 2:
            for index in range(len(query_terms) - 1):
                pair = query_terms[index:index + 2]
                add_phrase(" ".join(pair))
                add_phrase("".join(pair))
        return phrases

    def _phrase_bonus(self, entry: dict, phrases: list[str]) -> float:
        bonus = 0.0
        for phrase in phrases:
            comp = compact_text(phrase)
            if len(comp) < 2:
                continue
            if comp in entry["title_compact"]:
                bonus += 1.8
            elif comp in entry["content_compact"]:
                bonus += 0.9
        return bonus

    def _is_redundant_result(self, candidate: dict, selected: list[dict]) -> bool:
        candidate_item = candidate["item"]
        candidate_doc = candidate_item.get("doc_id")
        candidate_page = candidate_item.get("page_number", candidate_item.get("page"))
        candidate_index = safe_chunk_index(candidate_item, default=-10**9)
        candidate_terms = candidate["entry"]["content_terms"]
        for chosen in selected:
            chosen_item = chosen["item"]
            chosen_doc = chosen_item.get("doc_id")
            # If either doc_id is missing, skip the redundancy check — we can't
            # reliably determine whether the items belong to the same document.
            if candidate_doc is None or chosen_doc is None or candidate_doc != chosen_doc:
                continue
            if abs(candidate_index - safe_chunk_index(chosen_item)) <= 1:
                return True
            if candidate_page != chosen_item.get("page_number", chosen_item.get("page")):
                continue
            chosen_terms = chosen["entry"]["content_terms"]
            if candidate_terms and chosen_terms:
                overlap_ratio = len(candidate_terms & chosen_terms) / max(len(candidate_terms), 1)
                if overlap_ratio >= 0.85:
                    return True
        return False

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        return math.log(1 + (self._doc_count - df + 0.5) / (df + 0.5))

    def _bm25_tf(self, freq: int, doc_len: int, avg_doc_len: float) -> float:
        if freq <= 0:
            return 0.0
        k1 = 1.5
        b = 0.75
        denominator = freq + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1.0))
        return freq * (k1 + 1) / denominator

    def _score_entry(self, entry: dict, query_terms: list[str], compact_query: str = "") -> float:
        score = 0.0
        matched_terms = 0
        for term in query_terms:
            title_hits = entry["title_freq"].get(term, 0)
            content_hits = entry["content_freq"].get(term, 0)
            if title_hits == 0 and content_hits == 0:
                continue
            matched_terms += 1
            idf = self._idf(term)
            score += idf * self._bm25_tf(title_hits, entry["title_len"], self._avg_content_len) * 3.5
            score += idf * self._bm25_tf(content_hits, entry["content_len"], self._avg_content_len)
            if term in entry["title_lower"]:
                score += idf * 1.5
            if term in entry["content_lower"]:
                score += idf * 0.25
        if matched_terms == 0:
            return 0.0
        if len(compact_query) >= 2:
            if compact_query in entry["title_compact"]:
                score += 3.0
            if compact_query in entry["content_compact"]:
                score += 1.5
        coverage = matched_terms / max(len(query_terms), 1)
        return score * (0.5 + coverage)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if top_k <= 0:
            return []
        query_terms = self._normalize_query_terms(query)
        if not query_terms:
            return []
        knowledge_items = load_knowledge_base()
        self._ensure_index(knowledge_items)
        candidate_indices = self._candidate_indices(query_terms)
        if not candidate_indices:
            return []

        compact_query = compact_text(query)
        scored_results = []
        for index in candidate_indices:
            entry = self._index[index]
            score = self._score_entry(entry, query_terms, compact_query=compact_query)
            if score > 0:
                scored_results.append({"item": entry["item"], "score": score, "entry": entry})
        scored_results.sort(key=lambda x: (-x["score"], safe_chunk_index(x["item"])))

        phrases = self._extract_query_phrases(query, query_terms)
        if phrases and scored_results:
            rerank_window = min(len(scored_results), max(top_k * 6, 12))
            rerank_slice = scored_results[:rerank_window]
            for result in rerank_slice:
                result["score"] += self._phrase_bonus(result["entry"], phrases)
            rerank_slice.sort(key=lambda x: (-x["score"], safe_chunk_index(x["item"])))
            scored_results = rerank_slice + scored_results[rerank_window:]

        selected = []
        selected_keys = set()
        for result in scored_results:
            if self._is_redundant_result(result, selected):
                continue
            selected.append(result)
            selected_keys.add(result_key(result))
            if len(selected) >= top_k:
                break
        if len(selected) < top_k:
            for result in scored_results:
                if result_key(result) in selected_keys:
                    continue
                if self._is_redundant_result(result, selected):
                    continue
                selected.append(result)
                selected_keys.add(result_key(result))
                if len(selected) >= top_k:
                    break
        return [{"item": result["item"], "score": result["score"]} for result in selected]


_default_retriever = None


def search(query: str, top_k: int = 3) -> list[dict]:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = KeywordRetriever()
    return _default_retriever.search(query, top_k)
