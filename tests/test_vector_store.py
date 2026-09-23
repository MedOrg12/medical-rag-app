import dataclasses

import pytest

from medical_rag.config import Settings
from medical_rag.embeddings import HashingEmbeddingModel
from medical_rag.types import Chunk
from medical_rag.vector_store import QdrantVectorStore, VectorStore


def test_vector_store_round_trips_and_searches(tmp_path) -> None:
    chunks = [
        Chunk(
            id="stroke",
            text="FAST stroke symptoms include face drooping, arm weakness, and speech difficulty.",
            metadata={"source_id": "stroke.txt", "page": 1, "title": "Stroke"},
        ),
        Chunk(
            id="unrelated",
            text="Hypertension is a chronic cardiovascular risk factor.",
            metadata={"source_id": "risk.txt", "page": 1, "title": "Risk"},
        ),
    ]
    model = HashingEmbeddingModel(dimensions=128)
    path = tmp_path / "index.json"

    store = VectorStore.build(path=path, chunks=chunks, embedding_model=model)
    store.save()
    loaded = VectorStore.load(path)
    results = loaded.search("stroke face arm speech symptoms", model, top_k=1)

    assert results[0].chunk.id == "stroke"
    assert loaded.source_summaries()[0]["chunks"] == 1


class _FakeQdrantClient:
    instances: list["_FakeQdrantClient"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, dict]] = []
        self._exists = False
        _FakeQdrantClient.instances.append(self)

    def collection_exists(self, name: str) -> bool:
        return self._exists

    def delete_collection(self, name: str, **kwargs) -> bool:
        self.calls.append(("delete_collection", kwargs))
        self._exists = False
        return True

    def create_collection(self, **kwargs) -> bool:
        self.calls.append(("create_collection", kwargs))
        self._exists = True
        return True

    def upsert(self, **kwargs) -> None:
        self.calls.append(("upsert", kwargs))


def test_qdrant_store_uses_configured_timeout(monkeypatch, tmp_path) -> None:
    pytest.importorskip("qdrant_client")
    import qdrant_client

    _FakeQdrantClient.instances.clear()
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrantClient)
    settings = dataclasses.replace(
        Settings.from_env(tmp_path),
        qdrant_timeout_seconds=90.2,
        qdrant_url="http://qdrant.test:6333",
    )
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    store.save()

    assert _FakeQdrantClient.instances, "QdrantClient was never constructed"
    for client in _FakeQdrantClient.instances:
        assert client.kwargs["timeout"] == 91
        assert client.kwargs["url"] == "http://qdrant.test:6333"
    calls = [call for client in _FakeQdrantClient.instances for call in client.calls]
    create_calls = [kwargs for name, kwargs in calls if name == "create_collection"]
    assert create_calls and create_calls[0]["timeout"] == 91
    assert any(name == "upsert" for name, _ in calls)
