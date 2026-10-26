from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from medical_rag.chunking import chunk_pages
from medical_rag.documents import is_supported_source_file, iter_source_files, load_source_file
from medical_rag.types import Chunk, PageText

PARSER_VERSION = "pymupdf-sorted-text-v1"
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IngestionOptions:
    force: bool = False
    resume: bool = True
    failed_only: bool = False
    ocr_scanned: bool = False
    pdf_workers: int = 1


@dataclass(frozen=True)
class SourceFile:
    path: Path
    sha256: str
    size: int
    mtime_ns: int
    duplicate_of: str | None = None

    @property
    def cache_key(self) -> str:
        return self.sha256


@dataclass(frozen=True)
class ExtractedDocument:
    source: SourceFile
    pages: list[PageText]
    scanned_pages: int = 0
    from_cache: bool = False


@dataclass
class ChunkedDocument:
    """One source file after extraction (or a cache hit) and chunking, or its failure."""

    source: SourceFile
    chunks: list[Chunk] = field(default_factory=list)
    pages: int = 0
    scanned_pages: int = 0
    from_cache: bool = False
    error: str | None = None
    extraction_seconds: float = 0.0
    chunking_seconds: float = 0.0


@dataclass
class IngestionTimings:
    discovery_seconds: float = 0.0
    extraction_seconds: float = 0.0
    chunking_seconds: float = 0.0
    embedding_seconds: float = 0.0
    index_write_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return (
            self.discovery_seconds
            + self.extraction_seconds
            + self.chunking_seconds
            + self.embedding_seconds
            + self.index_write_seconds
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "discovery_seconds": round(self.discovery_seconds, 4),
            "extraction_seconds": round(self.extraction_seconds, 4),
            "chunking_seconds": round(self.chunking_seconds, 4),
            "embedding_seconds": round(self.embedding_seconds, 4),
            "index_write_seconds": round(self.index_write_seconds, 4),
            "total_seconds": round(self.total_seconds, 4),
        }


@dataclass
class IngestionState:
    source_path: Path
    files: list[SourceFile]
    unique_files: list[SourceFile]
    changed_files: list[SourceFile]
    deleted_paths: list[str]
    documents: list[ExtractedDocument] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    timings: IngestionTimings = field(default_factory=IngestionTimings)
    failed_files: dict[str, str] = field(default_factory=dict)

    @property
    def duplicate_files(self) -> int:
        return len([item for item in self.files if item.duplicate_of])

    @property
    def scanned_pages(self) -> int:
        return sum(document.scanned_pages for document in self.documents)

    @property
    def pages(self) -> int:
        return sum(len(document.pages) for document in self.documents)

    @property
    def cache_hits(self) -> int:
        return len([document for document in self.documents if document.from_cache])

    @property
    def files_processed(self) -> int:
        return len([document for document in self.documents if not document.from_cache])


class ManifestStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def changed_files(
        self,
        files: list[SourceFile],
        chunk_size_chars: int,
        chunk_overlap_chars: int,
        embedding_model: str,
        force: bool,
        failed_only: bool,
    ) -> list[SourceFile]:
        if force:
            return [file for file in files if not file.duplicate_of]

        # One query for every row: a connection per file is slow on shared storage.
        with self._connect() as connection:
            rows = {row["path"]: row for row in connection.execute("SELECT * FROM documents")}
        changed = []
        for file in files:
            if file.duplicate_of:
                continue
            row = rows.get(str(file.path))
            if row is None:
                if failed_only:
                    continue
                changed.append(file)
                continue
            if failed_only and row["status"] != "failed":
                continue
            if row["status"] == "failed":
                changed.append(file)
                continue
            if (
                row["sha256"] != file.sha256
                or row["size"] != file.size
                or row["mtime_ns"] != file.mtime_ns
                or row["parser_version"] != PARSER_VERSION
                or row["chunk_size_chars"] != chunk_size_chars
                or row["chunk_overlap_chars"] != chunk_overlap_chars
                or row["embedding_model"] != embedding_model
            ):
                changed.append(file)

        return changed

    def deleted_paths(self, current_paths: set[str]) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT path FROM documents WHERE status != 'deleted'").fetchall()
        return [row["path"] for row in rows if row["path"] not in current_paths]

    def mark_deleted(self, paths: list[str]) -> None:
        with self._connect() as connection:
            now = time.time()
            for path in paths:
                connection.execute(
                    "UPDATE documents SET status = ?, updated_at = ? WHERE path = ?",
                    ("deleted", now, path),
                )

    def mark_duplicates(self, files: list[SourceFile]) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO documents (
                    path, sha256, size, mtime_ns, status, duplicate_of, pages, chunks, error,
                    parser_version, chunk_size_chars, chunk_overlap_chars, embedding_model, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    status = excluded.status,
                    duplicate_of = excluded.duplicate_of,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        str(file.path),
                        file.sha256,
                        file.size,
                        file.mtime_ns,
                        "duplicate",
                        file.duplicate_of,
                        0,
                        0,
                        None,
                        PARSER_VERSION,
                        0,
                        0,
                        "",
                        now,
                    )
                    for file in files
                ],
            )

    def mark_indexed(
        self,
        file: SourceFile,
        pages: int,
        chunks: int,
        chunk_size_chars: int,
        chunk_overlap_chars: int,
        embedding_model: str,
        scanned_pages: int = 0,
    ) -> None:
        self.mark_indexed_many(
            [(file, pages, chunks, scanned_pages)],
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            embedding_model=embedding_model,
        )

    def mark_indexed_many(
        self,
        files: list[tuple[SourceFile, int, int, int]],
        chunk_size_chars: int,
        chunk_overlap_chars: int,
        embedding_model: str,
    ) -> None:
        """Record ``(file, pages, chunks, scanned_pages)`` entries in one transaction; a
        commit per file costs a sync each on shared storage."""
        now = time.time()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO documents (
                    path, sha256, size, mtime_ns, status, duplicate_of, pages, chunks, error,
                    parser_version, chunk_size_chars, chunk_overlap_chars, embedding_model,
                    scanned_pages, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    status = excluded.status,
                    duplicate_of = excluded.duplicate_of,
                    pages = excluded.pages,
                    chunks = excluded.chunks,
                    error = excluded.error,
                    parser_version = excluded.parser_version,
                    chunk_size_chars = excluded.chunk_size_chars,
                    chunk_overlap_chars = excluded.chunk_overlap_chars,
                    embedding_model = excluded.embedding_model,
                    scanned_pages = excluded.scanned_pages,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        str(file.path),
                        file.sha256,
                        file.size,
                        file.mtime_ns,
                        "indexed",
                        None,
                        pages,
                        chunks,
                        None,
                        PARSER_VERSION,
                        chunk_size_chars,
                        chunk_overlap_chars,
                        embedding_model,
                        scanned_pages,
                        now,
                    )
                    for file, pages, chunks, scanned_pages in files
                ],
            )

    def mark_failed(self, file: SourceFile, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    path, sha256, size, mtime_ns, status, duplicate_of, pages, chunks, error,
                    parser_version, chunk_size_chars, chunk_overlap_chars, embedding_model, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    str(file.path),
                    file.sha256,
                    file.size,
                    file.mtime_ns,
                    "failed",
                    None,
                    0,
                    0,
                    error[:2000],
                    PARSER_VERSION,
                    0,
                    0,
                    "",
                    time.time(),
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    duplicate_of TEXT,
                    pages INTEGER NOT NULL DEFAULT 0,
                    chunks INTEGER NOT NULL DEFAULT 0,
                    scanned_pages INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    parser_version TEXT NOT NULL,
                    chunk_size_chars INTEGER NOT NULL DEFAULT 0,
                    chunk_overlap_chars INTEGER NOT NULL DEFAULT 0,
                    embedding_model TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(MANIFEST_SCHEMA_VERSION)),
            )


def discover_source_files(path: Path, workers: int = 1) -> list[SourceFile]:
    raw_files = iter_source_files(path)
    seen_hashes: dict[str, str] = {}
    files: list[SourceFile] = []

    # Hashing is dominated by file-open and read latency on shared storage, and hashlib
    # releases the GIL, so threads overlap it. Results come back in input order, so the
    # first copy of a duplicate in sorted order is still the one kept.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        hashed = list(pool.map(_hash_and_stat, raw_files))

    for raw_file, (digest, stat) in zip(raw_files, hashed, strict=True):
        duplicate_of = seen_hashes.get(digest)
        if duplicate_of is None:
            seen_hashes[digest] = str(raw_file)
        files.append(
            SourceFile(
                path=raw_file,
                sha256=digest,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                duplicate_of=duplicate_of,
            )
        )
    return files


def iter_chunked_documents(
    files: list[SourceFile],
    cache_dir: Path,
    options: IngestionOptions,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> Iterator[ChunkedDocument]:
    """Extract (or load from the cache) and chunk ``files`` on worker processes, yielding
    each document in input order as soon as it and every earlier one are ready.

    This lets embedding start on the first documents while later ones are still being
    parsed. Only a bounded window of documents is in flight, so memory does not grow with
    the corpus when parsing outpaces embedding. Failures are yielded with ``error`` set.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    job = partial(
        _extract_and_chunk,
        cache_dir=cache_dir,
        force=options.force,
        ocr_scanned=options.ocr_scanned,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    workers = max(1, options.pdf_workers)
    if workers == 1:
        yield from map(job, files)
        return

    remaining = iter(files)
    pending: deque[tuple[SourceFile, Future[ChunkedDocument]]] = deque()
    with ProcessPoolExecutor(max_workers=workers) as pool:

        def submit_next() -> None:
            file = next(remaining, None)
            if file is not None:
                pending.append((file, pool.submit(job, file)))

        try:
            for _ in range(workers * _DOCUMENTS_IN_FLIGHT_PER_WORKER):
                submit_next()
            while pending:
                file, future = pending.popleft()
                submit_next()
                try:
                    document = future.result()
                except Exception as exc:  # noqa: BLE001 - e.g. a worker crash; record and continue.
                    document = ChunkedDocument(source=file, error=str(exc))
                yield document
        finally:
            # If ingestion stops early, don't parse the rest of the window before exiting.
            for _, future in pending:
                future.cancel()


# Documents queued per extraction worker: enough to keep every worker busy while the
# consumer is slow, without holding the whole corpus's chunks in memory.
_DOCUMENTS_IN_FLIGHT_PER_WORKER = 4


def chunk_document(
    document: ExtractedDocument, chunk_size_chars: int, chunk_overlap_chars: int
) -> list[Chunk]:
    chunks = chunk_pages(
        document.pages,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    for chunk in chunks:
        chunk.metadata.update(
            {
                "source_hash": document.source.sha256,
                "source_size": document.source.size,
                "source_mtime_ns": document.source.mtime_ns,
                "parser_version": "pymupdf-sorted-text-v1",
                "chunk_size_chars": chunk_size_chars,
                "chunk_overlap_chars": chunk_overlap_chars,
            }
        )
    return chunks


def _extract_and_chunk(
    file: SourceFile,
    cache_dir: Path,
    force: bool,
    ocr_scanned: bool,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> ChunkedDocument:
    started = time.perf_counter()
    try:
        document = None if force else _read_extraction_cache(file, cache_dir)
        if document is None:
            document = _extract_one(file, ocr_scanned)
            _write_extraction_cache(document, cache_dir)
    except Exception as exc:  # noqa: BLE001 - record and continue ingestion.
        return ChunkedDocument(source=file, error=str(exc))
    extracted = time.perf_counter()
    chunks = chunk_document(document, chunk_size_chars, chunk_overlap_chars)
    return ChunkedDocument(
        source=file,
        chunks=chunks,
        pages=len(document.pages),
        scanned_pages=document.scanned_pages,
        from_cache=document.from_cache,
        extraction_seconds=extracted - started,
        chunking_seconds=time.perf_counter() - extracted,
    )


def _hash_and_stat(path: Path) -> tuple[str, os.stat_result]:
    return sha256_file(path), path.stat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_one(file: SourceFile, ocr_scanned: bool) -> ExtractedDocument:
    pages, scanned_pages = load_source_file(file.path, ocr_scanned=ocr_scanned)
    return ExtractedDocument(source=file, pages=pages, scanned_pages=scanned_pages)


def _source_to_payload(file: SourceFile) -> dict[str, Any]:
    return {
        "path": str(file.path),
        "sha256": file.sha256,
        "size": file.size,
        "mtime_ns": file.mtime_ns,
        "duplicate_of": file.duplicate_of,
    }


def _document_to_payload(document: ExtractedDocument) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "source": _source_to_payload(document.source),
        "scanned_pages": document.scanned_pages,
        "pages": [
            {
                "source_id": page.source_id,
                "source_path": page.source_path,
                "title": page.title,
                "page_number": page.page_number,
                "text": page.text,
            }
            for page in document.pages
        ],
    }


def _payload_to_document(payload: dict[str, Any], from_cache: bool = False) -> ExtractedDocument:
    source_payload = payload["source"]
    source = SourceFile(
        path=Path(source_payload["path"]),
        sha256=source_payload["sha256"],
        size=source_payload["size"],
        mtime_ns=source_payload["mtime_ns"],
        duplicate_of=source_payload.get("duplicate_of"),
    )
    return ExtractedDocument(
        source=source,
        scanned_pages=int(payload.get("scanned_pages", 0)),
        from_cache=from_cache,
        pages=[
            PageText(
                source_id=page["source_id"],
                source_path=page["source_path"],
                title=page["title"],
                page_number=page["page_number"],
                text=page["text"],
            )
            for page in payload.get("pages", [])
        ],
    )


def _read_extraction_cache(file: SourceFile, cache_dir: Path) -> ExtractedDocument | None:
    path = _cache_path(file, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    source = payload.get("source", {})
    if (
        payload.get("parser_version") != PARSER_VERSION
        or source.get("sha256") != file.sha256
        or source.get("size") != file.size
        or source.get("mtime_ns") != file.mtime_ns
    ):
        return None
    return _payload_to_document(payload, from_cache=True)


def _write_extraction_cache(document: ExtractedDocument, cache_dir: Path) -> None:
    path = _cache_path(document.source, cache_dir)
    path.write_text(json.dumps(_document_to_payload(document)), encoding="utf-8")


def _cache_path(file: SourceFile, cache_dir: Path) -> Path:
    return cache_dir / f"{file.cache_key}.json"


def is_supported_source(path: Path) -> bool:
    return is_supported_source_file(path)
