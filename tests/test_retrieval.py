from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from medical_rag.bm25 import BM25Index, _tokenize
from medical_rag.config import Settings
from medical_rag.embeddings import HashingEmbeddingModel
from medical_rag.pipeline import StrokeRAG
from medical_rag.types import Chunk
from medical_rag.vector_store import VectorStore


def make_chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        metadata={"source_id": "test.txt", "source_path": "/tmp/test.txt", "title": "Test", "page": 1},
    )


class TestBM25Index:
    def test_build_and_search_returns_relevant_chunk(self):
        chunks = [
            make_chunk("c1", "anticoagulation warfarin atrial fibrillation reduces recurrent stroke"),
            make_chunk("c2", "blood pressure hypertension secondary prevention medication"),
            make_chunk("c3", "rehabilitation physiotherapy motor recovery upper limb"),
        ]
        idx = BM25Index.build(chunks)
        results = idx.search("atrial fibrillation anticoagulation", top_k=3)
        assert results, "BM25 should return results"
        top_id = results[0][0]
        assert top_id == "c1", f"Expected c1 on top, got {top_id}"

    def test_search_returns_empty_for_unknown_terms(self):
        chunks = [make_chunk("c1", "stroke rehabilitation exercises balance training")]
        idx = BM25Index.build(chunks)
        results = idx.search("quantum entanglement photon", top_k=5)
        assert results == []

    def test_round_trip_serialisation(self):
        chunks = [
            make_chunk("a", "aspirin antiplatelet secondary prevention stroke"),
            make_chunk("b", "tissue plasminogen activator tPA thrombolysis"),
        ]
        idx = BM25Index.build(chunks)
        restored = BM25Index.from_dict(idx.to_dict())
        original_results = idx.search("stroke prevention aspirin", top_k=2)
        restored_results = restored.search("stroke prevention aspirin", top_k=2)
        assert [r[0] for r in original_results] == [r[0] for r in restored_results]

    def test_tokenize_lowercases(self):
        assert _tokenize("Stroke RISK") == ["stroke", "risk"]

    def test_tokenize_ignores_punctuation(self):
        tokens = _tokenize("e.g., stroke (ischemic)")
        assert "stroke" in tokens
        assert "ischemic" in tokens


class TestHybridRetrieval:
    def test_hybrid_retrieval_surfaces_specific_passage(self):
        """Hybrid RRF should rank the AF-specific chunk highest."""
        chunks = [
            make_chunk(
                "af",
                "anticoagulation warfarin atrial fibrillation reduces recurrent stroke risk",
            ),
            make_chunk(
                "bp",
                "blood pressure hypertension secondary prevention lifestyle modification",
            ),
            make_chunk(
                "rehab",
                "rehabilitation physiotherapy motor recovery occupational therapy",
            ),
        ]
        embedding_model = HashingEmbeddingModel(dimensions=256)

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.json"
            store = VectorStore.build(path=index_path, chunks=chunks, embedding_model=embedding_model)
            store.save()
            loaded = VectorStore.load(index_path)

            assert loaded._bm25 is not None, "BM25 index should be persisted and loaded"

            results = loaded.search(
                "medications for recurrent stroke in atrial fibrillation",
                embedding_model=embedding_model,
                top_k=3,
                hybrid=True,
            )

        assert results, "Should return results"
        top_chunk_id = results[0].chunk.id
        assert top_chunk_id == "af", (
            f"AF-specific chunk should rank first under hybrid search, got {top_chunk_id}"
        )

    def test_bm25_persisted_in_index_json(self):
        """Saved index.json must contain a non-null 'bm25' key."""
        chunks = [make_chunk("x", "stroke ischemic thrombectomy mechanical")]
        embedding_model = HashingEmbeddingModel(dimensions=128)

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.json"
            store = VectorStore.build(path=index_path, chunks=chunks, embedding_model=embedding_model)
            store.save()

            import json
            payload = json.loads(index_path.read_text())
            assert "bm25" in payload, "index.json must contain 'bm25' key"
            assert payload["bm25"] is not None, "'bm25' value must not be null"

    def test_old_index_without_bm25_loads_as_vector_only(self):
        """An index saved without 'bm25' should load without error and fall back to vector search."""
        chunks = [make_chunk("y", "stroke prevention anticoagulation")]
        embedding_model = HashingEmbeddingModel(dimensions=128)

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.json"
            store = VectorStore.build(path=index_path, chunks=chunks, embedding_model=embedding_model)
            store.save()

            import json
            payload = json.loads(index_path.read_text())
            payload.pop("bm25", None)
            index_path.write_text(json.dumps(payload))

            loaded = VectorStore.load(index_path)
            assert loaded._bm25 is None
            results = loaded.search("stroke", embedding_model=embedding_model, top_k=1)
            assert len(results) == 1


class TestPipelineWithReranker:
    def test_pipeline_ask_includes_retrieval_mode(self, tmp_path):
        settings = Settings.from_env().with_paths(
            corpus_dir=tmp_path / "corpus",
            index_path=tmp_path / "index.json",
        )
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "test.txt").write_text(
            "Anticoagulation therapy with warfarin reduces stroke recurrence in patients "
            "with atrial fibrillation. Regular INR monitoring is required. "
            "Blood pressure control is also essential for secondary prevention of stroke.",
            encoding="utf-8",
        )

        embedding_model = HashingEmbeddingModel(dimensions=256)
        rag = StrokeRAG(settings=settings, embedding_model=embedding_model)
        rag.ingest()
        answer = rag.ask("what reduces recurrent stroke?")

        assert answer.retrieval_mode in ("vector", "hybrid")
        assert isinstance(answer.fallback_embedding, bool)

    def test_min_relevance_score_filters_results(self, tmp_path):
        settings = Settings.from_env().with_paths(
            corpus_dir=tmp_path / "corpus",
            index_path=tmp_path / "index.json",
        )
        # Use an extremely high min_relevance_score that will filter everything
        settings = Settings(
            root_dir=settings.root_dir,
            corpus_dir=settings.corpus_dir,
            index_path=settings.index_path,
            embedding_backend="hash",
            min_relevance_score=999.0,
        )
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "test.txt").write_text(
            "Stroke rehabilitation improves outcomes.",
            encoding="utf-8",
        )

        embedding_model = HashingEmbeddingModel(dimensions=256)
        rag = StrokeRAG(settings=settings, embedding_model=embedding_model)
        rag.ingest()
        answer = rag.ask("what helps stroke recovery?")
        assert answer.citations == []
