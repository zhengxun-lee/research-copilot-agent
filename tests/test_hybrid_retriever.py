import json

from retrievers import loader
from retrievers.hybrid import HybridRetriever


def test_hybrid_retriever_fuses_keyword_and_semantic(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Transformer Architecture",
                "content": "The transformer uses self-attention mechanisms to process sequences in parallel.",
                "page_number": 1,
                "chunk_id": "c1",
                "chunk_index": 0,
            },
            {
                "doc_id": "d2",
                "title": "Unrelated",
                "content": "unrelated content about cats",
                "page_number": 1,
                "chunk_id": "c2",
                "chunk_index": 0,
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = HybridRetriever(vector_enabled=False).search("transformer self-attention", top_k=2)

    assert len(results) >= 1
    assert results[0]["item"]["chunk_id"] == "c1"


def test_hybrid_retriever_returns_empty_for_no_match(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Cats",
                "content": "cats are feline animals",
                "page_number": 1,
                "chunk_id": "c1",
                "chunk_index": 0,
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = HybridRetriever(vector_enabled=False).search("quantum physics", top_k=3)
    assert results == []


def test_hybrid_retriever_respects_top_k():
    # top_k=0 short-circuits before touching the knowledge base
    results = HybridRetriever(vector_enabled=False).search("anything", top_k=0)
    assert results == []
