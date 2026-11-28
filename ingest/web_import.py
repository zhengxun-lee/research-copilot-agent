"""Single-process, atomic PDF import for the private workspace."""

import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading

from ingest.builder import build_chunks_from_pdf, save_knowledge_base
from retrievers.loader import load_knowledge_base

MAX_PDF_BYTES = 20 * 1024 * 1024
_IMPORT_LOCK = threading.Lock()


class ImportBusy(Exception):
    pass


def import_uploaded_pdf(data, filename, output_path):
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF 大小须为 1 字节至 20 MiB。")
    if not data.startswith(b"%PDF-"):
        raise ValueError("文件不是有效 PDF。")
    if not _IMPORT_LOCK.acquire(blocking=False):
        raise ImportBusy("已有文档正在入库，请稍后重试。")
    tmp = None
    try:
        output = Path(output_path)
        # A corrupt existing KB must never silently become an empty one.
        existing = load_knowledge_base(output) if output.exists() else []
        source_hash = hashlib.md5(data).hexdigest()
        duplicate = next(
            (item for item in existing if item.get("source_hash") == source_hash), None
        )
        if duplicate:
            return {
                "document": duplicate["doc_id"],
                "title": duplicate.get("title"),
                "deduplicated": True,
                "chunks": sum(
                    item.get("doc_id") == duplicate["doc_id"] for item in existing
                ),
            }
        title = Path(filename.replace("\\", "/")).stem
        title = (
            re.sub(r"[^\w\- .]", "-", title, flags=re.UNICODE).strip(" .")[:100]
            or "document"
        )
        directory = output.parent / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".pdf", dir=directory)
        tmp = Path(path)
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        from pypdf import PdfReader

        try:
            reader = PdfReader(tmp)
            if reader.is_encrypted:
                raise ValueError("请先解密 PDF，再上传。")
            if len(reader.pages) > 500:
                raise ValueError("单个 PDF 最多支持 500 页，请拆分后上传。")
            # Parse using the existing ingestion path, preserve page/chunk relationships.
            chunks = build_chunks_from_pdf(tmp)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF 解析失败，请确认文件未损坏。") from exc
        if not chunks:
            raise ValueError("PDF 中没有可提取的文字；扫描件需要先进行 OCR。")
        destination = directory / (hashlib.sha256(data).hexdigest() + ".pdf")
        doc_id = "upload-" + hashlib.sha256(data).hexdigest()[:20]
        for i, item in enumerate(chunks):
            item.update(
                doc_id=doc_id,
                title=title,
                source_path=str(destination),
                source_rel_path=filename[:200],
                chunk_id=f"{doc_id}::chunk-{i:05d}",
                prev_chunk_id=f"{doc_id}::chunk-{i-1:05d}" if i else None,
                next_chunk_id=(
                    f"{doc_id}::chunk-{i+1:05d}" if i + 1 < len(chunks) else None
                ),
            )
        os.replace(tmp, destination)
        tmp = None
        try:
            save_knowledge_base(existing + chunks, output)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return {
            "document": doc_id,
            "title": title,
            "chunks": len(chunks),
            "pages": len({item["page_number"] for item in chunks}),
            "deduplicated": False,
        }
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        _IMPORT_LOCK.release()


def delete_document(doc_id, output_path):
    """Remove indexed chunks and only the managed upload copy, under the import lock."""
    if not isinstance(doc_id, str) or not doc_id or len(doc_id) > 500:
        raise ValueError("无效的文档 ID。")
    if not _IMPORT_LOCK.acquire(blocking=False):
        raise ImportBusy("知识库正在更新，请稍后重试。")
    try:
        output = Path(output_path)
        existing = load_knowledge_base(output) if output.exists() else []
        removed = [item for item in existing if item.get("doc_id") == doc_id]
        if not removed:
            raise FileNotFoundError("文档已不存在。")
        remaining = [item for item in existing if item.get("doc_id") != doc_id]
        save_knowledge_base(remaining, output)
        from retrievers.loader import clear_knowledge_base_cache

        clear_knowledge_base_cache()
        # Never follow arbitrary source paths or delete CLI-imported originals.
        uploads = output.parent / "uploads"
        referenced = {item.get("source_path") for item in remaining}
        cleanup_pending = False
        for source in {item.get("source_path") for item in removed} - referenced:
            if not source:
                continue
            path = Path(source)
            if (path.parent.absolute() == uploads.absolute()
                    and re.fullmatch(r"[a-f0-9]{64}\.pdf", path.name)
                    and not uploads.is_symlink()):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    cleanup_pending = True
        return {"document": doc_id, "deleted_chunks": len(removed),
                "file_cleanup_pending": cleanup_pending}
    finally:
        _IMPORT_LOCK.release()
