from ingest.chunker import chunk_page_text
from ingest.cleaner import clean_text
from ingest.pdf_parser import _extract_page_text
from ingest.schema import Chunk


def test_clean_text_repairs_line_break_hyphenation():
    assert clean_text("trans-\nformer\nmodel") == "transformer model"


def test_chunk_page_text_uses_overlap_without_empty_chunks():
    text = (
        "第一段内容很重要，介绍研究背景和核心问题。" * 4
        + "\n\n"
        + "第二段内容也很重要，继续说明方法和实验设置。" * 4
        + "\n\n"
        + "第三段继续解释结果、局限和未来工作。" * 4
    )
    chunks = chunk_page_text(text, max_chars=120, overlap_chars=20)

    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 120 for chunk in chunks)


def test_chunk_roundtrip_supports_legacy_page_field():
    chunk = Chunk.from_dict({
        "doc_id": "d1",
        "title": "Doc",
        "content": "hello",
        "source_path": "doc.pdf",
        "source_rel_path": "doc.pdf",
        "source_hash": "abc",
        "page": 3,
        "chunk_id": "c1",
        "chunk_index": 1,
    })

    assert chunk.page_number == 3
    assert chunk.to_dict()["char_count"] == 5


def test_rotated_pdf_page_uses_plain_extraction():
    class Page:
        rotation = 90

        def extract_text(self, extraction_mode=None):
            if extraction_mode == "layout":
                raise AssertionError("layout extraction should be skipped for rotated pages")
            return "rotated text"

    assert _extract_page_text(Page()) == "rotated text"
