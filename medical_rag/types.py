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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAnswer:
    question: str
    answer: str
    citations: list[Citation]
    retrieval_model: str
    generation_model: str
    safety_notice: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["citations"] = [citation.to_dict() for citation in self.citations]
        return payload
