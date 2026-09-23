import pytest

from dataclasses import replace
import json

from medical_rag.config import Settings
from medical_rag.embeddings import (
    ApiEmbeddingModel,
    CachedEmbeddingModel,
    HashingEmbeddingModel,
    OllamaEmbeddingModel,
    RemoteEmbeddingModel,
    SentenceTransformersEmbeddingModel,
    make_embedding_model,
    ollama_model_name_matches,
)


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def test_hashing_embedding_scores_related_text_higher() -> None:
    model = HashingEmbeddingModel(dimensions=128)
    query, related, unrelated = model.embed(
        [
            "stroke symptoms face arm speech time",
            "face drooping arm weakness and speech difficulty are stroke symptoms",
            "weather patterns and crop yields",
        ]
    )

    assert _dot(query, related) > _dot(query, unrelated)


def test_auto_embedding_uses_ollama_when_configured_model_is_installed(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "medical_rag.embeddings.list_ollama_models",
        lambda *_args, **_kwargs: ["nomic-embed-text:latest"],
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path,
        index_path=tmp_path / "index.json",
        embedding_backend="auto",
        ollama_embedding_model="nomic-embed-text",
    )

    model, fallback = make_embedding_model(settings)

    assert isinstance(model, OllamaEmbeddingModel)
    assert fallback is False


def test_auto_embedding_falls_back_when_configured_model_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "medical_rag.embeddings.list_ollama_models",
        lambda *_args, **_kwargs: ["llama3.1:latest"],
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path,
        index_path=tmp_path / "index.json",
        embedding_backend="auto",
        ollama_embedding_model="nomic-embed-text",
    )

    model, fallback = make_embedding_model(settings)

    assert isinstance(model, HashingEmbeddingModel)
    assert fallback is True


def test_ollama_model_name_matches_latest_tag() -> None:
    assert ollama_model_name_matches("nomic-embed-text", "nomic-embed-text:latest")
    assert ollama_model_name_matches("nomic-embed-text:latest", "nomic-embed-text:latest")
    assert not ollama_model_name_matches("nomic-embed-text", "llama3.1:latest")


def test_api_embedding_model_posts_openai_compatible_request(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"data":[{"index":0,"embedding":[3,4]},'
                b'{"index":1,"embedding":[0,2]}]}'
            )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("medical_rag.embeddings.urllib.request.urlopen", fake_urlopen)
    model = ApiEmbeddingModel(
        base_url="https://api.example.test/v1",
        api_key="secret",
        model="embed-model",
        timeout_seconds=7,
    )

    vectors = model.embed(["stroke", "rehab"])

    assert seen["url"] == "https://api.example.test/v1/embeddings"
    assert seen["timeout"] == 7
    assert seen["auth"] == "Bearer secret"
    assert '"model": "embed-model"' in seen["body"]
    assert len(vectors) == 2
    assert round(_dot(vectors[0], vectors[0]), 6) == 1.0


def test_api_embedding_backend_requires_api_key(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path,
        index_path=tmp_path / "index.json",
        embedding_backend="api",
        api_key="",
    )

    try:
        make_embedding_model(settings)
    except ValueError as exc:
        assert "RAG_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected API embeddings without an API key to fail")
def test_sentence_transformers_backend_selection_is_lazy(tmp_path) -> None:
    settings = replace(
        Settings.from_env(tmp_path),
        embedding_backend="sentence-transformers",
        sentence_transformers_model="BAAI/bge-small-en-v1.5",
        sentence_transformers_device="cuda",
        sentence_transformers_batch_size=16,
        embedding_cache_path=None,
    )

    model, fallback_used = make_embedding_model(settings)

    assert fallback_used is False
    assert isinstance(model, SentenceTransformersEmbeddingModel)
    assert model.name == "sentence-transformers:BAAI/bge-small-en-v1.5"
    assert model.device == "cuda"
    assert model.batch_size == 16


def test_sentence_transformers_refuses_cuda_when_unavailable(monkeypatch) -> None:
    import sys
    import types

    from medical_rag.embeddings import SentenceTransformersEmbeddingModel

    fake_torch = types.SimpleNamespace(
        __version__="0.0-test",
        version=types.SimpleNamespace(cuda=None),
        cuda=types.SimpleNamespace(is_available=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=object))
    model = SentenceTransformersEmbeddingModel(model_name="BAAI/bge-base-en-v1.5", device="cuda")

    with pytest.raises(RuntimeError, match="no usable CUDA device"):
        model.embed(["stroke"])


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_remote_embedding_model_uses_health_and_batches_by_service_limit(monkeypatch) -> None:
    posts: list[list[str]] = []

    def fake_urlopen(request, timeout: float):  # type: ignore[no-untyped-def]
        assert timeout == 12.5
        if request.full_url == "http://embedder.test/health":
            assert request.get_method() == "GET"
            return _FakeResponse(
                {
                    "model_name": "sentence-transformers:test-model",
                    "dimensions": 3,
                    "max_batch_size": 2,
                }
            )

        assert request.full_url == "http://embedder.test/embed"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer secret"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model_name"] == "sentence-transformers:test-model"
        texts = payload["texts"]
        posts.append(texts)
        return _FakeResponse(
            {
                "model_name": "sentence-transformers:test-model",
                "dimensions": 3,
                "embeddings": [[float(len(text)), 0.0, 1.0] for text in texts],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    model = RemoteEmbeddingModel(
        base_url="http://embedder.test",
        timeout_seconds=12.5,
        batch_size=64,
        token="secret",
    )

    assert model.name == "sentence-transformers:test-model"
    embeddings = model.embed(["a", "bb", "ccc", "dddd", "eeeee"])

    assert posts == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert embeddings == [
        [1.0, 0.0, 1.0],
        [2.0, 0.0, 1.0],
        [3.0, 0.0, 1.0],
        [4.0, 0.0, 1.0],
        [5.0, 0.0, 1.0],
    ]


def test_remote_embedding_model_rejects_dimension_mismatch(monkeypatch) -> None:
    def fake_urlopen(request, timeout: float):  # type: ignore[no-untyped-def]
        if request.full_url == "http://embedder.test/health":
            return _FakeResponse(
                {
                    "model_name": "sentence-transformers:test-model",
                    "dimensions": 3,
                    "max_batch_size": 10,
                }
            )
        return _FakeResponse(
            {
                "model_name": "sentence-transformers:test-model",
                "dimensions": 3,
                "embeddings": [[1.0, 2.0]],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    model = RemoteEmbeddingModel(base_url="http://embedder.test")

    with pytest.raises(RuntimeError, match="dimension 2.*expected 3"):
        model.embed(["stroke"])


def test_remote_embedding_model_rejects_expected_model_mismatch(monkeypatch) -> None:
    def fake_urlopen(request, timeout: float):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            {
                "model_name": "sentence-transformers:actual",
                "dimensions": 3,
                "max_batch_size": 10,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    model = RemoteEmbeddingModel(
        base_url="http://embedder.test",
        expected_model_name="sentence-transformers:expected",
    )

    with pytest.raises(RuntimeError, match="sentence-transformers:expected.*sentence-transformers:actual"):
        _ = model.name


def test_make_embedding_model_builds_cached_remote_model(tmp_path) -> None:
    settings = replace(
        Settings.from_env(tmp_path),
        embedding_backend="remote",
        embedding_service_url="http://embedder.test",
        embedding_service_timeout_seconds=5.0,
        embedding_service_token="secret",
        embedding_service_expected_model="sentence-transformers:test-model",
        remote_embed_batch_size=7,
    )

    model, fallback_used = make_embedding_model(settings)

    assert fallback_used is False
    assert isinstance(model, CachedEmbeddingModel)
    assert isinstance(model.inner, RemoteEmbeddingModel)
    assert model.inner.base_url == "http://embedder.test"
    assert model.inner.timeout_seconds == 5.0
    assert model.inner.token == "secret"
    assert model.inner.expected_model_name == "sentence-transformers:test-model"
    assert model.inner.batch_size == 7
