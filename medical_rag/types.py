from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PageText:
    source_id: str
    source_path: str
    title: str
    page_number: int | None
    text: str
    hierarchy: list[str] | None = None
    layout_hints: dict[str, Any] | None = None


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float
    rank: int


@dataclass(frozen=True)
class Citation:
    id: int
    source: str
    page: int | None
    chunk_id: str
    score: float
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IngestionReport:
    source_path: str
    documents: int
    pages: int
    chunks: int
    index_path: str
    embedding_model: str
    files_discovered: int = 0
    files_changed: int = 0
    files_processed: int = 0
    files_from_cache: int = 0
    files_failed: int = 0
    duplicate_files: int = 0
    deleted_files: int = 0
    scanned_pages: int = 0
    skipped_unchanged: bool = False
    manifest_path: str | None = None
    extraction_cache_dir: str | None = None
    timings: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAnswer:
    question: str
    answer: str
    citations: list[Citation]
    retrieval_model: str
    generation_model: str
    answer_mode: str
    safety_notice: str
    retrieval_mode: str = "vector"
    fallback_embedding: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["citations"] = [citation.to_dict() for citation in self.citations]
        return payload
