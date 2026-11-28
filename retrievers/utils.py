import hashlib
import re
from typing import Dict, List, Pattern, Set, Union


# ---------------------------------------------------------------------------
# Shared tokenizer used across all retrievers and encoders.
# ---------------------------------------------------------------------------

TOKEN_RE: Pattern[str] = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*|[一-鿿]+")
CJK_RE: Pattern[str] = re.compile(r"^[一-鿿]+$")


# Stopwords that carry little semantic signal in retrieval contexts.
STOPWORDS: Set[str] = {
    "what", "is", "the", "a", "an", "of", "in", "on", "for", "to",
    "and", "or", "does", "say", "about", "please", "explain",
    "this", "that", "with", "as", "by", "from", "at", "be",
    "can", "could", "would", "should", "will", "do", "how",
    "why", "when", "where", "which",
    "的", "是", "在", "和", "了", "我", "有", "个", "们",
    "这", "那", "你", "他", "她", "它", "与", "或", "但",
    "把", "被", "让", "从", "到", "为", "以", "及", "其",
    "而", "如", "所", "对", "就", "都", "也", "要", "会",
    "能", "可", "将", "向", "更", "最", "已", "已经", "正在",
    "什么", "如何", "怎么", "为什么", "请", "请问", "解释",
    "说明", "一下", "本文", "论文", "文档", "知识库", "关于",
}

CJK_QUERY_BOUNDARY_STOP_CHARS: Set[str] = {
    "的", "是", "了", "在", "和", "与", "或", "把", "被",
    "让", "从", "到", "为", "以", "及", "其", "而", "如",
    "所", "就", "都", "也", "要", "会", "能", "可", "将",
    "向", "更", "最", "已", "请", "问", "吗", "呢", "么",
}

# ---------------------------------------------------------------------------
# Shared sentence-split regex (used by chunker and summarizer).
# ---------------------------------------------------------------------------

_SENTENCE_RE: Pattern[str] = re.compile(r"[^。！？.!?\n]+[。！？.!?]?")


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences for CJK and Latin scripts."""
    parts = _SENTENCE_RE.findall(text)
    return [part.strip() for part in parts if part.strip()]


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def tokenize(text: str, *, for_query: bool = False, remove_stopwords: bool = False) -> List[str]:
    """Tokenize text into a list of retrieval-friendly tokens.

    Splits on word boundaries for Latin script and produces bigrams for CJK.
    Compound tokens (``-`` / ``_`` delimited) are split into sub-tokens and
    the concatenated form is added as an extra token.

    Parameters
    ----------
    text:
        Input text (case-folded to lower).
    for_query:
        When *True*, CJK bigrams containing boundary stop-characters are
        skipped (useful for query-side tokenization).
    remove_stopwords:
        When *True*, tokens listed in the shared stopword set are dropped.
    """
    text = str(text or "").lower()
    tokens: List[str] = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0)
        if CJK_RE.match(token):
            tokens.extend(_tokenize_cjk(token, for_query=for_query, remove_stopwords=remove_stopwords))
            continue
        if remove_stopwords and token in STOPWORDS:
            continue
        tokens.append(token)
        if "-" in token or "_" in token:
            parts = [p for p in re.split(r"[-_]+", token) if p]
            for part in parts:
                if not remove_stopwords or part not in STOPWORDS:
                    tokens.append(part)
            if len(parts) > 1:
                merged = "".join(parts)
                if not remove_stopwords or merged not in STOPWORDS:
                    tokens.append(merged)
    return tokens


def _tokenize_cjk(text: str, *, for_query: bool = False, remove_stopwords: bool = False) -> List[str]:
    if len(text) == 1:
        if remove_stopwords and text in STOPWORDS:
            return []
        if for_query and text in CJK_QUERY_BOUNDARY_STOP_CHARS:
            return []
        return [text]
    tokens: List[str] = []
    for i in range(len(text) - 1):
        token = text[i:i + 2]
        if for_query and all(ch in CJK_QUERY_BOUNDARY_STOP_CHARS for ch in token):
            continue
        if remove_stopwords and token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def expand_with_synonyms(tokens: List[str], synonyms: dict) -> List[str]:
    """Expand a token list using a synonym map (token → related tokens)."""
    expanded: List[str] = []
    seen: Set[str] = set()
    for token in tokens:
        if token not in seen:
            expanded.append(token)
            seen.add(token)
        for synonym_text in synonyms.get(token, []):
            for syn_token in tokenize(synonym_text):
                if syn_token not in seen:
                    expanded.append(syn_token)
                    seen.add(syn_token)
    return expanded


# ---------------------------------------------------------------------------
# Cosine similarity (unified across dense and sparse vectors)
# ---------------------------------------------------------------------------

def cosine_similarity(
    left: Union[Dict[int, float], List[float]],
    right: Union[Dict[int, float], List[float]],
) -> float:
    """Cosine similarity supporting both dense (list) and sparse (dict) vectors.

    Dense vectors are **not** re-normalized — callers must pre-normalize or
    pass the result of :func:`_cosine_dense` which computes full cosine.

    Sparse vectors (``dict[int, float]``) are assumed **already L2-normalized**
    (only the dot product is computed).  Unnormalized sparse vectors will
    return incorrect similarity scores.
    """
    if isinstance(left, dict) and isinstance(right, dict):
        return _dot_product_sparse(left, right)
    if isinstance(left, list) and isinstance(right, list):
        return _cosine_dense(left, right)
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(
        "cosine_similarity received mismatched vector types: left=%s, right=%s. "
        "Returning 0.0 — this may be a bug in the caller.",
        type(left).__name__, type(right).__name__,
    )
    return 0.0


def _dot_product_sparse(left: Dict[int, float], right: Dict[int, float]) -> float:
    """Dot product of two sparse vectors (assumed already L2-normalized)."""
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def _cosine_dense(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def safe_chunk_index(item: dict, default: int = 10**9) -> int:
    try:
        return int(item.get("chunk_index", default))
    except (TypeError, ValueError):
        return default


def content_digest(content: str, digest_size: int = 8) -> str:
    return hashlib.blake2b(str(content).encode("utf-8"), digest_size=digest_size).hexdigest()


def result_key(result: dict) -> str:
    """Stable content-based key for deduplicating retrieval results."""
    item = result["item"]
    return str(item.get("chunk_id") or "|".join([
        str(item.get("doc_id", "")),
        str(item.get("page_number", "")),
        str(item.get("chunk_index", "")),
        content_digest(item.get("content", "")),
    ]))


def compact_text(text: str) -> str:
    """Remove whitespace, hyphens, and underscores for substring matching."""
    return re.sub(r"[\s\-_]+", "", str(text or "").lower())


# ---------------------------------------------------------------------------
# Shared stable-hash helpers (used by semantic retriever and hash encoder)
# ---------------------------------------------------------------------------


def hash_token_index(token: str, dimensions: int) -> int:
    """Deterministic dimension index for *token* in [0, *dimensions*)."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False) % dimensions


def hash_token_sign(token: str) -> float:
    """Deterministic sign (+1 or -1) for *token*."""
    digest = hashlib.blake2b(f"{token}:sign".encode("utf-8"), digest_size=8).digest()
    return 1.0 if int.from_bytes(digest, byteorder="big", signed=False) % 2 == 0 else -1.0
