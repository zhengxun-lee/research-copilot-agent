import io
import json
from http.client import HTTPConnection
from urllib.parse import urlparse

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

import web_app
from ingest.web_import import import_uploaded_pdf
from test_web_app import http_server, _get
from retrievers.loader import load_knowledge_base


def pdf_bytes(text="Research evidence on attention and retrieval."):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 30 700 Td (" + text + ") Tj ET").encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_real_pdf_import_preserves_pages_and_deduplicates(tmp_path):
    path = tmp_path / "kb.json"
    result = import_uploaded_pdf(pdf_bytes(), "../../paper.pdf", path)
    items = load_knowledge_base(path)
    assert result["pages"] == 1 and result["chunks"] > 0
    assert items[0]["page_number"] == 1
    assert "attention" in items[0]["content"]
    assert (tmp_path / "uploads") in __import__("pathlib").Path(
        items[0]["source_path"]
    ).parents
    assert import_uploaded_pdf(pdf_bytes(), "renamed.pdf", path)["deduplicated"]
    assert len(load_knowledge_base(path)) == len(items)


def test_bad_pdf_and_blank_scan_preserve_existing_kb(tmp_path):
    path = tmp_path / "kb.json"
    import_uploaded_pdf(pdf_bytes(), "paper.pdf", path)
    before = path.read_bytes()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    blank = io.BytesIO()
    writer.write(blank)
    for data in [b"not PDF", b"%PDF-corrupt", blank.getvalue()]:
        with pytest.raises(ValueError):
            import_uploaded_pdf(data, "bad.pdf", path)
    assert path.read_bytes() == before
    assert len(list((tmp_path / "uploads").glob("*.pdf"))) == 1


def test_http_upload_then_document_preview(http_server, monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "KNOWLEDGE_BASE_PATH", tmp_path / "kb.json")
    from retrievers import loader

    monkeypatch.setattr(loader, "KNOWLEDGE_BASE_PATH", tmp_path / "kb.json")
    url = urlparse(http_server)
    conn = HTTPConnection(url.hostname, url.port, timeout=5)
    conn.request(
        "POST",
        "/api/kb/import?filename=paper.pdf",
        body=pdf_bytes(),
        headers={"Content-Type": "application/pdf"},
    )
    response = conn.getresponse()
    result = json.loads(response.read())
    assert response.status == 201
    _, preview = _get(http_server, "/api/kb/document/" + result["document"])
    assert preview["exists"] and preview["chunks"][0]["page_number"] == 1
    conn.close()


def test_http_rejects_cross_origin_and_oversized_upload(http_server):
    url = urlparse(http_server)
    for headers, expected in [
        ({"Content-Type": "application/pdf", "Origin": "http://evil.invalid"}, 403),
        (
            {
                "Content-Type": "application/pdf",
                "Content-Length": str(21 * 1024 * 1024),
            },
            413,
        ),
        ({"Content-Type": "text/plain"}, 415),
    ]:
        conn = HTTPConnection(url.hostname, url.port, timeout=5)
        conn.request("POST", "/api/kb/import", body=b"", headers=headers)
        response = conn.getresponse()
        response.read()
        assert response.status == expected
        conn.close()


def test_delete_document_removes_upload_and_refreshes_index(tmp_path):
    from pathlib import Path
    from ingest.web_import import delete_document

    path = tmp_path / "kb.json"
    first = import_uploaded_pdf(pdf_bytes("First paper unique evidence."), "first.pdf", path)
    second = import_uploaded_pdf(pdf_bytes("Second paper remains."), "second.pdf", path)
    source = Path(load_knowledge_base(path)[0]["source_path"])
    result = delete_document(first["document"], path)
    assert result["deleted_chunks"] > 0
    assert not source.exists()
    assert {item["doc_id"] for item in load_knowledge_base(path)} == {second["document"]}
    with pytest.raises(FileNotFoundError):
        delete_document(first["document"], path)
    delete_document(second["document"], path)
    assert load_knowledge_base(path) == []
    assert not import_uploaded_pdf(pdf_bytes("First paper unique evidence."), "again.pdf", path)["deduplicated"]


def test_delete_document_preserves_external_sources_and_failed_write(tmp_path, monkeypatch):
    import ingest.web_import as module
    from ingest.builder import save_knowledge_base

    original = tmp_path / "original.pdf"
    original.write_bytes(b"original")
    path = tmp_path / "kb.json"
    save_knowledge_base([{"doc_id": "legacy", "source_path": str(original)}], path)
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError("disk full")
        patch.setattr(module, "save_knowledge_base", fail)
        with pytest.raises(OSError):
            module.delete_document("legacy", path)
    assert path.read_bytes() == before and original.exists()
    module.delete_document("legacy", path)
    assert original.exists()


def test_http_delete_updates_browse_and_rejects_cross_origin(http_server, tmp_path, monkeypatch):
    path = tmp_path / "kb.json"
    monkeypatch.setattr(web_app, "KNOWLEDGE_BASE_PATH", str(path))
    result = import_uploaded_pdf(pdf_bytes(), "paper.pdf", path)
    url = urlparse(http_server)
    for origin, expected in [("http://evil.invalid", 403), (http_server, 200), (http_server, 404)]:
        conn = HTTPConnection(url.hostname, url.port, timeout=5)
        conn.request("POST", "/api/kb/delete", body=json.dumps({"doc_id": result["document"]}),
                     headers={"Content-Type": "application/json", "Origin": origin})
        response = conn.getresponse()
        response.read()
        assert response.status == expected
        conn.close()
    assert load_knowledge_base(path) == []
