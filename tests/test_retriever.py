import json
import os

from retrievers import loader
from retrievers.keyword import KeywordRetriever


def test_keyword_retriever_matches_cjk_terms(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "机器学习论文",
                "content": "本文介绍卷积神经网络和目标检测方法。",
                "page_number": 2,
                "chunk_id": "c1",
                "chunk_index": 0,
            },
            {
                "doc_id": "d2",
                "title": "Other",
                "content": "unrelated content",
                "page_number": 1,
                "chunk_id": "c2",
                "chunk_index": 0,
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = KeywordRetriever().search("卷积神经网络是什么", top_k=1)

    assert results
    assert results[0]["item"]["chunk_id"] == "c1"


def test_loader_accepts_wrapped_chunks(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps({"chunks": [{"chunk_id": "c1"}]}), encoding="utf-8")
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    assert loader.load_knowledge_base() == [{"chunk_id": "c1"}]


def test_loader_invalidates_cache_when_file_changes(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps([{"chunk_id": "old"}]), encoding="utf-8")
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    assert loader.load_knowledge_base() == [{"chunk_id": "old"}]

    kb_path.write_text(json.dumps([{"chunk_id": "new-chunk"}]), encoding="utf-8")
    os.utime(kb_path, None)

    assert loader.load_knowledge_base() == [{"chunk_id": "new-chunk"}]


def test_keyword_retriever_does_not_return_zero_score_noise(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Only cats",
                "content": "cats sleep on mats",
                "page_number": 1,
                "chunk_id": "c1",
                "chunk_index": 0,
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    assert KeywordRetriever().search("quantum transformer", top_k=3) == []


def test_keyword_retriever_handles_missing_chunk_index(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Legacy",
                "content": "retrieval works for legacy chunks",
                "page": 4,
                "chunk_id": "legacy",
                "chunk_index": None,
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = KeywordRetriever().search("retrieval legacy", top_k=1)

    assert results[0]["item"]["chunk_id"] == "legacy"


def test_keyword_retriever_handles_none_text_fields(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "bad",
                "title": None,
                "content": None,
                "chunk_id": "bad",
                "chunk_index": 0,
            },
            {
                "doc_id": "good",
                "title": "Retrieval",
                "content": "retrieval works even when another chunk has null text",
                "chunk_id": "good",
                "chunk_index": 1,
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    results = KeywordRetriever().search("retrieval", top_k=1)

    assert results[0]["item"]["chunk_id"] == "good"
