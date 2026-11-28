import json

from retrievers import loader
from tools.knowledge import KnowledgeSearchTool


def test_knowledge_tool_adds_neighbor_context(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps([
            {
                "doc_id": "d1",
                "title": "Doc",
                "content": "previous context",
                "page_number": 1,
                "source_path": "doc.pdf",
                "chunk_id": "c0",
                "chunk_index": 0,
                "next_chunk_id": "c1",
            },
            {
                "doc_id": "d1",
                "title": "Doc",
                "content": "main answer about retrieval",
                "page_number": 1,
                "source_path": "doc.pdf",
                "chunk_id": "c1",
                "chunk_index": 1,
                "prev_chunk_id": "c0",
                "next_chunk_id": "c2",
            },
            {
                "doc_id": "d1",
                "title": "Doc",
                "content": "next context",
                "page_number": 1,
                "source_path": "doc.pdf",
                "chunk_id": "c2",
                "chunk_index": 2,
                "prev_chunk_id": "c1",
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", str(kb_path))
    loader.clear_knowledge_base_cache()

    output = KnowledgeSearchTool().run(query="retrieval")

    assert "main answer" in output
    assert "Prev Context: previous context" in output
    assert "Next Context: next context" in output


def test_knowledge_tool_validates_top_k_type():
    output = KnowledgeSearchTool().run(query="retrieval", top_k="3")

    assert output == "Error: 'top_k' must be an integer."
