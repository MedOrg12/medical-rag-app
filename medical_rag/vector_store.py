from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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

# Qdrant's own default HNSW indexing threshold (KB of vectors per segment), restored when a
# collection is found with indexing still paused by an ingest that was killed mid-run.
_DEFAULT_INDEXING_THRESHOLD_KB = 10000


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
        ...


@dataclass
class IngestStats:
    """What an ingestion run did, so reports can show reuse and per-stage timings."""

    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    stale_points_removed: int = 0
    embedding_seconds: float = 0.0
    # Qdrant writes overlap embedding, so this is only the time the ingest loop spent
    # blocked on writes (not hidden behind embedding), and it sums with embedding time.
    write_seconds: float = 0.0


def ingest_vector_store(
    settings: Settings, chunks: list[Chunk], embedding_model: EmbeddingModel
) -> tuple[VectorStoreBackend, IngestStats]:
    """Embed ``chunks`` and write them to the configured backend, streaming in batches.

    Vectors already present for an identical chunk (same id, same text, same embedding
    model) are reused instead of re-embedded, so re-running over an unchanged corpus
    costs no embedding work. Memory stays proportional to the batch size for Qdrant.
    """
    batch_size = max(1, settings.embedding_batch_size)
    if settings.vector_store_backend == "json":
        return VectorStore.ingest(
            path=settings.index_path,
            chunks=chunks,
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
        chunks: list[Chunk],
        embedding_model: EmbeddingModel,
        batch_size: int,
    ) -> tuple[QdrantVectorStore, IngestStats]:
        """Stream ``chunks`` into the collection one batch at a time.

        For each batch the collection is asked which point ids already hold a vector for
        the identical text and embedding model; only the rest are embedded and upserted.
        Afterwards, points whose id is not in the current corpus are deleted, so the
        collection mirrors the corpus without a separate embedding cache.

        Upserts run on a background thread with ``wait=False`` so the next batch is being
        embedded while the previous one is written. The final upsert uses ``wait=True``:
        Qdrant applies a shard's updates in order, so once it returns every earlier
        batch has been applied too, and the point count is checked against the corpus to
        catch an asynchronous write that was acknowledged but never applied.

        HNSW indexing is paused while points stream in and restored afterwards, so Qdrant
        builds the index once instead of re-indexing segments on its disk during the load.
        """
        store = cls(settings, embedding_model_name=embedding_model.name)
        client = store.client
        collection = settings.qdrant_collection
        stats = IngestStats(chunks_total=len(chunks))

        collection_ready = bool(client.collection_exists(collection))
        if collection_ready and settings.qdrant_recreate_collection:
            client.delete_collection(collection, timeout=_qdrant_timeout(settings))
            collection_ready = False
        # A collection created (or recreated) by this run holds nothing to reuse, so its
        # batches skip the reuse lookup instead of paying a round trip each.
        can_reuse = collection_ready
        collection_validated = False
        restore_indexing_threshold: int | None = None

        current_ids: set[str] = set()
        upsert_client = _qdrant_client(settings, for_bulk_upsert=True)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-upsert") as writer:
                pending: deque[Future[Any]] = deque()
                # The latest batch is held back one step so the last one can go out with wait=True.
                held_points: list[Any] | None = None

                def send(points: list[Any], wait: bool) -> None:
                    while len(pending) >= _MAX_PENDING_UPSERTS:
                        pending.popleft().result()
                    pending.append(
                        writer.submit(
                            upsert_client.upsert,
                            collection_name=collection,
                            points=points,
                            wait=wait,
                        )
                    )

                for start in range(0, len(chunks), batch_size):
                    batch = chunks[start : start + batch_size]
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

                    embed_started = time.perf_counter()
                    vectors = embedding_model.embed([chunk.text for _, chunk in missing])
                    stats.embedding_seconds += time.perf_counter() - embed_started
                    stats.chunks_embedded += len(missing)

                    write_started = time.perf_counter()
                    if not collection_validated:
                        # Needs a real vector to know the dimension; runs once per ingest.
                        store._ensure_collection(len(vectors[0]))
                        collection_ready = True
                        restore_indexing_threshold = store._pause_indexing()
                        collection_validated = True
                    if held_points is not None:
                        send(held_points, wait=False)
                    held_points = [
                        _qdrant_point(
                            settings=settings,
                            chunk=chunk,
                            dense_vector=vector,
                            embedding_model=embedding_model.name,
                        )
                        for (_, chunk), vector in zip(missing, vectors, strict=True)
                    ]
                    stats.write_seconds += time.perf_counter() - write_started

                write_started = time.perf_counter()
                if held_points is not None:
                    send(held_points, wait=True)
                while pending:
                    pending.popleft().result()
                stats.write_seconds += time.perf_counter() - write_started

            if collection_ready:
                write_started = time.perf_counter()
                stats.stale_points_removed = store._delete_stale_points(client, current_ids)
                stored = store.chunk_count()
                stats.write_seconds += time.perf_counter() - write_started
                if stored != len(current_ids):
                    raise RuntimeError(
                        f"Qdrant collection {collection!r} holds {stored} points after ingestion, "
                        f"expected {len(current_ids)}; an asynchronous upsert may have failed on "
                        "the server. Check the Qdrant logs and re-run the ingest."
                    )
        finally:
            upsert_client.close()
            if restore_indexing_threshold is not None:
                store._set_indexing_threshold(restore_indexing_threshold)
        return store, stats

    def _pause_indexing(self) -> int:
        """Stop HNSW indexing on the collection and return the threshold to restore."""
        client = self.client
        name = self.settings.qdrant_collection
        current = client.get_collection(name).config.optimizer_config.indexing_threshold
        # 0 means an earlier ingest was killed before restoring indexing; don't keep that.
        restore = current or _DEFAULT_INDEXING_THRESHOLD_KB
        self._set_indexing_threshold(0)
        return restore

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
        # Only the metadata sub-document is fetched: chunk text is by far the largest part
        # of each payload and a full scroll of it would not fit on a small query host.
        return _summarize_sources(self._scroll_metadata())

    def _scroll_metadata(self) -> Iterator[dict[str, Any]]:
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.settings.qdrant_collection,
                limit=1024,
                offset=offset,
                with_payload=["metadata"],
                with_vectors=False,
            )
            for point in points:
                yield dict((point.payload or {}).get("metadata") or {})
            if offset is None:
                break

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


def _qdrant_point(
    settings: Settings, chunk: Chunk, dense_vector: list[float], embedding_model: str
) -> Any:
    models = _qdrant_models()
    return models.PointStruct(
        id=_point_id(chunk.id),
        vector={settings.qdrant_dense_vector_name: dense_vector},
        payload={
            "chunk_id": chunk.id,
            "text": chunk.text,
            # Chunk ids only hash the first 120 characters of text, so the full-text hash is
            # what lets ingestion tell "unchanged" from "changed past the id prefix".
            "text_sha256": _text_sha256(chunk.text),
            "metadata": chunk.metadata,
            "embedding_model": embedding_model,
        },
    )


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
