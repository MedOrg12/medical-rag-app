from __future__ import annotations

import hashlib
import re

from medical_rag.types import Chunk, PageText

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


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
    for page in pages:
        page_chunks = split_text(page.text, chunk_size_chars, chunk_overlap_chars)
        for index, text in enumerate(page_chunks, start=1):
            chunk_id = _chunk_id(page, index, text)
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    metadata={
                        "source_id": page.source_id,
                        "source_path": page.source_path,
                        "title": page.title,
                        "page": page.page_number,
                        "chunk_index": index,
                    },
                )
            )
    return chunks


def split_text(text: str, chunk_size_chars: int, chunk_overlap_chars: int) -> list[str]:
    paragraphs = _paragraphs(text)
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size_chars:
            if current:
                chunks.append(current.strip())
                current = _tail(current, chunk_overlap_chars)
            for piece in _split_long_paragraph(paragraph, chunk_size_chars, chunk_overlap_chars):
                chunks.append(piece)
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size_chars:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
        current = f"{_tail(current, chunk_overlap_chars)} {paragraph}".strip()
        if len(current) > chunk_size_chars:
            chunks.extend(_split_long_paragraph(current, chunk_size_chars, chunk_overlap_chars))
            current = ""

    if current:
        chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk.strip()]


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paragraphs = _BLANK_LINES_RE.split(normalized)
    paragraphs = []
    for paragraph in raw_paragraphs:
        cleaned = _WHITESPACE_RE.sub(" ", paragraph.replace("\n", " ")).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def _split_long_paragraph(
    paragraph: str, chunk_size_chars: int, chunk_overlap_chars: int
) -> list[str]:
    pieces: list[str] = []
    start = 0
    text_length = len(paragraph)

    while start < text_length:
        end = min(start + chunk_size_chars, text_length)
        if end < text_length:
            boundary = paragraph.rfind(" ", start, end)
            if boundary > start + int(chunk_size_chars * 0.6):
                end = boundary

        piece = paragraph[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= text_length:
            break
        start = max(end - chunk_overlap_chars, start + 1)

    return pieces


def _tail(text: str, size: int) -> str:
    if not text or size <= 0:
        return ""
    tail = text[-size:]
    first_space = tail.find(" ")
    if first_space > 0:
        return tail[first_space + 1 :].strip()
    return tail.strip()


def _chunk_id(page: PageText, chunk_index: int, text: str) -> str:
    raw = f"{page.source_path}:{page.page_number}:{chunk_index}:{text[:120]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
