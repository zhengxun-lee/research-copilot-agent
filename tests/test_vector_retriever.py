from retrievers.vector import OpenAIEmbeddingRetriever


def test_vector_retriever_disabled_without_api():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="")

    assert retriever.search("anything", top_k=3) == []


def test_vector_key_changes_when_content_changes():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="")

    first = retriever._item_vector_key({"chunk_id": "c1", "content": "old"})
    second = retriever._item_vector_key({"chunk_id": "c1", "content": "new"})

    assert first != second


def test_vector_key_includes_model_name():
    first = OpenAIEmbeddingRetriever(enabled=False, api_key="", model="m1")
    second = OpenAIEmbeddingRetriever(enabled=False, api_key="", model="m2")

    assert first._item_vector_key({"chunk_id": "c1", "content": "same"}) != second._item_vector_key(
        {"chunk_id": "c1", "content": "same"}
    )


def test_vector_key_handles_none_content():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="")

    assert retriever._item_vector_key({"chunk_id": "c1", "content": None}).startswith(retriever.model)


def test_cosine_rejects_dimension_mismatch():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="")

    assert retriever._cosine([1.0, 0.0], [1.0]) == 0.0


def test_vector_candidates_rank_by_query_overlap():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="", candidate_k=2)
    retriever._entries = [
        {"item": {"chunk_index": 0}, "title_tokens": set(), "tokens": {"cat"}},
        {"item": {"chunk_index": 1}, "title_tokens": {"retrieval"}, "tokens": {"retrieval", "agent"}},
        {"item": {"chunk_index": 2}, "title_tokens": set(), "tokens": {"retrieval"}},
    ]
    retriever._term_to_doc_indices = {"retrieval": {1, 2}, "agent": {1}}

    assert retriever._candidate_indices("retrieval agent") == [1, 2]


def test_vector_candidates_skip_large_corpus_without_lexical_match():
    retriever = OpenAIEmbeddingRetriever(enabled=False, api_key="", candidate_k=1)
    retriever._entries = [
        {"item": {"chunk_index": 0}, "title_tokens": set(), "tokens": {"cat"}},
        {"item": {"chunk_index": 1}, "title_tokens": set(), "tokens": {"dog"}},
    ]
    retriever._term_to_doc_indices = {"cat": {0}, "dog": {1}}

    assert retriever._candidate_indices("transformer") == []
