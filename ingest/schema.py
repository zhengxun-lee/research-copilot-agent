from dataclasses import dataclass
from typing import Optional


def _safe_int(value, default: int = 0) -> int:
    """Convert *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Sentinel used by :class:`Chunk` to mean "no chunk_index was supplied"
# (e.g. legacy data imported before chunk_index was tracked).  Comparing
# against this lets downstream sort logic push unsorted entries to the end of
# the list instead of the front (where default-zero would collide with the
# legitimate first chunk).
MISSING_CHUNK_INDEX = -1


@dataclass
class Chunk:
    doc_id: str
    title: str
    content: str
    source_path: str
    source_rel_path: str
    source_hash: str
    page_number: int
    chunk_id: str
    chunk_index: int
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    char_count: int = 0

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "content": self.content,
            "source_path": self.source_path,
            "source_rel_path": self.source_rel_path,
            "source_hash": self.source_hash,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "prev_chunk_id": self.prev_chunk_id,
            "next_chunk_id": self.next_chunk_id,
            "char_count": self.char_count or len(self.content),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        raw_index = data.get("chunk_index")
        chunk_index = (
            _safe_int(raw_index) if raw_index is not None else MISSING_CHUNK_INDEX
        )
        return cls(
            doc_id=data.get("doc_id", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            source_path=data.get("source_path", ""),
            source_rel_path=data.get("source_rel_path", ""),
            source_hash=data.get("source_hash", ""),
            page_number=_safe_int(data.get("page_number") or data.get("page"), default=0),
            chunk_id=data.get("chunk_id", ""),
            chunk_index=chunk_index,
            prev_chunk_id=data.get("prev_chunk_id"),
            next_chunk_id=data.get("next_chunk_id"),
            char_count=_safe_int(data.get("char_count"), default=len(data.get("content", ""))),
        )
