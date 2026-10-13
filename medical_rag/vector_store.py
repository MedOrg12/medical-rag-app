from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import deque
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Protocol

from medical_rag.bm25 import BM25Index
from medical_rag.config import Settings
from medical_rag.embeddings import EmbeddingModel
from medical_rag.types import Chunk, SearchResult

SCHEMA_VERSION = 1

# Upserts allowed to be queued or running while the next batch is embedded. One writer
# thread keeps them in order; the bound stops a slow Qdrant disk from letting embedded
# batches pile up in memory, and makes the embedding loop wait instead.
_MAX_PENDING_UPSERTS = 2

# Every Nth upsert (and the last) uses wait=True. Qdrant acknowledges a wait=False upsert
# before applying it, so on a slow disk its apply backlog could otherwise grow for the whole
# run and the final wait would have to drain all of it inside a single request timeout.
_UPSERTS_PER_WAIT = 8

# Upper bound on the JSON size of one float in a REST upsert body (e.g. "-1.2345678901234567e-05,"),
# plus per-point framing (id, vector name, braces), used to keep requests under Qdrant's
# service.max_request_size_mb. Measured 768-dim bge vectors average ~22 bytes per float.
_JSON_BYTES_PER_FLOAT = 24
_JSON_BYTES_PER_POINT = 128

# Qdrant's own default HNSW indexing threshold (KB of vectors per segment), restored when a
# collection is found with indexing still paused by an ingest that was killed mid-run.
_DEFAULT_INDEXING_THRESHOLD_KB = 10000

# Payload field the source list is counted by. Qdrant can only facet on an indexed field.
_SOURCE_ID_FIELD = "metadata.source_id"

# Facet results are capped at ``limit`` values; set far above any realistic corpus so every
# source is counted, unless the collection's strict mode allows less.
_MAX_FACET_SOURCES = 1_000_000


class VectorStoreBackend(Protocol):
    @property
    def retrieval_mode(self) -> str:
        ...

    def chunk_count(self) -> int:
        ...

    def search(
        self,
        query: str,
        embedding_model: EmbeddingModel,
        top_k: int,
        filters: dict[str, Any] | None = None,
        hybrid: bool = True,
    ) -> list[SearchResult]:
        ...

    def source_summaries(self) -> list[dict[str, Any]]:
        """One entry per source with at least ``source_id`` and ``chunks``. Backends that
        can afford it also include ``title``, ``source_path`` and ``pages``."""
        ...


@dataclass
class IngestStats:
    """What an ingestion run did, so reports can show reuse and per-stage timings.

    For Qdrant, the ``*_seconds`` phases split the ingest loop's wall time with nothing left
    over: each moment is charged to exactly one phase, and ``total_seconds`` is their sum.
    Writes run on a background thread, so ``write_wait_seconds`` is only the time the loop
    was stuck behind them; ``upsert_busy_seconds`` is how long the writer itself was busy.
    """

    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    stale_points_removed: int = 0
    embedding_seconds: float = 0.0
    # Main-thread time on write-side work: for Qdrant, setup + point building + waiting on
    # the writer + cleanup. Sums with embedding and lookup time.
    write_seconds: float = 0.0
    setup_seconds: float = 0.0
    # Waiting for the next chunks from upstream extraction and chunking, which now run
    # alongside the ingest loop.
    source_wait_seconds: float = 0.0
    lookup_seconds: float = 0.0
    point_build_seconds: float = 0.0
    write_wait_seconds: float = 0.0
    cleanup_seconds: float = 0.0
    total_seconds: float = 0.0
    upsert_requests: int = 0
    upsert_busy_seconds: float = 0.0
    upsert_request_mb: float = 0.0


class _PhaseTimer:
    """Charges elapsed wall time to whichever phase is current, so phases never overlap
    and always add up to the total, leaving no unexplained time."""

    def __init__(self, stats: IngestStats) -> None:
        self._stats = stats
        self._phase: str | None = None
        self._since = time.perf_counter()

    def enter(self, phase: str | None) -> None:
        now = time.perf_counter()
        if self._phase is not None:
            field = f"{self._phase}_seconds"
            setattr(self._stats, field, getattr(self._stats, field) + now - self._since)
        self._phase = phase
        self._since = now


def ingest_vector_store(
    settings: Settings, chunks: Iterable[Chunk], embedding_model: EmbeddingModel
) -> tuple[VectorStoreBackend, IngestStats]:
    """Embed ``chunks`` and write them to the configured backend, streaming in batches.

    ``chunks`` may be a lazy stream; the Qdrant backend consumes it batch by batch, so
    embedding can start before upstream extraction has finished.

    Vectors already present for an identical chunk (same id, same text, same embedding
    model) are reused instead of re-embedded, so re-running over an unchanged corpus
    costs no embedding work. Memory stays proportional to the batch size for Qdrant.
    """
    batch_size = max(1, settings.embedding_batch_size)
    if settings.vector_store_backend == "json":
        return VectorStore.ingest(
            path=settings.index_path,
            chunks=list(chunks),
            embedding_model=embedding_model,
            batch_size=batch_size,
        )
    if settings.vector_store_backend == "qdrant":
        return QdrantVectorStore.ingest(
            settings=settings,
            chunks=chunks,
            embedding_model=embedding_model,
            batch_size=batch_size,
        )
    raise ValueError(f"Unsupported vector store backend: {settings.vector_store_backend!r}")


def load_vector_store(settings: Settings) -> VectorStoreBackend:
    if settings.vector_store_backend == "json":
        return VectorStore.load(settings.index_path)
    if settings.vector_store_backend == "qdrant":
        return QdrantVectorStore.load(settings)
    raise ValueError(f"Unsupported vector store backend: {settings.vector_store_backend!r}")


def vector_store_exists(settings: Settings) -> bool:
    if settings.vector_store_backend == "json":
        return settings.index_path.exists()
    if settings.vector_store_backend == "qdrant":
        return QdrantVectorStore.collection_exists(settings)
    raise ValueError(f"Unsupported vector store backend: {settings.vector_store_backend!r}")


class VectorStore:
    def __init__(
        self,
        path: Path,
        chunks: list[Chunk] | None = None,
        vectors: list[list[float]] | None = None,
        embedding_model: str | None = None,
        bm25: BM25Index | None = None,
    ) -> None:
        self.path = path
        self.chunks = chunks or []
        self.vectors = vectors or []
        self.embedding_model = embedding_model
        self._bm25 = bm25

    @property
    def retrieval_mode(self) -> str:
        return "hybrid" if self._bm25 is not None else "vector"

    def chunk_count(self) -> int:
        return len(self.chunks)

    @classmethod
    def build(cls, path: Path, chunks: list[Chunk], embedding_model: EmbeddingModel) -> VectorStore:
        vectors = embedding_model.embed([chunk.text for chunk in chunks])
        bm25 = BM25Index.build(chunks)
        return cls(path=path, chunks=chunks, vectors=vectors, embedding_model=embedding_model.name, bm25=bm25)

    @classmethod
    def ingest(
        cls,
        path: Path,
        chunks: list[Chunk],
        embedding_model: EmbeddingModel,
        batch_size: int,
    ) -> tuple[VectorStore, IngestStats]:
        """Rebuild the index, reusing vectors from the existing file for unchanged chunks."""
        stats = IngestStats(chunks_total=len(chunks))
        existing: dict[str, tuple[str, list[float]]] = {}
        if path.exists():
            try:
                previous = cls.load(path)
            except (ValueError, OSError, KeyError):
                previous = None
            if previous is not None and previous.embedding_model == embedding_model.name:
                existing = {
                    chunk.id: (chunk.text, vector)
                    for chunk, vector in zip(previous.chunks, previous.vectors, strict=True)
                }

        vectors: list[list[float] | None] = [None] * len(chunks)
        missing: list[int] = []
        for index, chunk in enumerate(chunks):
            match = existing.get(chunk.id)
            if match is not None and match[0] == chunk.text:
                vectors[index] = match[1]
            else:
                missing.append(index)
        stats.chunks_reused = len(chunks) - len(missing)

        embed_started = time.perf_counter()
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            embedded = embedding_model.embed([chunks[index].text for index in batch])
            for index, vector in zip(batch, embedded, strict=True):
                vectors[index] = vector
        stats.chunks_embedded = len(missing)
        stats.embedding_seconds = time.perf_counter() - embed_started

        write_started = time.perf_counter()
        store = cls(
            path=path,
            chunks=chunks,
            vectors=[vector for vector in vectors if vector is not None],
            embedding_model=embedding_model.name,
            bm25=BM25Index.build(chunks),
        )
        store.save()
        stats.write_seconds = time.perf_counter() - write_started
        return store, stats

    @classmethod
    def load(cls, path: Path) -> VectorStore:
        if not path.exists():
            raise FileNotFoundError(f"Vector index does not exist: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported vector index schema: {payload.get('schema_version')}. "
                f"Expected {SCHEMA_VERSION}."
            )

        chunks = [
            Chunk(id=item["id"], text=item["text"], metadata=item.get("metadata", {}))
            for item in payload.get("chunks", [])
        ]
        vectors = [[float(value) for value in vector] for vector in payload.get("vectors", [])]

        bm25_data = payload.get("bm25")
        bm25 = BM25Index.from_dict(bm25_data) if bm25_data else None

        return cls(
            path=path,
            chunks=chunks,
            vectors=vectors,
            embedding_model=payload.get("embedding_model"),
            bm25=bm25,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding_model": self.embedding_model,
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "vectors": self.vectors,
            "bm25": self._bm25.to_dict() if self._bm25 is not None else None,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def search(
        self,
        query: str,
        embedding_model: EmbeddingModel,
        top_k: int,
        filters: dict[str, Any] | None = None,
        hybrid: bool = True,
    ) -> list[SearchResult]:
        if not self.chunks:
            return []
        if self.embedding_model != embedding_model.name:
            raise ValueError(
                "The index was built with "
                f"{self.embedding_model}, but the current embedding model is {embedding_model.name}. "
                "Re-run ingestion or use the same embedding backend."
            )

        candidate_limit = min(max(top_k * 4, top_k), 50)

        # Vector search
        query_vector = embedding_model.embed([query])[0]
        vec_scored: list[tuple[float, Chunk]] = []
        for chunk, vector in zip(self.chunks, self.vectors):
            if filters and not _matches_filters(chunk.metadata, filters):
                continue
            vec_scored.append((_dot(query_vector, vector), chunk))
        vec_scored.sort(key=lambda item: item[0], reverse=True)

        if not (hybrid and self._bm25 is not None):
            return [
                SearchResult(chunk=chunk, score=score, rank=rank)
                for rank, (score, chunk) in enumerate(vec_scored[:top_k], start=1)
            ]

        # Hybrid: RRF combination
        vec_top = vec_scored[:candidate_limit]
        bm25_top = self._bm25.search(query, top_k=candidate_limit)

        vec_rank: dict[str, int] = {chunk.id: rank for rank, (_, chunk) in enumerate(vec_top, start=1)}
        bm25_rank: dict[str, float] = {cid: rank for rank, (cid, _) in enumerate(bm25_top, start=1)}

        all_ids = set(vec_rank) | set(bm25_rank)
        chunk_by_id = {chunk.id: chunk for _, chunk in vec_top}
        for cid, _ in bm25_top:
            if cid not in chunk_by_id:
                for chunk in self.chunks:
                    if chunk.id == cid:
                        if not filters or _matches_filters(chunk.metadata, filters):
                            chunk_by_id[cid] = chunk
                        break

        rrf_scores: list[tuple[float, str]] = []
        for cid in all_ids:
            if cid not in chunk_by_id:
                continue
            vr = vec_rank.get(cid, candidate_limit + 60)
            br = bm25_rank.get(cid, candidate_limit + 60)
            rrf = 1.0 / (60 + vr) + 1.0 / (60 + br)
            rrf_scores.append((rrf, cid))

        rrf_scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (score, cid) in enumerate(rrf_scores[:top_k], start=1):
            chunk = chunk_by_id.get(cid)
            if chunk is not None:
                results.append(SearchResult(chunk=chunk, score=score, rank=rank))
        return results

    def source_summaries(self) -> list[dict[str, Any]]:
        return _summarize_sources(chunk.metadata for chunk in self.chunks)


def _summarize_sources(metadata_items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per-source chunk counts and pages without holding chunk text."""
    summaries: dict[str, dict[str, Any]] = {}
    for metadata in metadata_items:
        source_id = metadata.get("source_id", "unknown")
        entry = summaries.setdefault(
            source_id,
            {
                "source_id": source_id,
                "title": metadata.get("title", source_id),
                "source_path": metadata.get("source_path"),
                "chunks": 0,
                "pages": set(),
            },
        )
        entry["chunks"] += 1
        if metadata.get("page") is not None:
            entry["pages"].add(metadata["page"])

    results = []
    for entry in summaries.values():
        pages = sorted(entry.pop("pages"))
        entry["pages"] = pages
        results.append(entry)
    return sorted(results, key=lambda item: str(item["source_id"]).lower())


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if metadata.get(key) != expected:
            return False
    return True


class QdrantVectorStore:
    def __init__(self, settings: Settings, embedding_model_name: str | None = None) -> None:
        self.settings = settings
        self.embedding_model = embedding_model_name
        self._client: Any = None
        self._source_index_ready = False
        self._source_facet_limit = _MAX_FACET_SOURCES

    @property
    def client(self) -> Any:
        """One client per store: QdrantClient owns a connection pool and probes the server
        version on construction, so building one per search call is wasteful."""
        if self._client is None:
            self._client = _qdrant_client(self.settings)
        return self._client

    @property
    def retrieval_mode(self) -> str:
        return "vector"

    @classmethod
    def load(cls, settings: Settings) -> QdrantVectorStore:
        if not cls.collection_exists(settings):
            raise FileNotFoundError(f"Qdrant collection does not exist: {settings.qdrant_collection}")
        return cls(settings)

    @classmethod
    def collection_exists(cls, settings: Settings) -> bool:
        """Return whether the configured collection exists.

        Raises RuntimeError when Qdrant cannot be reached, so callers can tell an empty
        store apart from an unavailable one instead of treating both as "not ingested".
        """
        try:
            return bool(_qdrant_client(settings).collection_exists(settings.qdrant_collection))
        except Exception as exc:  # noqa: BLE001 - qdrant-client raises several transport types
            raise RuntimeError(
                f"Could not reach Qdrant at {settings.qdrant_url} to check collection "
                f"{settings.qdrant_collection!r}: {exc}"
            ) from exc

    @classmethod
    def ingest(
        cls,
        settings: Settings,
        chunks: Iterable[Chunk],
        embedding_model: EmbeddingModel,
        batch_size: int,
    ) -> tuple[QdrantVectorStore, IngestStats]:
        """Stream ``chunks`` into the collection one batch at a time.

        For each ``batch_size`` batch the collection is asked which point ids already hold a
        vector for the identical text and embedding model; only the rest are embedded.
        Afterwards, points whose id is not in the current corpus are deleted, so the
        collection mirrors the corpus without a separate embedding cache.

        Embedded points are upserted in requests of up to ``qdrant_batch_size`` points, cut
        short to stay under ``qdrant_max_request_mb``. Upserts run on a background thread
        with ``wait=False`` so embedding continues while earlier points are written. Every
        ``_UPSERTS_PER_WAIT``-th upsert and the last one use ``wait=True``: Qdrant applies
        a shard's updates in order, so that bounds its apply backlog, and once the last one
        returns everything has been applied. The point count is then checked against the
        corpus to catch an asynchronous write that was acknowledged but never applied.

        Once a run has written enough to cross Qdrant's indexing threshold, HNSW indexing is
        paused and restored afterwards, so Qdrant builds the index once instead of
        re-indexing segments on its disk during the load.
        """
        stats = IngestStats()
        timer = _PhaseTimer(stats)
        timer.enter("setup")
        store = cls(settings, embedding_model_name=embedding_model.name)
        client = store.client
        collection = settings.qdrant_collection

        collection_ready = bool(client.collection_exists(collection))
        if collection_ready and settings.qdrant_recreate_collection:
            client.delete_collection(collection, timeout=_qdrant_timeout(settings))
            collection_ready = False
        # A collection created (or recreated) by this run holds nothing to reuse, so its
        # batches skip the reuse lookup instead of paying a round trip each.
        can_reuse = collection_ready
        collection_validated = False
        restore_indexing_threshold: int | None = None
        indexing_paused = False
        pause_indexing_at_bytes = 0
        written_vector_bytes = 0
        max_request_points = max(1, settings.qdrant_batch_size)
        max_request_bytes = int(settings.qdrant_max_request_mb * 1024 * 1024)

        current_ids: set[str] = set()
        upsert_client = _qdrant_client(settings, for_bulk_upsert=True)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-upsert") as writer:
                pending: deque[Future[Any]] = deque()

                point_model = _qdrant_models().PointStruct
                vector_name = settings.qdrant_dense_vector_name

                def upsert(points: list[tuple[str, list[float], dict[str, Any]]], wait: bool) -> None:
                    started = time.perf_counter()
                    # Building the point models validates every float, so it runs here, off
                    # the embedding loop, where it overlaps GPU time.
                    upsert_client.upsert(
                        collection_name=collection,
                        points=[
                            point_model(id=point_id, vector={vector_name: vector}, payload=payload)
                            for point_id, vector, payload in points
                        ],
                        wait=wait,
                    )
                    # Only this single writer thread updates it.
                    stats.upsert_busy_seconds += time.perf_counter() - started

                def send(
                    points: list[tuple[str, list[float], dict[str, Any]]],
                    request_bytes: int,
                    final: bool = False,
                ) -> None:
                    while len(pending) >= _MAX_PENDING_UPSERTS:
                        pending.popleft().result()
                    stats.upsert_requests += 1
                    stats.upsert_request_mb += request_bytes / (1024 * 1024)
                    wait = final or stats.upsert_requests % _UPSERTS_PER_WAIT == 0
                    pending.append(writer.submit(upsert, points, wait))

                buffered: list[tuple[str, list[float], dict[str, Any]]] = []
                buffered_bytes = 0
                chunk_stream = iter(chunks)
                while True:
                    timer.enter("source_wait")
                    batch = list(islice(chunk_stream, batch_size))
                    if not batch:
                        break
                    stats.chunks_total += len(batch)

                    timer.enter("lookup")
                    point_ids = [_point_id(chunk.id) for chunk in batch]
                    current_ids.update(point_ids)

                    reusable: set[str] = set()
                    if can_reuse:
                        reusable = store._reusable_point_ids(point_ids, batch)
                    missing = [
                        (point_id, chunk)
                        for point_id, chunk in zip(point_ids, batch, strict=True)
                        if point_id not in reusable
                    ]
                    stats.chunks_reused += len(batch) - len(missing)
                    if not missing:
                        continue

                    timer.enter("embedding")
                    vectors = embedding_model.embed([chunk.text for _, chunk in missing])
                    stats.chunks_embedded += len(missing)

                    timer.enter("setup")
                    if not collection_validated:
                        # Needs a real vector to know the dimension; runs once per ingest.
                        store._ensure_collection(len(vectors[0]))
                        # Indexing an empty or existing collection up front is cheaper than
                        # building the index over everything once the load is done.
                        store._ensure_source_index()
                        collection_ready = True
                        collection_validated = True
                        threshold_kb = store._indexing_threshold_kb()
                        if threshold_kb == 0:
                            # An earlier ingest was killed before restoring indexing.
                            indexing_paused = True
                            restore_indexing_threshold = _DEFAULT_INDEXING_THRESHOLD_KB
                        # Below the threshold Qdrant would not index the new points during
                        # the load anyway, so small incremental runs leave the config alone.
                        pause_indexing_at_bytes = threshold_kb * 1024 // 2
                    # Qdrant stores dense vectors as float32.
                    written_vector_bytes += len(vectors) * len(vectors[0]) * 4
                    if not indexing_paused and written_vector_bytes >= pause_indexing_at_bytes:
                        store._set_indexing_threshold(0)
                        indexing_paused = True
                        restore_indexing_threshold = threshold_kb

                    timer.enter("point_build")
                    for (point_id, chunk), vector in zip(missing, vectors, strict=True):
                        payload = _qdrant_payload(chunk, embedding_model.name)
                        point_bytes = _estimated_request_bytes(payload, len(vector))
                        # Requests are only cut when the next point does not fit, so the
                        # buffer is never empty at the end and the last upsert can wait.
                        if buffered and (
                            len(buffered) >= max_request_points
                            or buffered_bytes + point_bytes > max_request_bytes
                        ):
                            timer.enter("write_wait")
                            send(buffered, buffered_bytes)
                            timer.enter("point_build")
                            buffered, buffered_bytes = [], 0
                        buffered.append((point_id, vector, payload))
                        buffered_bytes += point_bytes

                timer.enter("write_wait")
                if buffered:
                    send(buffered, buffered_bytes, final=True)
                while pending:
                    pending.popleft().result()

            timer.enter("cleanup")
            if collection_ready:
                # Covers a run that reused every chunk and so never reached the call above.
                store._ensure_source_index()
                # A collection this run created only holds this run's points, so scrolling
                # through all of them for stale ones would find nothing.
                if can_reuse:
                    stats.stale_points_removed = store._delete_stale_points(client, current_ids)
                stored = store.chunk_count()
                if stored != len(current_ids):
                    raise RuntimeError(
                        f"Qdrant collection {collection!r} holds {stored} points after ingestion, "
                        f"expected {len(current_ids)}; an asynchronous upsert may have failed on "
                        "the server. Check the Qdrant logs and re-run the ingest."
                    )
        finally:
            timer.enter("cleanup")
            upsert_client.close()
            if restore_indexing_threshold is not None:
                store._set_indexing_threshold(restore_indexing_threshold)
            timer.enter(None)
        stats.write_seconds = (
            stats.setup_seconds
            + stats.point_build_seconds
            + stats.write_wait_seconds
            + stats.cleanup_seconds
        )
        stats.total_seconds = (
            stats.write_seconds
            + stats.source_wait_seconds
            + stats.lookup_seconds
            + stats.embedding_seconds
        )
        return store, stats

    def _indexing_threshold_kb(self) -> int:
        info = self.client.get_collection(self.settings.qdrant_collection)
        threshold = info.config.optimizer_config.indexing_threshold
        return _DEFAULT_INDEXING_THRESHOLD_KB if threshold is None else int(threshold)

    def _set_indexing_threshold(self, threshold: int) -> None:
        self.client.update_collection(
            collection_name=self.settings.qdrant_collection,
            optimizers_config=_qdrant_models().OptimizersConfigDiff(indexing_threshold=threshold),
            timeout=_qdrant_timeout(self.settings),
        )

    def _reusable_point_ids(self, point_ids: list[str], batch: list[Chunk]) -> set[str]:
        """Ids in ``point_ids`` whose stored point was embedded from the same text by the
        same model. Payload is limited to the two tags, so the round trip is small."""
        expected = {
            point_id: _text_sha256(chunk.text)
            for point_id, chunk in zip(point_ids, batch, strict=True)
        }
        records = self.client.retrieve(
            collection_name=self.settings.qdrant_collection,
            ids=point_ids,
            with_payload=["embedding_model", "text_sha256"],
            with_vectors=False,
        )
        reusable: set[str] = set()
        for record in records:
            payload = record.payload or {}
            point_id = str(record.id)
            if (
                payload.get("embedding_model") == self.embedding_model
                and payload.get("text_sha256") == expected.get(point_id)
            ):
                reusable.add(point_id)
        return reusable

    def _delete_stale_points(self, client: Any, current_ids: set[str]) -> int:
        models = _qdrant_models()
        stale: list[str] = []
        offset = None
        while True:
            records, offset = client.scroll(
                collection_name=self.settings.qdrant_collection,
                limit=1024,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            stale.extend(str(record.id) for record in records if str(record.id) not in current_ids)
            if offset is None:
                break
        batch_size = max(1, self.settings.qdrant_batch_size)
        for start in range(0, len(stale), batch_size):
            client.delete(
                collection_name=self.settings.qdrant_collection,
                points_selector=models.PointIdsList(points=stale[start : start + batch_size]),
            )
        return len(stale)

    def chunk_count(self) -> int:
        result = self.client.count(collection_name=self.settings.qdrant_collection, exact=True)
        return int(getattr(result, "count", result))

    def search(
        self,
        query: str,
        embedding_model: EmbeddingModel,
        top_k: int,
        filters: dict[str, Any] | None = None,
        hybrid: bool = True,
    ) -> list[SearchResult]:
        client = self.client
        qdrant_filter = _qdrant_filter(filters, embedding_model.name)
        query_vector = embedding_model.embed([query])[0]
        response = client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=query_vector,
            using=self.settings.qdrant_dense_vector_name,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )
        points = getattr(response, "points", response)
        return [_search_result_from_point(point, rank) for rank, point in enumerate(points, start=1)]

    def source_summaries(self) -> list[dict[str, Any]]:
        # Scrolling every chunk's metadata to aggregate it here took 20+ seconds at ~275k
        # chunks, long enough for the request to time out. A facet on the indexed source id
        # does the counting on the server in one request, but it cannot return titles or
        # page numbers, so only chunk counts are reported.
        self._ensure_source_index()
        limit = self._source_facet_limit
        response = self.client.facet(
            collection_name=self.settings.qdrant_collection,
            key=_SOURCE_ID_FIELD,
            limit=limit,
            exact=True,
            timeout=_qdrant_timeout(self.settings),
        )
        # Facets cannot be paged, so a full page may have cut sources off the list.
        if len(response.hits) >= limit:
            raise RuntimeError(
                f"Qdrant collection {self.settings.qdrant_collection!r} has at least {limit} "
                "sources, more than one facet request may return; raise the collection's "
                "strict-mode max_query_limit to list them all."
            )
        summaries = [{"source_id": str(hit.value), "chunks": int(hit.count)} for hit in response.hits]
        return sorted(summaries, key=lambda item: item["source_id"].lower())

    def _ensure_source_index(self) -> None:
        """Make sure the keyword index the source facet needs exists and is built.

        Ingestion creates it, so this only builds it once, for a collection ingested before
        the index existed; building reads every point's payload, which takes a while on a
        large collection. The request is sent even when the collection already lists the
        index: Qdrant lists it as soon as a build starts, and faceting on it fails until the
        build finishes. A repeated request waits for a build in progress (from this process
        or another) and returns at once when the index is ready.
        """
        if self._source_index_ready:
            return
        info = self.client.get_collection(self.settings.qdrant_collection)
        strict_mode = getattr(info.config, "strict_mode_config", None)
        max_query_limit = getattr(strict_mode, "max_query_limit", None)
        if getattr(strict_mode, "enabled", False) and max_query_limit:
            self._source_facet_limit = min(_MAX_FACET_SOURCES, int(max_query_limit))
        self.client.create_payload_index(
            collection_name=self.settings.qdrant_collection,
            field_name=_SOURCE_ID_FIELD,
            field_schema=_qdrant_models().PayloadSchemaType.KEYWORD,
            wait=True,
            timeout=_qdrant_timeout(self.settings),
        )
        self._source_index_ready = True

    def _ensure_collection(self, vector_size: int) -> None:
        client = self.client
        models = _qdrant_models()
        if client.collection_exists(self.settings.qdrant_collection):
            self._validate_existing_collection(client, vector_size)
            return
        client.create_collection(
            collection_name=self.settings.qdrant_collection,
            vectors_config={
                self.settings.qdrant_dense_vector_name: models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
            timeout=_qdrant_timeout(self.settings),
        )

    def _validate_existing_collection(self, client: Any, vector_size: int) -> None:
        """Fail early with a clear message if the live collection cannot accept these vectors."""
        name = self.settings.qdrant_collection
        vector_name = self.settings.qdrant_dense_vector_name
        info = client.get_collection(name)
        vectors = info.config.params.vectors
        params = vectors.get(vector_name) if isinstance(vectors, dict) else None
        if params is None:
            configured = sorted(vectors) if isinstance(vectors, dict) else "an unnamed vector"
            raise ValueError(
                f"Qdrant collection {name!r} has no vector named {vector_name!r} (it has {configured}). "
                "Set RAG_QDRANT_RECREATE_COLLECTION=true to rebuild it, or use a different collection."
            )
        if int(params.size) != int(vector_size):
            raise ValueError(
                f"Qdrant collection {name!r} stores {params.size}-dimensional vectors but the embedding "
                f"model produces {vector_size} dimensions. Set RAG_QDRANT_RECREATE_COLLECTION=true to "
                "rebuild it, or use a different collection."
            )


def _qdrant_client(settings: Settings, for_bulk_upsert: bool = False) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError("qdrant-client is required for RAG_VECTOR_STORE=qdrant") from exc

    # qdrant-client defaults to a 5 second REST timeout. Collection creation on the shared
    # Qdrant service regularly takes longer than that, so use the configured timeout instead.
    # gRPC ships vectors as packed floats instead of JSON, which matters for bulk ingestion;
    # it connects to the URL's host on ``qdrant_grpc_port``.
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=_qdrant_timeout(settings),
        prefer_grpc=settings.qdrant_prefer_grpc,
        grpc_port=settings.qdrant_grpc_port,
        # Otherwise every upsert first scans each float of each point in Python looking for
        # local-inference objects (models.Document etc.), which dominated ingest write time.
        # Ingestion only sends precomputed vectors, so there is never anything to infer.
        cloud_inference=for_bulk_upsert,
    )


def _qdrant_timeout(settings: Settings) -> int:
    return max(1, math.ceil(settings.qdrant_timeout_seconds))


def _qdrant_models() -> Any:
    try:
        from qdrant_client import models
    except ImportError as exc:
        raise RuntimeError("qdrant-client is required for RAG_VECTOR_STORE=qdrant") from exc

    return models


def _qdrant_payload(chunk: Chunk, embedding_model: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "text": chunk.text,
        # Chunk ids only hash the first 120 characters of text, so the full-text hash is
        # what lets ingestion tell "unchanged" from "changed past the id prefix".
        "text_sha256": _text_sha256(chunk.text),
        "metadata": chunk.metadata,
        "embedding_model": embedding_model,
    }


def _estimated_request_bytes(payload: dict[str, Any], dimensions: int) -> int:
    """Upper bound on one point's share of a REST upsert body. ``json.dumps`` escapes
    non-ASCII text, so it over- rather than under-counts the payload."""
    return len(json.dumps(payload)) + dimensions * _JSON_BYTES_PER_FLOAT + _JSON_BYTES_PER_POINT


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _qdrant_filter(filters: dict[str, Any] | None, embedding_model: str) -> Any:
    models = _qdrant_models()
    conditions = [
        models.FieldCondition(
            key="embedding_model",
            match=models.MatchValue(value=embedding_model),
        )
    ]
    for key, expected in (filters or {}).items():
        conditions.append(
            models.FieldCondition(
                key=f"metadata.{key}",
                match=models.MatchValue(value=expected),
            )
        )
    return models.Filter(must=conditions)


def _chunk_from_payload(payload: dict[str, Any]) -> Chunk:
    return Chunk(
        id=str(payload.get("chunk_id", "")),
        text=str(payload.get("text", "")),
        metadata=dict(payload.get("metadata", {})),
    )


def _search_result_from_point(point: Any, rank: int) -> SearchResult:
    return SearchResult(
        chunk=_chunk_from_payload(point.payload or {}),
        score=float(point.score or 0.0),
        rank=rank,
    )
