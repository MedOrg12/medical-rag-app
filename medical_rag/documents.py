from __future__ import annotations

from pathlib import Path

from medical_rag.types import PageText

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


def iter_source_files(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source path does not exist: {path}")

    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported source file type: {path.suffix}")
        return [path]

    files = [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda item: str(item).lower())


def load_documents(path: Path) -> list[PageText]:
    pages: list[PageText] = []
    for source_file in iter_source_files(path):
        file_pages, _ = load_source_file(source_file)
        pages.extend(file_pages)
    return pages


def load_source_file(path: Path, ocr_scanned: bool = False) -> tuple[list[PageText], int]:
    if path.suffix.lower() == ".pdf":
        return _load_pdf(path, ocr_scanned=ocr_scanned)
    return _load_text_file(path), 0


def _load_pdf(path: Path, ocr_scanned: bool = False) -> tuple[list[PageText], int]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires PyMuPDF. Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    pages: list[PageText] = []
    scanned_pages = 0
    with fitz.open(path) as document:
        title = (document.metadata or {}).get("title") or path.stem
        for page_index, page in enumerate(document, start=1):
            text = _extract_page_text(page).strip()
            if not text:
                scanned_pages += 1
                if ocr_scanned:
                    # OCR is intentionally opt-in and requires a future backend.
                    # For now we mark scanned pages so ingestion can continue quickly.
                    pass
                continue
            pages.append(
                PageText(
                    source_id=_source_id(path),
                    source_path=str(path),
                    title=title,
                    page_number=page_index,
                    text=text,
                )
            )
    return pages, scanned_pages


def _load_text_file(path: Path) -> list[PageText]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []

    return [
        PageText(
            source_id=_source_id(path),
            source_path=str(path),
            title=path.stem,
            page_number=1,
            text=text,
        )
    ]


def _source_id(path: Path) -> str:
    return path.name


def _extract_page_text(page) -> str:
    try:
        return page.get_text("text", sort=True)
    except TypeError:
        return page.get_text("text")
