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
    # Class-level so tests can seed a pre-existing collection before the store constructs clients.
    existing: dict[str, dict] | None = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, dict]] = []
        _FakeQdrantClient.instances.append(self)

    @property
    def _collection(self) -> dict | None:
        return _FakeQdrantClient.existing

    def collection_exists(self, name: str) -> bool:
        return self._collection is not None

    def get_collection(self, name: str):
        from types import SimpleNamespace

        assert self._collection is not None
        vectors = {
            vector_name: SimpleNamespace(size=size)
            for vector_name, size in self._collection["vectors"].items()
        }
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))

    def delete_collection(self, name: str, **kwargs) -> bool:
        self.calls.append(("delete_collection", kwargs))
        _FakeQdrantClient.existing = None
        return True

    def create_collection(self, **kwargs) -> bool:
        self.calls.append(("create_collection", kwargs))
        _FakeQdrantClient.existing = {
            "vectors": {name: params.size for name, params in kwargs["vectors_config"].items()},
            "points": {},
        }
        return True

    def upsert(self, **kwargs) -> None:
        self.calls.append(("upsert", kwargs))
        assert self._collection is not None
        for point in kwargs["points"]:
            self._collection["points"][point.id] = point

    def scroll(self, **kwargs):
        from types import SimpleNamespace

        assert self._collection is not None
        return [SimpleNamespace(id=point_id) for point_id in self._collection["points"]], None

    def delete(self, **kwargs) -> None:
        self.calls.append(("delete", kwargs))
        assert self._collection is not None
        for point_id in kwargs["points_selector"].points:
            self._collection["points"].pop(point_id, None)


def _qdrant_settings(tmp_path, **overrides) -> Settings:
    return dataclasses.replace(
        Settings.from_env(tmp_path),
        qdrant_url="http://qdrant.test:6333",
        **overrides,
    )


def _use_fake_qdrant(monkeypatch, existing: dict | None = None) -> None:
    pytest.importorskip("qdrant_client")
    import qdrant_client

    _FakeQdrantClient.instances.clear()
    _FakeQdrantClient.existing = existing
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrantClient)


def _calls() -> list[tuple[str, dict]]:
    return [call for client in _FakeQdrantClient.instances for call in client.calls]


def _call_names() -> list[str]:
    return [name for name, _ in _calls()]


def test_qdrant_store_uses_configured_timeout(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    settings = _qdrant_settings(tmp_path, qdrant_timeout_seconds=90.2)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    store.save()

    assert _FakeQdrantClient.instances, "QdrantClient was never constructed"
    for client in _FakeQdrantClient.instances:
        assert client.kwargs["timeout"] == 91
        assert client.kwargs["url"] == "http://qdrant.test:6333"
    create_calls = [kwargs for name, kwargs in _calls() if name == "create_collection"]
    assert create_calls and create_calls[0]["timeout"] == 91
    assert "upsert" in _call_names()


def test_qdrant_store_upserts_into_existing_collection_and_removes_stale_points(
    monkeypatch, tmp_path
) -> None:
    from medical_rag.vector_store import _point_id

    stale_id = _point_id("old-chunk")
    kept_id = _point_id("kept")
    _use_fake_qdrant(
        monkeypatch,
        existing={"vectors": {"dense": 8}, "points": {stale_id: object(), kept_id: object()}},
    )
    settings = _qdrant_settings(tmp_path)  # recreate defaults to False
    chunks = [
        Chunk(id="kept", text="stroke symptoms", metadata={"source_id": "a"}),
        Chunk(id="new", text="new guidance", metadata={"source_id": "b"}),
    ]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    store.save()

    names = _call_names()
    assert "create_collection" not in names
    assert "delete_collection" not in names
    assert names.index("upsert") < names.index("delete"), "stale cleanup must follow the upsert"
    assert set(_FakeQdrantClient.existing["points"]) == {kept_id, _point_id("new")}


def test_qdrant_store_rejects_existing_collection_with_wrong_dimension(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 768}, "points": {}})
    settings = _qdrant_settings(tmp_path)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    with pytest.raises(ValueError, match="768-dimensional.*8 dimensions.*RAG_QDRANT_RECREATE_COLLECTION"):
        store.save()

    assert "upsert" not in _call_names()


def test_qdrant_store_rejects_existing_collection_with_missing_vector_name(
    monkeypatch, tmp_path
) -> None:
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"other": 8}, "points": {}})
    settings = _qdrant_settings(tmp_path)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    with pytest.raises(ValueError, match="no vector named 'dense'"):
        store.save()


def test_qdrant_store_recreates_collection_when_requested(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 768}, "points": {"x": object()}})
    settings = _qdrant_settings(tmp_path, qdrant_recreate_collection=True)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    store = QdrantVectorStore.build(settings, chunks, HashingEmbeddingModel(dimensions=8))

    store.save()

    names = _call_names()
    assert names.index("delete_collection") < names.index("create_collection") < names.index("upsert")
    assert _FakeQdrantClient.existing["vectors"] == {"dense": 8}
