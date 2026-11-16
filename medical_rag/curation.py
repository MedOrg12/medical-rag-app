"""Curator-maintained applicability metadata, lifecycle policy, and disagreement notes."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from medical_rag.types import SearchResult

DocumentType = Literal["unclassified", "guideline", "systematic_review", "trial", "observational_study", "patient_education", "local_protocol", "other"]
DocumentStatus = Literal["unreviewed", "current", "superseded", "withdrawn"]
INACTIVE_STATUSES = {"superseded", "withdrawn"}


class ConflictNote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    with_source: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=1, max_length=200)
    source_position: str = Field(min_length=1, max_length=2000)
    other_position: str = Field(min_length=1, max_length=2000)
    context: str = Field(min_length=1, max_length=2000)
    source_page: int | None = Field(default=None, ge=1)
    other_page: int | None = Field(default=None, ge=1)


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    title: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1000, le=9999)
    publication_date: str | None = None
    document_type: DocumentType = "unclassified"
    populations: list[str] = Field(default_factory=list, max_length=50)
    topics: list[str] = Field(default_factory=list, max_length=50)
    jurisdiction: str | None = Field(default=None, max_length=200)
    document_version: str | None = Field(default=None, max_length=200)
    status: DocumentStatus = "unreviewed"
    superseded_by: str | None = Field(default=None, max_length=500)
    review_notes: str | None = Field(default=None, max_length=4000)
    reviewed_by: str | None = Field(default=None, max_length=200)
    conflicts: list[ConflictNote] = Field(default_factory=list, max_length=30)

    @field_validator("populations", "topics")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        if any(not tag.strip() or len(tag) > 200 for tag in tags):
            raise ValueError("Tags must contain 1 to 200 characters.")
        return list(dict.fromkeys(tag.strip().casefold() for tag in tags))

    @field_validator("publication_date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Use an ISO publication date (YYYY-MM-DD).")
        return value

    @model_validator(mode="after")
    def check_consistency(self):
        if self.publication_date:
            year = date.fromisoformat(self.publication_date).year
            if self.publication_year is not None and self.publication_year != year:
                raise ValueError("Publication year must agree with publication date.")
            self.publication_year = year
        if self.status in INACTIVE_STATUSES and not self.review_notes:
            raise ValueError("Superseded or withdrawn documents need a reason in review_notes.")
        if self.superseded_by and self.status != "superseded":
            raise ValueError("superseded_by is only valid for a superseded document.")
        return self


class LibraryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_types: list[DocumentType] = Field(default_factory=list, max_length=8)
    populations: list[str] = Field(default_factory=list, max_length=50)
    topics: list[str] = Field(default_factory=list, max_length=50)
    jurisdiction: str | None = Field(default=None, max_length=200)
    reviewed_only: bool = False
    include_inactive: bool = False

    @field_validator("populations", "topics")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return DocumentMetadata.normalize_tags(tags)

    def matches(self, metadata: DocumentMetadata) -> bool:
        return (
            (not self.document_types or metadata.document_type in self.document_types)
            and (not self.populations or bool(set(self.populations) & set(metadata.populations)))
            and (not self.topics or bool(set(self.topics) & set(metadata.topics)))
            and (not self.jurisdiction or self.jurisdiction.casefold() == (metadata.jurisdiction or "").casefold())
            and (not self.reviewed_only or metadata.status != "unreviewed")
            and (self.include_inactive or metadata.status not in INACTIVE_STATUSES)
        )

    @property
    def restricts_metadata(self) -> bool:
        return bool(self.document_types or self.populations or self.topics or self.jurisdiction or self.reviewed_only)


class CatalogConflictError(ValueError):
    """The catalog changed after an editor loaded it."""


class SourceCatalog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._cache_signature = None
        self._cache_entries: dict[str, DocumentMetadata] = {}
        self._cache_revision = ""

    def snapshot(self) -> tuple[dict[str, DocumentMetadata], str]:
        with self._lock:
            try:
                stat = self.path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature == self._cache_signature:
                    return self._cache_entries, self._cache_revision
                raw = self.path.read_bytes()
            except FileNotFoundError:
                signature = None
                raw = b"{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Source catalog must be an object keyed by indexed source_id.")
            entries = {key: DocumentMetadata.model_validate(value) for key, value in data.items()}
            self._validate_replacement_cycles(entries)
            revision = hashlib.sha256(raw).hexdigest()
            self._cache_signature, self._cache_entries, self._cache_revision = signature, entries, revision
            return entries, revision

    def enrich(self, result: SearchResult, entries: dict[str, DocumentMetadata] | None = None) -> SearchResult:
        entries = self.snapshot()[0] if entries is None else entries
        entry = entries.get(str(result.chunk.metadata.get("source_id")))
        if entry is None:
            return result
        fields = entry.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        metadata = {**result.chunk.metadata, **{key: value for key, value in fields.items() if value != ""}}
        return replace(result, chunk=replace(result.chunk, metadata=metadata))

    def save(self, source_id: str, metadata: DocumentMetadata, revision: str, known_sources: set[str]) -> dict[str, Any]:
        # SQLite's file lock serializes catalog writers across app processes and platforms.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(sqlite3.connect(str(self.path) + ".lock.sqlite")) as lock, lock:
            lock.execute("BEGIN IMMEDIATE")
            entries, current_revision = self.snapshot()
            if current_revision != revision:
                raise CatalogConflictError("The library metadata changed. Reload the document before saving.")
            if source_id not in known_sources:
                raise KeyError(source_id)
            references = {note.with_source for note in metadata.conflicts}
            if metadata.superseded_by:
                references.add(metadata.superseded_by)
            if source_id in references or references - known_sources:
                raise ValueError("Replacement and disagreement sources must be different, indexed documents.")
            entries = {**entries, source_id: metadata}
            self._validate_replacement_cycles(entries)
            payload = {key: value.model_dump(mode="json", exclude_none=True) for key, value in entries.items()}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                    temporary = output.name
                    json.dump(payload, output, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            return {"source_id": source_id, "metadata": payload[source_id], "revision": self.snapshot()[1]}

    @staticmethod
    def _validate_replacement_cycles(entries: dict[str, DocumentMetadata]) -> None:
        for start in entries:
            visited = set()
            source = start
            while source in entries and entries[source].superseded_by:
                if source in visited:
                    raise ValueError("Supersession links cannot form a cycle.")
                visited.add(source)
                source = entries[source].superseded_by


def retrieval_scope(entries: dict[str, DocumentMetadata], scope: LibraryFilters, filters: dict[str, str] | None) -> dict[str, Any]:
    result: dict[str, Any] = dict(filters or {})
    excluded = {source for source, metadata in entries.items() if not scope.include_inactive and metadata.status in INACTIVE_STATUSES}
    if scope.restricts_metadata:
        included = {source for source, metadata in entries.items() if scope.matches(metadata)}
        if "source_id" in result:
            included &= {result["source_id"]}
        result["source_id"] = {"$in": sorted(included)}
    elif "source_id" in result:
        if result["source_id"] in excluded:
            result["source_id"] = {"$in": []}
    elif excluded:
        result["source_id"] = {"$nin": sorted(excluded)}
    return result


def source_disagreements(results: list[SearchResult], entries: dict[str, DocumentMetadata]) -> list[dict[str, Any]]:
    retrieved: dict[str, list[int]] = {}
    for number, result in enumerate(results, 1):
        retrieved.setdefault(str(result.chunk.metadata.get("source_id")), []).append(number)
    disagreements = []
    seen = set()
    for source, metadata in entries.items():
        for note in metadata.conflicts:
            if source not in retrieved and note.with_source not in retrieved:
                continue
            key = (*sorted((source, note.with_source)), note.topic.casefold())
            if key in seen:
                continue
            seen.add(key)
            other = entries.get(note.with_source, DocumentMetadata())
            disagreements.append({
                **note.model_dump(), "source_id": source,
                "source_title": entries[source].title or source,
                "other_title": other.title or note.with_source,
                "source_status": entries[source].status, "other_status": other.status,
                "source_citation_ids": retrieved.get(source, []),
                "other_citation_ids": retrieved.get(note.with_source, []),
                "both_sources_retrieved": source in retrieved and note.with_source in retrieved,
                "provenance": "curator_recorded",
            })
    return disagreements
