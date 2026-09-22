from dataclasses import replace

from medical_rag.config import Settings
from medical_rag.embeddings import (
    ApiEmbeddingModel,
    HashingEmbeddingModel,
    OllamaEmbeddingModel,
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
