from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import re

from medical_rag.types import Chunk, PageText

_WHITESPACE_RE = re.compile(r"[ \t]+")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+[A-Z][A-Za-z0-9, /&-]{2,}$")
_LEADING_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+")
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,4}$", re.IGNORECASE)
_DOI_RE = re.compile(r"\bdoi:\s*10\.", re.IGNORECASE)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

_COMMON_SECTION_HEADINGS = {
    "abstract",
    "background",
    "background and purpose",
    "introduction",
    "methods",
    "method",
    "materials and methods",
    "patients and methods",
    "statistical analysis",
    "results",
    "findings",
    "discussion",
    "interpretation",
    "conclusion",
    "conclusions",
    "recommendation",
    "recommendations",
    "summary",
    "key points",
    "clinical implications",
    "diagnosis",
    "treatment",
    "management",
    "rehabilitation",
    "prevention",
    "secondary prevention",
    "limitations",
}

_REFERENCE_HEADINGS = {"references", "bibliography", "reference"}
_NOISE_LINE_PREFIXES = (
    "copyright",
    "downloaded from",
    "published by",
    "all rights reserved",
    "supplemental material",
)


@dataclass
class _SectionSegment:
    page: PageText
    section: str | None
    page_start: int | None
    page_end: int | None
    lines: list[str]

    @property
    def text(self) -> str:
        return _lines_to_text(self.lines)


def chunk_pages(
    pages: list[PageText],
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[Chunk]:
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be greater than zero")
    if chunk_overlap_chars < 0:
        raise ValueError("chunk_overlap_chars cannot be negative")
    if chunk_overlap_chars >= chunk_size_chars:
        raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")

    chunks: list[Chunk] = []
    chunk_counter_by_source: dict[str, int] = {}

    for source_pages in _group_pages_by_source(pages):
        for segment in _segment_source_pages(source_pages):
            if not segment.text:
                continue

            section_prefix = f"Section: {segment.section}\n\n" if segment.section else ""
            body_limit = max(240, chunk_size_chars - len(section_prefix))
            segment_chunks = _chunk_text(
                segment.text,
                chunk_size_chars=body_limit,
                chunk_overlap_chars=chunk_overlap_chars,
            )

            for text in segment_chunks:
                source_index = chunk_counter_by_source.get(segment.page.source_id, 0) + 1
                chunk_counter_by_source[segment.page.source_id] = source_index
                chunk_text = f"{section_prefix}{text}" if section_prefix else text
                chunk_id = _chunk_id(segment, source_index, chunk_text)
                page_start = segment.page_start
                page_end = segment.page_end
                page_value = page_start if page_start == page_end else page_start

                metadata = {
                    "source_id": segment.page.source_id,
                    "source_path": segment.page.source_path,
                    "title": segment.page.title,
                    "page": page_value,
                    "page_start": page_start,
                    "page_end": page_end,
                    "section": segment.section,
                    "chunk_index": source_index,
                    "chunking_strategy": "section_sentence_window_v1",
                }

                if page_start != page_end:
                    metadata["page_range"] = f"{page_start}-{page_end}"

                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=chunk_text,
                        metadata=metadata,
                    )
                )
    return chunks


def split_text(text: str, chunk_size_chars: int, chunk_overlap_chars: int) -> list[str]:
    return _chunk_text(
        _lines_to_text(_clean_lines(text)),
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )


def _group_pages_by_source(pages: list[PageText]) -> list[list[PageText]]:
    grouped: OrderedDict[str, list[PageText]] = OrderedDict()
    for page in pages:
        grouped.setdefault(page.source_id, []).append(page)
    return list(grouped.values())


def _segment_source_pages(pages: list[PageText]) -> list[_SectionSegment]:
    if not pages:
        return []

    segments: list[_SectionSegment] = []
    current_section: str | None = None
    current_lines: list[str] = []
    current_start_page: int | None = None
    current_end_page: int | None = None
    first_page = pages[0]
    stop_at_references = False

    def flush() -> None:
        nonlocal current_lines, current_start_page, current_end_page
        if not current_lines:
            return
        segments.append(
            _SectionSegment(
                page=first_page,
                section=current_section,
                page_start=current_start_page,
                page_end=current_end_page,
                lines=current_lines,
            )
        )
        current_lines = []
        current_start_page = None
        current_end_page = None

    for page in pages:
        if stop_at_references:
            break

        for line in _clean_lines(page.text):
            if _is_reference_heading(line):
                flush()
                stop_at_references = True
                break

            heading = _detect_heading(line)
            if heading:
                flush()
                current_section = heading
                continue

            current_lines.append(line)
            if current_start_page is None:
                current_start_page = page.page_number
            current_end_page = page.page_number

    flush()
    return segments


def _chunk_text(text: str, chunk_size_chars: int, chunk_overlap_chars: int) -> list[str]:
    if not text:
        return []

    sentences = _sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = []

    for sentence in sentences:
        if len(sentence) > chunk_size_chars:
            if current_sentences:
                chunks.append(_join_sentences(current_sentences))
                current_sentences = _tail_sentences(current_sentences, chunk_overlap_chars)
            chunks.extend(_split_long_text(sentence, chunk_size_chars, chunk_overlap_chars))
            continue

        candidate = _join_sentences([*current_sentences, sentence])
        if len(candidate) <= chunk_size_chars:
            current_sentences.append(sentence)
            continue

        if current_sentences:
            chunks.append(_join_sentences(current_sentences))
        current_sentences = _tail_sentences(current_sentences, chunk_overlap_chars)

        while current_sentences and len(_join_sentences([*current_sentences, sentence])) > chunk_size_chars:
            current_sentences = current_sentences[1:]
        current_sentences.append(sentence)

    if current_sentences:
        chunks.append(_join_sentences(current_sentences))

    return [chunk for chunk in chunks if chunk.strip()]


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if _is_noise_line(line):
            continue
        lines.append(line)
    return _merge_hyphenated_lines(lines)


def _merge_hyphenated_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if merged and merged[-1].endswith("-") and line and line[0].islower():
            merged[-1] = merged[-1][:-1] + line
        else:
            merged.append(line)
    return merged


def _lines_to_text(lines: list[str]) -> str:
    text = " ".join(lines)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    parts = _SENTENCE_BOUNDARY_RE.split(normalized)
    sentences = []
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def _detect_heading(line: str) -> str | None:
    candidate = line.strip().strip(":")
    lowered = candidate.lower()
    word_count = len(candidate.split())

    if len(candidate) < 3 or len(candidate) > 110 or word_count > 12:
        return None
    if candidate.endswith(".") and lowered not in _COMMON_SECTION_HEADINGS:
        return None
    if lowered in _COMMON_SECTION_HEADINGS:
        return _normalize_heading(candidate)
    if _NUMBERED_HEADING_RE.match(candidate):
        return _normalize_heading(candidate)
    if candidate.isupper() and 1 <= word_count <= 10:
        return _normalize_heading(candidate)
    if line.endswith(":") and word_count <= 10:
        return _normalize_heading(candidate)

    title_words = sum(1 for word in candidate.split() if word[:1].isupper())
    if word_count >= 2 and title_words / word_count >= 0.75 and not any(
        char in candidate for char in ".;()"
    ):
        return _normalize_heading(candidate)

    return None


def _normalize_heading(heading: str) -> str:
    cleaned = _LEADING_NUMBER_RE.sub("", heading).strip(" :-")
    if cleaned.isupper():
        return cleaned.title()
    return cleaned[:1].upper() + cleaned[1:]


def _is_reference_heading(line: str) -> bool:
    cleaned = line.strip().strip(":").lower()
    return cleaned in _REFERENCE_HEADINGS


def _is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if _PAGE_NUMBER_RE.match(line):
        return True
    if _DOI_RE.search(line) or _URL_RE.search(line):
        return True
    return lowered.startswith(_NOISE_LINE_PREFIXES)


def _join_sentences(sentences: list[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip()).strip()


def _tail_sentences(sentences: list[str], max_chars: int) -> list[str]:
    if max_chars <= 0:
        return []

    selected: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        next_total = total + len(sentence) + (1 if selected else 0)
        if next_total > max_chars:
            break
        selected.append(sentence)
        total = next_total
    return list(reversed(selected))


def _split_long_text(
    text: str, chunk_size_chars: int, chunk_overlap_chars: int
) -> list[str]:
    pieces: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size_chars, text_length)
        if end < text_length:
            boundary = text.rfind(" ", start, end)
            if boundary > start + int(chunk_size_chars * 0.6):
                end = boundary

        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= text_length:
            break
        start = max(end - chunk_overlap_chars, start + 1)

    return pieces


def _chunk_id(segment: _SectionSegment, chunk_index: int, text: str) -> str:
    raw = (
        f"{segment.page.source_path}:{segment.page_start}:{segment.page_end}:"
        f"{segment.section}:{chunk_index}:{text[:120]}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
