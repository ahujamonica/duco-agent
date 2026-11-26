"""PDF text extraction tool."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def extract_pdf_text(path: str | Path) -> tuple[str, int]:
    """Return ``(text, page_count)`` for a text-based PDF."""
    document = pymupdf.open(str(path))
    pages = [page.get_text("text") for page in document]
    document.close()
    return "\n".join(pages).strip(), len(pages)
