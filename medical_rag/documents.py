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
        if source_file.suffix.lower() == ".pdf":
            pages.extend(_load_pdf(source_file))
        else:
            pages.extend(_load_text_file(source_file))
    return pages


def _load_pdf(path: Path) -> list[PageText]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires PyMuPDF. Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    pages: list[PageText] = []
    with fitz.open(path) as document:
        title = (document.metadata or {}).get("title") or path.stem
        for page_index, page in enumerate(document, start=1):
            text = _extract_page_text(page).strip()
            if not text:
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
    return pages


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
