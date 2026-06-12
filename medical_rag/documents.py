from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from medical_rag.types import PageText

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}

_NOISE_PREFIXES = (
    "copyright",
    "downloaded from",
    "published by",
    "all rights reserved",
    "supplemental material",
)
_PAGE_NUM_RE = re.compile(r"^(?:page\s*)?\d{1,4}$", re.IGNORECASE)
_DOI_RE = re.compile(r"\bdoi:\s*10\.", re.IGNORECASE)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_REFERENCE_HEADINGS = {"references", "bibliography", "reference"}


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
    with fitz.open(path) as doc:
        title = (doc.metadata or {}).get("title") or path.stem
        repeated = _find_repeated_blocks(doc)
        stop = False

        for page_index, page in enumerate(doc, start=1):
            if stop:
                break
            try:
                text, layout_hints, stop = _extract_blocks(page, repeated, stop)
            except Exception:
                text = _fallback_page_text(page)
                layout_hints = None

            text = text.strip()
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
                    layout_hints=layout_hints,
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


def _fallback_page_text(page) -> str:
    try:
        return page.get_text("text", sort=True)
    except TypeError:
        return page.get_text("text")


# ---------------------------------------------------------------------------
# Block-level extraction helpers
# ---------------------------------------------------------------------------

def _find_repeated_blocks(doc) -> set[str]:
    """Return normalised text of blocks that appear on ≥15% of pages (min 3)."""
    n_pages = len(doc)
    min_count = max(3, int(n_pages * 0.15))
    counter: Counter[str] = Counter()

    for page in doc:
        seen: set[str] = set()
        try:
            blocks = page.get_text("dict").get("blocks", [])
        except Exception:
            continue
        for block in blocks:
            if block.get("type") != 0:
                continue
            raw = _block_text(block).strip()
            if not raw or len(raw) >= 120:
                continue
            norm = re.sub(r"\s+", " ", raw).lower()
            if norm not in seen:
                counter[norm] += 1
                seen.add(norm)

    return {text for text, count in counter.items() if count >= min_count}


def _detect_columns(blocks: list[dict], page_width: float) -> int:
    """Return 1 or 2: if >30% of text blocks start right of 45% page width → two-column."""
    if not blocks or page_width <= 0:
        return 1
    threshold = page_width * 0.45
    right = sum(1 for b in blocks if b["bbox"][0] > threshold)
    return 2 if right / len(blocks) > 0.30 else 1


def _order_two_column(blocks: list[dict], page_width: float) -> list[dict]:
    """Sort two-column blocks left-column first, then right-column, each by y-position."""
    threshold = page_width * 0.45
    left = sorted([b for b in blocks if b["bbox"][0] <= threshold], key=lambda b: b["bbox"][1])
    right = sorted([b for b in blocks if b["bbox"][0] > threshold], key=lambda b: b["bbox"][1])
    return left + right


def _block_text(block: dict) -> str:
    """Concatenate all span text in a block into a single string."""
    parts = []
    for line in block.get("lines", []):
        line_parts = [span["text"] for span in line.get("spans", []) if span["text"].strip()]
        if line_parts:
            parts.append("".join(line_parts))
    return " ".join(parts)


def _is_noise_block(text: str) -> bool:
    """True for page numbers, DOIs, URLs, and copyright boilerplate."""
    if _PAGE_NUM_RE.match(text):
        return True
    if _DOI_RE.search(text):
        return True
    if _URL_RE.search(text):
        return True
    return text.lower().startswith(_NOISE_PREFIXES)


def _looks_like_table_row(block: dict) -> bool:
    """Heuristic: ≥3 spans at ≥3 distinct x-positions, ≥70% shorter than 40 chars."""
    spans = [
        span
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["text"].strip()
    ]
    if len(spans) < 3:
        return False
    x_buckets = {round(span["bbox"][0] / 10) for span in spans}
    if len(x_buckets) < 3:
        return False
    short = sum(1 for s in spans if len(s["text"].strip()) < 40)
    return short / len(spans) >= 0.70


def _table_block_to_lines(block: dict) -> list[str]:
    """Convert a table-like block into a single `Cell1 | Cell2 | ...` line."""
    cells = [
        span["text"].strip()
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["text"].strip()
    ]
    return [" | ".join(cells)] if cells else []


def _extract_blocks(
    page, repeated: set[str], stop: bool
) -> tuple[str, dict[str, Any], bool]:
    """Extract clean text from one page using block coordinates."""
    data = page.get_text("dict")
    blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]
    page_width = page.rect.width

    n_cols = _detect_columns(blocks, page_width)
    if n_cols == 2:
        blocks = _order_two_column(blocks, page_width)
    else:
        blocks = sorted(blocks, key=lambda b: b["bbox"][1])

    lines: list[str] = []
    has_table = False

    for block in blocks:
        raw = _block_text(block).strip()
        if not raw:
            continue

        norm = re.sub(r"\s+", " ", raw).lower()

        if norm in repeated:
            continue

        stripped = norm.strip().strip(":")
        if stripped in _REFERENCE_HEADINGS:
            stop = True
            break

        if _is_noise_block(raw):
            continue

        if _looks_like_table_row(block):
            has_table = True
            lines.extend(_table_block_to_lines(block))
        else:
            lines.append(raw)

    text = "\n".join(lines)
    layout_hints: dict[str, Any] = {"columns": n_cols, "has_table": has_table}
    return text, layout_hints, stop
