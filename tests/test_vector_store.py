import dataclasses

import pytest

from medical_rag.config import Settings
from medical_rag.embeddings import HashingEmbeddingModel
from medical_rag.types import Chunk
from medical_rag.vector_store import QdrantVectorStore, VectorStore, ingest_vector_store


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
    existing: dict | None = None

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

    def retrieve(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(("retrieve", kwargs))
        assert self._collection is not None
        assert kwargs["with_vectors"] is False
        keys = kwargs["with_payload"]
        records = []
        for point_id in kwargs["ids"]:
            point = self._collection["points"].get(point_id)
            if point is None:
                continue
            payload = {key: point.payload[key] for key in keys if key in point.payload}
            records.append(SimpleNamespace(id=point_id, payload=payload))
        return records

    def count(self, **kwargs):
        from types import SimpleNamespace

        assert self._collection is not None
        return SimpleNamespace(count=len(self._collection["points"]))

    def scroll(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(("scroll", kwargs))
        assert self._collection is not None
        with_payload = kwargs.get("with_payload", False)
        records = []
        for point_id, point in self._collection["points"].items():
            payload = None
            if with_payload is True:
                payload = point.payload
            elif isinstance(with_payload, list):
                payload = {key: point.payload[key] for key in with_payload if key in point.payload}
            records.append(SimpleNamespace(id=point_id, payload=payload))
        return records, None

    def delete(self, **kwargs) -> None:
        self.calls.append(("delete", kwargs))
        assert self._collection is not None
        for point_id in kwargs["points_selector"].points:
            self._collection["points"].pop(point_id, None)


class _CountingModel(HashingEmbeddingModel):
    def __init__(self, dimensions: int = 8) -> None:
        super().__init__(dimensions=dimensions)
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return super().embed(texts)


def _fake_point(chunk_id: str, text: str, model: str = "hashing-bow-8", **metadata) -> object:
    from types import SimpleNamespace

    from medical_rag.vector_store import _point_id, _text_sha256

    return SimpleNamespace(
        id=_point_id(chunk_id),
        payload={
            "chunk_id": chunk_id,
            "text": text,
            "text_sha256": _text_sha256(text),
            "metadata": metadata,
            "embedding_model": model,
        },
    )


def _qdrant_settings(tmp_path, **overrides) -> Settings:
    return dataclasses.replace(
        Settings.from_env(tmp_path),
        **{
            "vector_store_backend": "qdrant",
            "qdrant_url": "http://qdrant.test:6333",
            "embedding_batch_size": 2,
            **overrides,
        },
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


def _ingest(settings: Settings, chunks: list[Chunk], model=None):
    return ingest_vector_store(settings, chunks, model or HashingEmbeddingModel(dimensions=8))


def test_qdrant_store_uses_configured_timeout(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    settings = _qdrant_settings(tmp_path, qdrant_timeout_seconds=90.2)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]

    _ingest(settings, chunks)

    assert _FakeQdrantClient.instances, "QdrantClient was never constructed"
    for client in _FakeQdrantClient.instances:
        assert client.kwargs["timeout"] == 91
        assert client.kwargs["url"] == "http://qdrant.test:6333"
    create_calls = [kwargs for name, kwargs in _calls() if name == "create_collection"]
    assert create_calls and create_calls[0]["timeout"] == 91
    assert "upsert" in _call_names()


def test_qdrant_ingest_streams_in_batches_and_reports_counts(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    settings = _qdrant_settings(tmp_path, embedding_batch_size=2)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]
    model = _CountingModel()

    store, stats = _ingest(settings, chunks, model)

    upserts = [kwargs for name, kwargs in _calls() if name == "upsert"]
    assert [len(call["points"]) for call in upserts] == [2, 2, 1]
    assert model.embedded == [f"chunk {i}" for i in range(5)]
    assert stats.chunks_total == 5
    assert stats.chunks_embedded == 5
    assert stats.chunks_reused == 0
    assert stats.stale_points_removed == 0
    assert store.chunk_count() == 5
    stored = _FakeQdrantClient.existing["points"]
    assert all("text_sha256" in point.payload for point in stored.values())


def test_qdrant_ingest_reuses_unchanged_points_and_removes_stale_ones(monkeypatch, tmp_path) -> None:
    from medical_rag.vector_store import _point_id

    kept = _fake_point("kept", "stroke symptoms", source_id="a")
    stale = _fake_point("old-chunk", "gone", source_id="z")
    _use_fake_qdrant(
        monkeypatch,
        existing={"vectors": {"dense": 8}, "points": {kept.id: kept, stale.id: stale}},
    )
    settings = _qdrant_settings(tmp_path)  # recreate defaults to False
    chunks = [
        Chunk(id="kept", text="stroke symptoms", metadata={"source_id": "a"}),
        Chunk(id="new", text="new guidance", metadata={"source_id": "b"}),
    ]
    model = _CountingModel()

    _, stats = _ingest(settings, chunks, model)

    names = _call_names()
    assert "create_collection" not in names
    assert "delete_collection" not in names
    assert names.index("upsert") < names.index("delete"), "stale cleanup must follow the upsert"
    assert model.embedded == ["new guidance"]
    assert stats.chunks_embedded == 1
    assert stats.chunks_reused == 1
    assert stats.stale_points_removed == 1
    assert set(_FakeQdrantClient.existing["points"]) == {kept.id, _point_id("new")}


def test_qdrant_ingest_re_embeds_when_text_or_model_changed_behind_same_id(
    monkeypatch, tmp_path
) -> None:
    text_changed = _fake_point("t", "old text", source_id="a")
    model_changed = _fake_point("m", "same text", model="other-model", source_id="a")
    _use_fake_qdrant(
        monkeypatch,
        existing={
            "vectors": {"dense": 8},
            "points": {text_changed.id: text_changed, model_changed.id: model_changed},
        },
    )
    chunks = [
        Chunk(id="t", text="new text", metadata={"source_id": "a"}),
        Chunk(id="m", text="same text", metadata={"source_id": "a"}),
    ]
    model = _CountingModel()

    _, stats = _ingest(_qdrant_settings(tmp_path), chunks, model)

    assert sorted(model.embedded) == ["new text", "same text"]
    assert stats.chunks_reused == 0
    stored = _FakeQdrantClient.existing["points"]
    assert stored[text_changed.id].payload["text"] == "new text"
    assert stored[model_changed.id].payload["embedding_model"] == "hashing-bow-8"


def test_qdrant_ingest_with_nothing_changed_does_no_embedding(monkeypatch, tmp_path) -> None:
    point = _fake_point("c1", "stroke", source_id="a")
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 8}, "points": {point.id: point}})
    model = _CountingModel()

    _, stats = _ingest(
        _qdrant_settings(tmp_path), [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})], model
    )

    assert model.embedded == []
    assert stats.chunks_reused == 1
    assert "upsert" not in _call_names()
    assert "create_collection" not in _call_names()


def test_qdrant_store_rejects_existing_collection_with_wrong_dimension(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 768}, "points": {}})
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]

    with pytest.raises(ValueError, match="768-dimensional.*8 dimensions.*RAG_QDRANT_RECREATE_COLLECTION"):
        _ingest(_qdrant_settings(tmp_path), chunks)

    assert "upsert" not in _call_names()


def test_qdrant_store_rejects_existing_collection_with_missing_vector_name(
    monkeypatch, tmp_path
) -> None:
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"other": 8}, "points": {}})
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]

    with pytest.raises(ValueError, match="no vector named 'dense'"):
        _ingest(_qdrant_settings(tmp_path), chunks)


def test_qdrant_store_recreates_collection_when_requested(monkeypatch, tmp_path) -> None:
    point = _fake_point("c1", "stroke", source_id="a")
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 768}, "points": {point.id: point}})
    settings = _qdrant_settings(tmp_path, qdrant_recreate_collection=True)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]
    model = _CountingModel()

    _, stats = _ingest(settings, chunks, model)

    names = _call_names()
    assert names.index("delete_collection") < names.index("create_collection") < names.index("upsert")
    assert "retrieve" not in names, "nothing can be reused from a dropped collection"
    assert model.embedded == ["stroke"]
    assert _FakeQdrantClient.existing["vectors"] == {"dense": 8}


def test_qdrant_source_summaries_fetch_metadata_only(monkeypatch, tmp_path) -> None:
    a1 = _fake_point("a1", "text one", source_id="a", title="A", page=1)
    a2 = _fake_point("a2", "text two", source_id="a", title="A", page=2)
    b1 = _fake_point("b1", "text three", source_id="b", title="B", page=7)
    _use_fake_qdrant(
        monkeypatch,
        existing={"vectors": {"dense": 8}, "points": {p.id: p for p in (a1, a2, b1)}},
    )

    store = QdrantVectorStore.load(_qdrant_settings(tmp_path))
    summaries = store.source_summaries()

    scrolls = [kwargs for name, kwargs in _calls() if name == "scroll"]
    assert scrolls and all(call["with_payload"] == ["metadata"] for call in scrolls)
    assert [(s["source_id"], s["chunks"], s["pages"]) for s in summaries] == [
        ("a", 2, [1, 2]),
        ("b", 1, [7]),
    ]


def test_qdrant_collection_exists_reports_unreachable_server(monkeypatch, tmp_path) -> None:
    pytest.importorskip("qdrant_client")
    import qdrant_client

    class _Unreachable:
        def __init__(self, **kwargs) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            raise ConnectionError("connection refused")

    monkeypatch.setattr(qdrant_client, "QdrantClient", _Unreachable)

    with pytest.raises(RuntimeError, match="Could not reach Qdrant at http://qdrant.test:6333"):
        QdrantVectorStore.collection_exists(_qdrant_settings(tmp_path))


def test_qdrant_store_reuses_one_client_across_calls(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]

    store, _ = _ingest(_qdrant_settings(tmp_path), chunks)
    store.chunk_count()
    store.source_summaries()

    assert len(_FakeQdrantClient.instances) == 1


def test_json_ingest_reuses_vectors_from_existing_index(tmp_path) -> None:
    path = tmp_path / "index.json"
    settings = dataclasses.replace(
        Settings.from_env(tmp_path), index_path=path, embedding_batch_size=2
    )
    chunks = [
        Chunk(id="a", text="stroke symptoms", metadata={"source_id": "a"}),
        Chunk(id="b", text="arm weakness", metadata={"source_id": "b"}),
    ]
    first_model = _CountingModel()
    _, first = ingest_vector_store(settings, chunks, first_model)

    changed = [
        Chunk(id="a", text="stroke symptoms", metadata={"source_id": "a"}),
        Chunk(id="b", text="arm weakness and numbness", metadata={"source_id": "b"}),
        Chunk(id="c", text="speech difficulty", metadata={"source_id": "c"}),
    ]
    second_model = _CountingModel()
    store, second = ingest_vector_store(settings, changed, second_model)

    assert first.chunks_embedded == 2 and first.chunks_reused == 0
    assert second.chunks_reused == 1
    assert sorted(second_model.embedded) == ["arm weakness and numbness", "speech difficulty"]
    assert store.chunk_count() == 3
    reloaded = VectorStore.load(path)
    assert len(reloaded.vectors) == 3
    assert reloaded.search("speech", HashingEmbeddingModel(dimensions=8), top_k=1)[0].chunk.id == "c"
