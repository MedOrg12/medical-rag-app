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
    # Every call across all clients, in order; ingestion upserts through its own client.
    log: list[tuple[str, dict]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, dict]] = []
        _FakeQdrantClient.instances.append(self)

    def _record(self, name: str, kwargs: dict) -> None:
        self.calls.append((name, kwargs))
        _FakeQdrantClient.log.append((name, kwargs))

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
        optimizer_config = SimpleNamespace(
            indexing_threshold=self._collection.get("indexing_threshold", 10000)
        )
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=vectors), optimizer_config=optimizer_config
            )
        )

    def close(self) -> None:
        self._record("close", {})

    def update_collection(self, **kwargs) -> bool:
        self._record("update_collection", kwargs)
        assert self._collection is not None
        self._collection["indexing_threshold"] = kwargs["optimizers_config"].indexing_threshold
        return True

    def delete_collection(self, name: str, **kwargs) -> bool:
        self._record("delete_collection", kwargs)
        _FakeQdrantClient.existing = None
        return True

    def create_collection(self, **kwargs) -> bool:
        self._record("create_collection", kwargs)
        _FakeQdrantClient.existing = {
            "vectors": {name: params.size for name, params in kwargs["vectors_config"].items()},
            "points": {},
        }
        return True

    def upsert(self, **kwargs) -> None:
        self._record("upsert", kwargs)
        assert self._collection is not None
        for point in kwargs["points"]:
            self._collection["points"][point.id] = point

    def retrieve(self, **kwargs):
        from types import SimpleNamespace

        self._record("retrieve", kwargs)
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

        self._record("scroll", kwargs)
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
        self._record("delete", kwargs)
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
    _FakeQdrantClient.log.clear()
    _FakeQdrantClient.existing = existing
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrantClient)


def _calls() -> list[tuple[str, dict]]:
    return list(_FakeQdrantClient.log)


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


def test_qdrant_ingest_only_waits_on_the_final_upsert(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]

    _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks)

    upserts = [kwargs for name, kwargs in _calls() if name == "upsert"]
    assert [call["wait"] for call in upserts] == [False, False, True]


def test_qdrant_ingest_waits_periodically_to_bound_the_server_backlog(
    monkeypatch, tmp_path
) -> None:
    import medical_rag.vector_store as vector_store

    _use_fake_qdrant(monkeypatch)
    monkeypatch.setattr(vector_store, "_UPSERTS_PER_WAIT", 2)

    _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), _many_chunks(10))

    upserts = [kwargs for name, kwargs in _calls() if name == "upsert"]
    assert [call["wait"] for call in upserts] == [False, True, False, True, True]


def test_qdrant_ingest_embeds_next_batch_while_previous_upsert_is_in_flight(
    monkeypatch, tmp_path
) -> None:
    import threading

    _use_fake_qdrant(monkeypatch)
    first_upsert_started = threading.Event()
    release_upserts = threading.Event()
    embedded_during_upsert: list[str] = []
    original_upsert = _FakeQdrantClient.upsert

    def slow_upsert(self, **kwargs) -> None:
        first_upsert_started.set()
        assert release_upserts.wait(timeout=5), "embedding never overlapped the upsert"
        original_upsert(self, **kwargs)

    class _OverlapModel(_CountingModel):
        def embed(self, texts: list[str]) -> list[list[float]]:
            if first_upsert_started.is_set():
                embedded_during_upsert.extend(texts)
                release_upserts.set()
            return super().embed(texts)

    monkeypatch.setattr(_FakeQdrantClient, "upsert", slow_upsert)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(6)]

    _, stats = _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks, _OverlapModel())

    assert embedded_during_upsert == ["chunk 4", "chunk 5"]
    assert stats.chunks_embedded == 6
    assert len(_FakeQdrantClient.existing["points"]) == 6


def test_qdrant_ingest_surfaces_background_upsert_failures(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)

    def failing_upsert(self, **kwargs) -> None:
        raise ConnectionError("qdrant went away")

    monkeypatch.setattr(_FakeQdrantClient, "upsert", failing_upsert)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]

    with pytest.raises(ConnectionError, match="qdrant went away"):
        _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks)


def test_qdrant_ingest_fails_when_async_writes_did_not_land(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    original_upsert = _FakeQdrantClient.upsert

    def lossy_upsert(self, **kwargs) -> None:
        # Acknowledged but never applied, as a wait=False upsert can be on the server.
        if kwargs["wait"]:
            original_upsert(self, **kwargs)

    monkeypatch.setattr(_FakeQdrantClient, "upsert", lossy_upsert)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]

    with pytest.raises(RuntimeError, match="holds 1 points after ingestion, expected 5"):
        _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks)


def _indexing_thresholds() -> list[int]:
    return [
        kwargs["optimizers_config"].indexing_threshold
        for name, kwargs in _calls()
        if name == "update_collection"
    ]


def test_qdrant_ingest_skips_reuse_lookup_for_a_collection_it_created(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]

    _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks)

    assert "retrieve" not in _call_names()


def _many_chunks(count: int = 40) -> list[Chunk]:
    # With 8-dim float32 vectors, a 1 KB indexing threshold is 32 points, so the pause
    # (at half the threshold) triggers once 16 points have been written.
    return [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(count)]


def test_qdrant_ingest_pauses_indexing_during_a_large_load_and_restores_it(
    monkeypatch, tmp_path
) -> None:
    _use_fake_qdrant(
        monkeypatch, existing={"vectors": {"dense": 8}, "points": {}, "indexing_threshold": 1}
    )

    _ingest(_qdrant_settings(tmp_path, embedding_batch_size=10), _many_chunks())

    names = _call_names()
    update_indexes = [i for i, name in enumerate(names) if name == "update_collection"]
    upsert_indexes = [i for i, name in enumerate(names) if name == "upsert"]
    assert _indexing_thresholds() == [0, 1]
    assert update_indexes[0] < upsert_indexes[0] and upsert_indexes[-1] < update_indexes[1]
    assert _FakeQdrantClient.existing["indexing_threshold"] == 1


def test_qdrant_ingest_leaves_indexing_alone_for_a_small_load(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(
        monkeypatch, existing={"vectors": {"dense": 8}, "points": {}, "indexing_threshold": 1}
    )

    _ingest(_qdrant_settings(tmp_path, embedding_batch_size=10), _many_chunks(15))

    assert "update_collection" not in _call_names()


def test_qdrant_ingest_restores_indexing_when_a_write_fails(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(
        monkeypatch, existing={"vectors": {"dense": 8}, "points": {}, "indexing_threshold": 1}
    )

    def failing_upsert(self, **kwargs) -> None:
        raise ConnectionError("qdrant went away")

    monkeypatch.setattr(_FakeQdrantClient, "upsert", failing_upsert)

    with pytest.raises(ConnectionError):
        _ingest(_qdrant_settings(tmp_path, embedding_batch_size=10), _many_chunks())

    assert _indexing_thresholds() == [0, 1]


def test_qdrant_ingest_recovers_indexing_left_paused_by_a_killed_run(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(
        monkeypatch, existing={"vectors": {"dense": 8}, "points": {}, "indexing_threshold": 0}
    )
    chunks = [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})]

    _ingest(_qdrant_settings(tmp_path), chunks)

    assert _FakeQdrantClient.existing["indexing_threshold"] == 10000


def test_qdrant_ingest_leaves_indexing_alone_when_nothing_is_written(monkeypatch, tmp_path) -> None:
    point = _fake_point("c1", "stroke", source_id="a")
    _use_fake_qdrant(monkeypatch, existing={"vectors": {"dense": 8}, "points": {point.id: point}})

    _ingest(_qdrant_settings(tmp_path), [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})])

    assert "update_collection" not in _call_names()


def test_qdrant_ingest_upserts_through_a_client_that_skips_inference_scanning(
    monkeypatch, tmp_path
) -> None:
    _use_fake_qdrant(monkeypatch)
    chunks = [Chunk(id=f"c{i}", text=f"chunk {i}", metadata={"source_id": "a"}) for i in range(5)]

    store, _ = _ingest(_qdrant_settings(tmp_path, embedding_batch_size=2), chunks)

    upserting = [
        client
        for client in _FakeQdrantClient.instances
        if any(name == "upsert" for name, _ in client.calls)
    ]
    assert len(upserting) == 1
    assert upserting[0].kwargs["cloud_inference"] is True
    assert upserting[0].calls[-1][0] == "close"
    assert store.client.kwargs["cloud_inference"] is False


def test_qdrant_client_uses_grpc_when_configured(monkeypatch, tmp_path) -> None:
    _use_fake_qdrant(monkeypatch)
    settings = _qdrant_settings(tmp_path, qdrant_prefer_grpc=True, qdrant_grpc_port=16334)

    _ingest(settings, [Chunk(id="c1", text="stroke", metadata={"source_id": "a"})])

    for client in _FakeQdrantClient.instances:
        assert client.kwargs["prefer_grpc"] is True
        assert client.kwargs["grpc_port"] == 16334


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

    query_clients = [c for c in _FakeQdrantClient.instances if not c.kwargs["cloud_inference"]]
    assert len(query_clients) == 1


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
