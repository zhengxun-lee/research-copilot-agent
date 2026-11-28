from __future__ import annotations

import re

from retrievers.utils import CJK_RE, split_sentences

# Separator used between segments when packing chunks.
_SEGMENT_SEP = "\n\n"
_SEGMENT_SEP_LEN = len(_SEGMENT_SEP)


def _is_mostly_cjk(text: str) -> bool:
    """Return True when *text* is predominantly CJK (no inter-word spaces needed)."""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if CJK_RE.match(ch))
    return cjk_count > len(text) * 0.5


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if paragraphs:
        return paragraphs
    return [text.strip()] if text.strip() else []


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = split_sentences(paragraph)
    # CJK text doesn't use inter-word spaces — joining sentences with a space
    # would inject spurious whitespace that degrades bigram tokenization.
    sep = "" if _is_mostly_cjk(paragraph) else " "
    segments = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer}{sep}{sentence}".strip() if buffer else sentence
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            segments.append(buffer)
        if len(sentence) <= max_chars:
            buffer = sentence
        else:
            segments.extend(sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars))
            buffer = ""
    if buffer:
        segments.append(buffer)
    return segments or [paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars)]


def _make_overlap(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    if len(text) <= overlap_chars:
        return text
    tail = text[-overlap_chars:].strip()
    boundary = max(
        tail.rfind("。"), tail.rfind("！"), tail.rfind("？"),
        tail.rfind("."), tail.rfind("!"), tail.rfind("?"),
    )
    if 0 <= boundary < len(tail) - 1:
        tail = tail[boundary:].strip()
    return tail


def _fit_with_overlap(overlap: str, segment: str, max_chars: int) -> str:
    if not overlap:
        return segment
    candidate = f"{overlap}{_SEGMENT_SEP}{segment}".strip()
    if len(candidate) <= max_chars:
        return candidate
    available = max_chars - len(segment) - _SEGMENT_SEP_LEN
    if available <= 0:
        return segment
    trimmed_overlap = overlap[-available:].strip()
    return f"{trimmed_overlap}{_SEGMENT_SEP}{segment}".strip()


def _pack_segments(segments: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    chunks = []
    current = ""
    for segment in segments:
        candidate = f"{current}{_SEGMENT_SEP}{segment}".strip() if current else segment
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            overlap = _make_overlap(current, overlap_chars)
            current = _fit_with_overlap(overlap, segment, max_chars)
        else:
            # Segment alone exceeds max_chars (should be rare); truncate as safety net.
            chunks.append(segment[:max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def chunk_page_text(page_text: str, max_chars: int = 500, overlap_chars: int = 80) -> list[str]:
    if not page_text or not page_text.strip():
        return []
    max_chars = max(100, max_chars)
    overlap_chars = min(max(0, overlap_chars), max_chars // 3)
    segments = []
    for paragraph in _split_paragraphs(page_text):
        segments.extend(_split_long_paragraph(paragraph, max_chars=max_chars))
    return [chunk.strip() for chunk in _pack_segments(segments, max_chars, overlap_chars) if chunk.strip()]
