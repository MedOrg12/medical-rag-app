from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from medical_rag.bm25 import BM25Index
from medical_rag.embeddings import EmbeddingModel
from medical_rag.types import Chunk, SearchResult

SCHEMA_VERSION = 1


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
