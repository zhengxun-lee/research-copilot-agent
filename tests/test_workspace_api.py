import json

import pytest

from retrievers import loader
from test_web_app import http_server, _get, _post_json


def install_corpus(tmp_path, monkeypatch, count=3):
    path = tmp_path / 'workspace-kb.json'
    items = [{'doc_id': 'unit-doc', 'title': 'Unit document', 'content': f'Attention retrieval evidence unique passage {i}',
              'chunk_id': f'c{i}', 'chunk_index': i, 'page_number': i,
              'prev_chunk_id': f'c{i-1}' if i else None,
              'next_chunk_id': f'c{i+1}' if i < count-1 else None,
              'source_path': '/private/not-for-playground.pdf'} for i in range(count)]
    path.write_text(json.dumps(items))
    monkeypatch.setattr(loader, 'KNOWLEDGE_BASE_PATH', str(path))
    loader.clear_knowledge_base_cache()
    return items


def test_public_configuration_never_exposes_credentials(http_server, monkeypatch):
    import api_config
    monkeypatch.setattr(api_config, 'SIMPLE_MODEL_API_KEY', 'unit-secret-never-render')
    code, body = _get(http_server, '/api/config/public')
    assert code == 200
    assert body['api_configured'] is True
    assert 'unit-secret-never-render' not in json.dumps(body)
    assert 'base_url' not in json.dumps(body)
    assert body['capabilities']['token_streaming'] is True


def test_playground_uses_real_keyword_index_and_limits_metadata(http_server, tmp_path, monkeypatch):
    install_corpus(tmp_path, monkeypatch)
    code, body = _post_json(http_server, '/api/retrieval/search', {'query': 'Attention', 'mode': 'keyword', 'top_k': 2})
    assert code == 200
    assert len(body['results']) > 0
    assert body['results'][0]['score'] > 0
    assert 'Attention' in body['results'][0]['item']['content']
    assert '/private/not-for-playground.pdf' not in json.dumps(body)
    assert body['duration_ms'] >= 0


def test_document_pagination_and_zero_page_are_preserved(http_server, tmp_path, monkeypatch):
    install_corpus(tmp_path, monkeypatch, count=55)
    _, first = _get(http_server, '/api/kb/document/unit-doc')
    assert first['chunks'][0]['page_number'] == 0
    assert len(first['chunks']) == 50
    _, second = _get(http_server, '/api/kb/document/unit-doc?offset=50')
    assert second['offset'] == 50
    assert len(second['chunks']) == 5
    assert second['chunks'][0]['prev_chunk_id'] == 'c49'


@pytest.mark.parametrize('body', [
    {'query': ''}, {'query': 'x', 'mode': 'invalid'}, {'query': 'x', 'top_k': True},
    {'query': 'x', 'top_k': 20}, {'query': 'x'*2001}, {'query': ['x']}
])
def test_playground_rejects_invalid_requests(http_server, body):
    assert _post_json(http_server, '/api/retrieval/search', body)[0] == 400
