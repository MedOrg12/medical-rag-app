from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from medical_rag.bm25 import BM25Index
from medical_rag.config import Settings
from medical_rag.embeddings import EmbeddingModel
from medical_rag.types import Chunk, SearchResult

SCHEMA_VERSION = 1


class VectorStoreBackend(Protocol):
    @property
    def chunks(self) -> list[Chunk]:
        ...

    @property
    def retrieval_mode(self) -> str:
        ...

    def save(self) -> None:
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


def build_vector_store(
    settings: Settings, chunks: list[Chunk], embedding_model: EmbeddingModel
) -> VectorStoreBackend:
    if settings.vector_store_backend == "json":
        return VectorStore.build(path=settings.index_path, chunks=chunks, embedding_model=embedding_model)
    if settings.vector_store_backend == "qdrant":
        return QdrantVectorStore.build(settings=settings, chunks=chunks, embedding_model=embedding_model)
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

    @classmethod
    def build(cls, path: Path, chunks: list[Chunk], embedding_model: EmbeddingModel) -> "VectorStore":
        vectors = embedding_model.embed([chunk.text for chunk in chunks])
        bm25 = BM25Index.build(chunks)
        return cls(path=path, chunks=chunks, vectors=vectors, embedding_model=embedding_model.name, bm25=bm25)

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
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
        summaries: dict[str, dict[str, Any]] = {}
        for chunk in self.chunks:
            source_id = chunk.metadata.get("source_id", "unknown")
            entry = summaries.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "title": chunk.metadata.get("title", source_id),
                    "source_path": chunk.metadata.get("source_path"),
                    "chunks": 0,
                    "pages": set(),
                },
            )
            entry["chunks"] += 1
            if chunk.metadata.get("page") is not None:
                entry["pages"].add(chunk.metadata["page"])

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
    def __init__(
        self,
        settings: Settings,
        embedding_model_name: str | None = None,
        chunks: list[Chunk] | None = None,
        vectors: list[list[float]] | None = None,
    ) -> None:
        self.settings = settings
        self.embedding_model = embedding_model_name
        self._chunks = chunks
        self._vectors = vectors

    @property
    def chunks(self) -> list[Chunk]:
        if self._chunks is None:
            self._chunks = self._scroll_chunks()
        return self._chunks

    @property
    def retrieval_mode(self) -> str:
        return "vector"

    @classmethod
    def build(
        cls, settings: Settings, chunks: list[Chunk], embedding_model: EmbeddingModel
    ) -> "QdrantVectorStore":
        vectors = embedding_model.embed([chunk.text for chunk in chunks])
        return cls(settings, embedding_model_name=embedding_model.name, chunks=chunks, vectors=vectors)

    @classmethod
    def load(cls, settings: Settings) -> "QdrantVectorStore":
        if not cls.collection_exists(settings):
            raise FileNotFoundError(f"Qdrant collection does not exist: {settings.qdrant_collection}")
        return cls(settings)

    @classmethod
    def collection_exists(cls, settings: Settings) -> bool:
        try:
            return bool(_qdrant_client(settings).collection_exists(settings.qdrant_collection))
        except Exception:
            return False

    def save(self) -> None:
        if self._chunks is None or self._vectors is None:
            return
        if not self._chunks:
            return

        self._ensure_collection(len(self._vectors[0]))
        client = _qdrant_client(self.settings)
        points = [
            _qdrant_point(
                settings=self.settings,
                chunk=chunk,
                dense_vector=vector,
                embedding_model=self.embedding_model or "",
            )
            for chunk, vector in zip(self._chunks, self._vectors)
        ]
        batch_size = max(1, self.settings.qdrant_batch_size)
        for start in range(0, len(points), batch_size):
            client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=points[start : start + batch_size],
            )

    def search(
        self,
        query: str,
        embedding_model: EmbeddingModel,
        top_k: int,
        filters: dict[str, Any] | None = None,
        hybrid: bool = True,
    ) -> list[SearchResult]:
        client = _qdrant_client(self.settings)
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
        summaries: dict[str, dict[str, Any]] = {}
        for chunk in self.chunks:
            source_id = chunk.metadata.get("source_id", "unknown")
            entry = summaries.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "title": chunk.metadata.get("title", source_id),
                    "source_path": chunk.metadata.get("source_path"),
                    "chunks": 0,
                    "pages": set(),
                },
            )
            entry["chunks"] += 1
            if chunk.metadata.get("page") is not None:
                entry["pages"].add(chunk.metadata["page"])

        results = []
        for entry in summaries.values():
            pages = sorted(entry.pop("pages"))
            entry["pages"] = pages
            results.append(entry)
        return sorted(results, key=lambda item: str(item["source_id"]).lower())

    def _ensure_collection(self, vector_size: int) -> None:
        client = _qdrant_client(self.settings)
        models = _qdrant_models()
        timeout = _qdrant_timeout(self.settings)
        if self.settings.qdrant_recreate_collection and client.collection_exists(
            self.settings.qdrant_collection
        ):
            client.delete_collection(self.settings.qdrant_collection, timeout=timeout)
        if not client.collection_exists(self.settings.qdrant_collection):
            client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config={
                    self.settings.qdrant_dense_vector_name: models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                timeout=timeout,
            )

    def _scroll_chunks(self) -> list[Chunk]:
        client = _qdrant_client(self.settings)
        chunks: list[Chunk] = []
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=self.settings.qdrant_collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            chunks.extend(_chunk_from_payload(point.payload or {}) for point in points)
            if offset is None:
                break
        return chunks


def _qdrant_client(settings: Settings) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError("qdrant-client is required for RAG_VECTOR_STORE=qdrant") from exc

    # qdrant-client defaults to a 5 second REST timeout. Collection creation on the shared
    # Qdrant service regularly takes longer than that, so use the configured timeout instead.
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=_qdrant_timeout(settings),
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
            "metadata": chunk.metadata,
            "embedding_model": embedding_model,
        },
    )


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


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
