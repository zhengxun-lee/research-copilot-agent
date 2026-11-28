from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Union

_LAYOUT_LOGGER_NAME = "pypdf._text_extraction._layout_mode._fixed_width_page"

logger = logging.getLogger(__name__)


def _load_pdf_reader():
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised only without dependency
        raise RuntimeError(
            "pypdf is required to parse PDF files. Run `make install` or "
            "`python3 -m pip install -r requirements.txt`."
        ) from exc
    return PdfReader


def _extract_page_text(page: Any) -> str:
    if _page_rotation(page):
        return _extract_plain_text(page)
    try:
        with _suppress_layout_warnings():
            return page.extract_text(extraction_mode="layout") or ""
    except TypeError:
        logger.debug("Layout extraction not supported by this pypdf version; falling back to plain text.")
        return _extract_plain_text(page)
    except Exception:
        logger.debug("Layout extraction failed; falling back to plain text.", exc_info=True)
        return _extract_plain_text(page)


def _extract_plain_text(page: Any) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        logger.debug("Plain text extraction failed; returning empty string.", exc_info=True)
        return ""


def _page_rotation(page: Any) -> int:
    rotation = getattr(page, "rotation", 0)
    try:
        return int(rotation or 0) % 360
    except (TypeError, ValueError):
        return 0


@contextmanager
def _suppress_layout_warnings():
    logger = logging.getLogger(_LAYOUT_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous_level)


def extract_pdf_pages(pdf_path: Union[str, Path]) -> list[tuple[int, str]]:
    PdfReader = _load_pdf_reader()
    path = Path(pdf_path)
    try:
        try:
            reader = PdfReader(str(path), strict=False)
        except TypeError:
            reader = PdfReader(str(path))
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF: {path}") from exc
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Cannot decrypt encrypted PDF: {path}") from exc
    return [(index + 1, _extract_page_text(page)) for index, page in enumerate(reader.pages)]


