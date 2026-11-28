from ingest.builder import remove_existing_source_items


def test_remove_existing_source_items_keeps_identical_content_from_other_path():
    items = [
        {"source_path": "a.pdf", "source_hash": "same", "chunk_id": "a1"},
        {"source_path": "b.pdf", "source_hash": "same", "chunk_id": "b1"},
    ]

    remaining = remove_existing_source_items(items, source_path="a.pdf")

    assert remaining == [{"source_path": "b.pdf", "source_hash": "same", "chunk_id": "b1"}]


def test_make_doc_id_strips_path_separators_and_lowercases():
    from ingest.builder import make_doc_id

    class _FakePath:
        stem = "Some/Paper Title"

    assert make_doc_id(_FakePath(), "deadbeef" * 4).startswith("some-paper-title-")


def test_save_and_reload_roundtrip(tmp_path, monkeypatch):
    """save_knowledge_base writes atomically and loader can read it back."""
    import json
    from ingest.builder import save_knowledge_base
    from retrievers import loader

    out = tmp_path / "kb.json"
    items = [{"chunk_id": "c1", "content": "hello", "doc_id": "d1"}]
    save_knowledge_base(items, output_path=out)

    assert out.exists()
    data = json.loads(out.read_text("utf-8"))
    assert data == items

    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(out))
    loader.clear_knowledge_base_cache()
    assert loader.load_knowledge_base() == items
    assert "c1" in loader.get_chunk_index()


def test_import_pdf_folder_dedups_symlink_paths(tmp_path, monkeypatch):
    """Two rglob hits that resolve to the same absolute path must not be
    ingested twice."""
    from ingest import builder

    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    real_pdf = pdf_dir / "paper.pdf"
    real_pdf.write_bytes(b"%PDF-1.4\n%fake pdf body\n")
    nested = pdf_dir / "nested"
    nested.mkdir()
    link = nested / "paper.pdf"
    try:
        link.symlink_to(real_pdf)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("Symlinks not supported on this filesystem")

    seen_calls = []

    def fake_build(pdf_path, **kwargs):
        seen_calls.append(str(pdf_path.resolve()))
        return []

    monkeypatch.setattr(builder, "build_chunks_from_pdf", fake_build)
    monkeypatch.setattr(builder, "save_knowledge_base", lambda items, output_path: items)
    monkeypatch.setattr(builder, "load_knowledge_base_safe", lambda *a, **k: [])

    builder.import_pdf_folder(pdf_dir=pdf_dir, output_path=tmp_path / "kb.json")

    assert len(seen_calls) == 1, f"Expected one ingest call, got {len(seen_calls)}: {seen_calls}"


def test_import_pdf_folder_skips_missing_pdf_directory(tmp_path):
    """A missing directory should raise FileNotFoundError with the path."""
    import pytest
    from ingest import builder

    with pytest.raises(FileNotFoundError):
        builder.import_pdf_folder(pdf_dir=tmp_path / "nope", output_path=tmp_path / "kb.json")


def test_chunk_from_dict_missing_chunk_index_uses_sentinel():
    """Legacy chunks without ``chunk_index`` must be distinguishable from a
    genuine index-0 chunk (so sort order stays deterministic)."""
    from ingest.schema import Chunk, MISSING_CHUNK_INDEX

    c = Chunk.from_dict({
        "doc_id": "d",
        "title": "T",
        "content": "x",
        "source_path": "p",
        "source_rel_path": "p",
        "source_hash": "h",
        "page_number": 1,
        "chunk_id": "c1",
    })
    assert c.chunk_index == MISSING_CHUNK_INDEX
    assert c.chunk_index != 0


def test_chunk_from_dict_round_trip_preserves_index():
    from ingest.schema import Chunk

    original = Chunk(
        doc_id="d", title="T", content="x",
        source_path="p", source_rel_path="p", source_hash="h",
        page_number=1, chunk_id="c1", chunk_index=7,
    )
    data = original.to_dict()
    restored = Chunk.from_dict(data)
    assert restored.chunk_index == 7
