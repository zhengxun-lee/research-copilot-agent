import json

import retrievers
from retrievers import loader


def test_search_dispatches_semantic_mode(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Transformer",
                "content": "Attention improves encoder decoder language models.",
                "page_number": 1,
                "chunk_id": "c1",
                "chunk_index": 0,
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = retrievers.search("transformer attention", top_k=1, mode="semantic")

    assert results
    assert results[0]["item"]["chunk_id"] == "c1"


def test_vector_mode_falls_back_to_local_semantic(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "RAG",
                "content": "Retrieval augmented generation combines search and language models.",
                "page_number": 1,
                "chunk_id": "c1",
                "chunk_index": 0,
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = retrievers.search("rag", top_k=1, mode="vector")

    assert results
    assert results[0]["item"]["chunk_id"] == "c1"
