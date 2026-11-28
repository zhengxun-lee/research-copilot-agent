from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

from config import KNOWLEDGE_BASE_PATH
from ingest.chunker import chunk_page_text
from ingest.cleaner import clean_text
from ingest.pdf_parser import extract_pdf_pages
from ingest.schema import Chunk
from retrievers.loader import clear_knowledge_base_cache, load_knowledge_base as _load_kb

logger = logging.getLogger(__name__)


def _hash_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_doc_id(pdf_path: Path, source_hash: str) -> str:
    stem = "".join(ch if ch.isalnum() else "-" for ch in pdf_path.stem.lower()).strip("-")
    return f"{stem}-{source_hash[:10]}" if stem else f"doc-{source_hash[:10]}"


def make_chunk_id(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}::chunk-{chunk_index:05d}"


def build_chunks_from_pdf(
    pdf_path: Union[str, Path],
    root_dir: Optional[Union[str, Path]] = None,
    max_chars: int = 500,
    overlap_chars: int = 80,
) -> list[dict]:
    path = Path(pdf_path)
    root = Path(root_dir) if root_dir else path.parent
    source_hash = _hash_file(path)
    doc_id = make_doc_id(path, source_hash)
    title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    try:
        source_rel_path = str(path.relative_to(root))
    except ValueError:
        source_rel_path = path.name

    chunks: list[Chunk] = []
    chunk_index = 0
    for page_number, raw_text in extract_pdf_pages(path):
        text = clean_text(raw_text)
        for chunk_text in chunk_page_text(text, max_chars=max_chars, overlap_chars=overlap_chars):
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    title=title,
                    content=chunk_text,
                    source_path=str(path),
                    source_rel_path=source_rel_path,
                    source_hash=source_hash,
                    page_number=page_number,
                    chunk_id=make_chunk_id(doc_id, chunk_index),
                    chunk_index=chunk_index,
                    char_count=len(chunk_text),
                )
            )
            chunk_index += 1

    for index, chunk in enumerate(chunks):
        if index > 0:
            chunk.prev_chunk_id = chunks[index - 1].chunk_id
        if index < len(chunks) - 1:
            chunk.next_chunk_id = chunks[index + 1].chunk_id
    return [chunk.to_dict() for chunk in chunks]


def load_knowledge_base_safe(output_path: Union[str, Path] = KNOWLEDGE_BASE_PATH) -> list[dict]:
    """Return the current knowledge-base contents, or [] on missing / corrupt file."""
    try:
        return _load_kb(path=output_path)
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to load knowledge base from %s", output_path)
        return []


def save_knowledge_base(items: list[dict], output_path: Union[str, Path] = KNOWLEDGE_BASE_PATH):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file first, then atomically rename — avoids corruption on crash.
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix=".kb-", dir=path.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as file:
            json.dump(items, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure (including KeyboardInterrupt).
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    clear_knowledge_base_cache()


def remove_existing_source_items(items: list[dict], source_path: str) -> list[dict]:
    """Remove items belonging to *source_path* from *items*.

    Deduplication is path-based because two different files can share the
    same content hash (e.g. copies).  Both the original and the fully-resolved
    (absolute) forms are compared so that running imports from different working
    directories does not create duplicate chunks.
    """
    path = Path(source_path).resolve()
    path_str = str(path)
    source_paths = {path_str, str(Path(source_path))}
    kept = []
    for item in items:
        item_source = item.get("source_path")
        if item_source and str(Path(item_source).resolve()) in source_paths:
            continue
        item_rel = item.get("source_rel_path")
        if item_rel and str(Path(item_rel).resolve()) == path_str:
            continue
        kept.append(item)
    return kept


def import_single_pdf(
    pdf_path: Union[str, Path],
    output_path: Union[str, Path] = KNOWLEDGE_BASE_PATH,
    root_dir: Optional[Union[str, Path]] = None,
    max_chars: int = 500,
    overlap_chars: int = 80,
) -> list[dict]:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    # Build new chunks BEFORE removing old ones — if building fails, old data is preserved.
    new_items = build_chunks_from_pdf(
        path,
        root_dir=root_dir,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    existing_items = load_knowledge_base_safe(output_path)
    existing_items = remove_existing_source_items(existing_items, str(path))
    all_items = existing_items + new_items
    save_knowledge_base(all_items, output_path)
    return all_items


def import_pdf_folder(
    pdf_dir: Union[str, Path] = "data/pdfs",
    output_path: Union[str, Path] = KNOWLEDGE_BASE_PATH,
    max_chars: int = 500,
    overlap_chars: int = 80,
    progress: bool = True,
) -> list[dict]:
    root = Path(pdf_dir)
    if not root.exists():
        raise FileNotFoundError(f"PDF directory not found: {root}")
    existing_items = load_knowledge_base_safe(output_path)
    # Resolve before sorting so symlinks / case-only differences in the
    # underlying filesystem don't cause the same PDF to be ingested twice.
    pdf_paths = sorted({path.resolve() for path in root.rglob("*.pdf")})
    # Normalise to resolved (absolute) paths so dedup works regardless of CWD.
    source_paths = {str(path.resolve()) for path in pdf_paths}
    source_rel_paths = {str(path.relative_to(root)) for path in pdf_paths}

    def _should_preserve(item: dict) -> bool:
        # Drop items that will be re-imported from current PDFs.
        item_source = item.get("source_path")
        if item_source:
            item_path = Path(item_source)
            # Resolve the item's stored path to an absolute path for comparison.
            # If the item was imported from a different working directory, its
            # stored path may be relative — try resolving both against the
            # current CWD and against the PDF root directory.
            candidates = {str(item_path.resolve())}
            if not item_path.is_absolute():
                candidates.add(str((root / item_source).resolve()))
            if candidates & source_paths:
                return False
        if item.get("source_rel_path") in source_rel_paths:
            return False
        # Drop stale items whose source file has been deleted.
        if item_source:
            item_path = Path(item_source)
            exists = item_path.exists()
            if not exists and not item_path.is_absolute():
                # The stored path may be relative — try resolving against the
                # PDF root directory in case the import ran from a different CWD.
                exists = (root / item_source).exists()
            if not exists:
                logger.info("Removing stale chunks from deleted file: %s", item_source)
                return False
        return True

    preserved_items = [item for item in existing_items if _should_preserve(item)]
    if progress:
        rel = f" ({len(preserved_items)} 个保留)" if preserved_items else ""
        print(f"[ingest] 发现 {len(pdf_paths)} 个 PDF{rel}，开始处理 ...")

    new_items = []
    failures = []
    for index, pdf_path in enumerate(pdf_paths, start=1):
        rel_path = pdf_path.relative_to(root)
        if progress:
            print(f"[ingest] [{index}/{len(pdf_paths)}] {rel_path}", end="", flush=True)
        try:
            chunks = build_chunks_from_pdf(
                pdf_path,
                root_dir=root,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        except Exception as exc:
            failures.append((str(rel_path), str(exc)))
            if progress:
                print(f"  ✗ 失败: {exc}")
            logger.exception("Failed to process PDF: %s", pdf_path)
            continue
        new_items.extend(chunks)
        if progress:
            print(f"  ✓ {len(chunks)} 个片段")

    all_items = preserved_items + new_items
    save_knowledge_base(all_items, output_path)

    if progress:
        print(
            f"[ingest] 完成：{len(new_items)} 个新片段 + {len(preserved_items)} 个保留 → {output_path}"
        )
        if failures:
            print(f"[ingest] {len(failures)} 个文件处理失败：")
            for path, reason in failures:
                print(f"  - {path}: {reason}")
    return all_items


def main():
    parser = argparse.ArgumentParser(description="Build local knowledge base from PDFs.")
    parser.add_argument("--pdf-dir", default="data/pdfs")
    parser.add_argument("--output", default=KNOWLEDGE_BASE_PATH)
    parser.add_argument("--max-chars", type=int, default=500)
    parser.add_argument("--overlap-chars", type=int, default=80)
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()
    try:
        items = import_pdf_folder(
            pdf_dir=args.pdf_dir,
            output_path=args.output,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            progress=not args.quiet,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
    if args.quiet:
        print(f"Saved {len(items)} chunks to {args.output}")


if __name__ == "__main__":
    main()
