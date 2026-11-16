"""Evidence presentation and citation-ID checks, not clinical claim verification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from medical_rag.curation import SourceCatalog  # noqa: F401 - public compatibility import
from medical_rag.types import Chunk, Citation, SearchResult

_CITATION_GROUP = re.compile(r"\[([0-9]+(?:\s*-\s*[0-9]+)?(?:\s*[,;]\s*[0-9]+(?:\s*-\s*[0-9]+)?)*)\]")


def citation_ids(answer: str) -> set[int]:
    ids = set()
    for match in _CITATION_GROUP.finditer(answer):
        for group in re.split(r"\s*[,;]\s*", match[1]):
            bounds = group.split("-")
            start = int(bounds[0])
            end = int(bounds[-1])
            # Bound work on malformed/model-generated ranges.
            if end >= start and end - start <= 100:
                ids.update(range(start, end + 1))
            else:
                ids.update((start, end))
    return ids


def partition_evidence(answer: str, evidence: list[Citation]) -> tuple[list[Citation], list[Citation], dict[str, Any]]:
    mentioned = citation_ids(answer)
    available = {item.id for item in evidence}
    invalid = sorted(mentioned - available)
    used = [item for item in evidence if item.id in mentioned]
    unused = [item for item in evidence if item.id not in mentioned]
    warnings = []
    if invalid:
        warnings.append("The answer refers to unavailable source numbers: " + ", ".join(map(str, invalid)) + ".")
    if evidence and not used:
        warnings.append("The answer does not cite any of the retrieved passages. Its claims need review.")
    return used, unused, {
        "status": "needs_review" if warnings else "ids_valid" if used else "no_citations",
        "invalid_ids": invalid,
        "warnings": warnings,
        "claim_support_verified": False,
    }


def document_path(chunk: Chunk, corpus_dir: Path) -> Path | None:
    """Only indexed PDFs inside the configured corpus can be served; never accept a URL path."""
    source_path = chunk.metadata.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        return None
    try:
        root = corpus_dir.expanduser().resolve()
        path = Path(source_path).expanduser().resolve()
        if (path != root and not path.is_relative_to(root)) or path.suffix.lower() != ".pdf":
            return None
        if not path.is_file():
            return None
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def make_citation(result: SearchResult, citation_id: int, corpus_dir: Path) -> Citation:
    metadata = result.chunk.metadata
    page = metadata.get("page_start", metadata.get("page"))
    page = page if type(page) is int and page > 0 else None
    page_end = metadata.get("page_end", page)
    page_end = page_end if type(page_end) is int and page_end >= (page or 1) else page
    year = metadata.get("publication_year")
    year = year if type(year) is int and 1000 <= year <= 9999 else None
    url = None
    if document_path(result.chunk, corpus_dir):
        url = f"/evidence/{quote(result.chunk.id, safe='')}/document"
        if page:
            url += f"#page={page}"
    cleaned = " ".join(result.chunk.text.split())
    excerpt = cleaned if len(cleaned) <= 320 else cleaned[:319].rsplit(" ", 1)[0] + "..."
    return Citation(
        id=citation_id,
        source=str(metadata.get("source_id", "unknown")),
        page=page,
        chunk_id=result.chunk.id,
        score=round(result.score, 6),
        excerpt=excerpt,
        title=str(metadata["title"]) if metadata.get("title") else None,
        publisher=str(metadata["publisher"]) if metadata.get("publisher") else None,
        publication_year=year,
        section=str(metadata["section"]) if metadata.get("section") else None,
        page_end=page_end,
        text=result.chunk.text,
        document_url=url,
        document_type=str(metadata.get("document_type", "unclassified")),
        status=str(metadata.get("status", "unreviewed")),
        populations=list(metadata.get("populations", [])),
        topics=list(metadata.get("topics", [])),
        jurisdiction=metadata.get("jurisdiction"),
        publication_date=metadata.get("publication_date"),
        document_version=metadata.get("document_version"),
        superseded_by=metadata.get("superseded_by"),
        review_notes=metadata.get("review_notes"),
    )
