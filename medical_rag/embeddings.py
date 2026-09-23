from __future__ import annotations

import hashlib
import sys
import time
import json
import math
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from medical_rag.config import Settings

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*|\d+(?:\.\d+)?")


class EmbeddingModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


@dataclass
class HashingEmbeddingModel(EmbeddingModel):
    dimensions: int = 768

    @property
    def name(self) -> str:
        return f"hashing-bow-{self.dimensions}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokens(text)
        weighted_terms = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]

        for term in weighted_terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        return _normalize(vector)


@dataclass
class OllamaEmbeddingModel(EmbeddingModel):
    base_url: str
    model: str
    timeout_seconds: float = 20.0

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) == 1:
            return [self._embed_one(texts[0])]

        try:
            return self._embed_batch(texts)
        except RuntimeError:
            return [self._embed_one(text) for text in texts]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not get Ollama batch embeddings from {self.base_url}") from exc

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama batch embedding response did not include expected embeddings")
        return [_normalize([float(value) for value in embedding]) for embedding in embeddings]

    def _embed_one(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not get Ollama embedding from {self.base_url}") from exc

        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Ollama embedding response did not include an embedding list")
        return _normalize([float(value) for value in embedding])


@dataclass
class ApiEmbeddingModel(EmbeddingModel):
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 20.0

    @property
    def name(self) -> str:
        return f"api:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_api_error_message("embedding", exc)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not get API embeddings from {self.base_url}") from exc

        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise RuntimeError("API embedding response did not include expected data entries")

        indexed_items = []
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                raise RuntimeError("API embedding response included a malformed data entry")
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise RuntimeError("API embedding response did not include an embedding list")
            indexed_items.append((int(item.get("index", position)), embedding))

        indexed_items.sort(key=lambda item: item[0])
        return [_normalize([float(value) for value in embedding]) for _, embedding in indexed_items]


@dataclass
class RemoteEmbeddingModel(EmbeddingModel):
    base_url: str
    timeout_seconds: float = 60.0
    batch_size: int = 64
    token: str | None = None
    expected_model_name: str | None = None
    _model_name: str | None = field(default=None, init=False, repr=False)
    _dimensions: int | None = field(default=None, init=False, repr=False)
    _max_batch_size: int | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        self._load_health()
        assert self._model_name is not None
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model_name = self.name
        dimensions = self._dimensions
        max_batch_size = self._max_batch_size
        if dimensions is None or max_batch_size is None:
            raise RuntimeError("Embedding service health response was incomplete")

        embeddings: list[list[float]] = []
        batch_size = min(max(1, self.batch_size), max(1, max_batch_size))
        for batch in _text_batches(texts, batch_size):
            payload = json.dumps({"texts": batch, "model_name": model_name}).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/embed",
                data=payload,
                headers=self._headers(),
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise RuntimeError(self._format_http_error(exc)) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise RuntimeError(
                    f"Could not reach embedding service at {self.base_url}: {exc}"
                ) from exc

            response_model_name = data.get("model_name")
            if response_model_name != model_name:
                raise RuntimeError(
                    "Embedding service returned model_name "
                    f"{response_model_name!r}, expected {model_name!r}"
                )

            batch_embeddings = data.get("embeddings")
            if not isinstance(batch_embeddings, list) or len(batch_embeddings) != len(batch):
                raise RuntimeError(
                    "Embedding service returned "
                    f"{len(batch_embeddings) if isinstance(batch_embeddings, list) else 'invalid'} "
                    f"embeddings for a batch of {len(batch)} texts"
                )

            for index, vector in enumerate(batch_embeddings):
                if not isinstance(vector, list):
                    raise RuntimeError("Embedding service returned a non-list embedding vector")
                if len(vector) != dimensions:
                    raise RuntimeError(
                        "Embedding service returned vector with dimension "
                        f"{len(vector)} at batch index {index}, expected {dimensions}"
                    )
                embeddings.append([float(value) for value in vector])

        return embeddings

    def _load_health(self) -> None:
        if self._model_name is not None:
            return

        request = urllib.request.Request(f"{self.base_url.rstrip('/')}/health")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Could not reach embedding service at {self.base_url}: {exc}"
            ) from exc

        model_name = data.get("model_name")
        dimensions = data.get("dimensions")
        max_batch_size = data.get("max_batch_size")
        if not isinstance(model_name, str) or not isinstance(dimensions, int) or not isinstance(
            max_batch_size, int
        ):
            raise RuntimeError("Embedding service health response was incomplete")
        if self.expected_model_name is not None and model_name != self.expected_model_name:
            raise RuntimeError(
                "Embedding service model mismatch: "
                f"expected {self.expected_model_name!r}, got {model_name!r}"
            )

        self._model_name = model_name
        self._dimensions = dimensions
        self._max_batch_size = max_batch_size

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _format_http_error(self, exc: urllib.error.HTTPError) -> str:
        message = str(exc)
        try:
            data = json.loads(exc.read().decode("utf-8"))
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = error["message"]
        except Exception:
            pass
        return f"Embedding service returned HTTP {exc.code}: {message}"


@dataclass
class SentenceTransformersEmbeddingModel(EmbeddingModel):
    model_name: str
    device: str = "auto"
    batch_size: int = 64
    _model: object | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return f"sentence-transformers:{self.model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        started = time.perf_counter()
        vectors = model.encode(
            texts,
            batch_size=max(1, self.batch_size),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        encoded = time.perf_counter()
        result = vectors.tolist()
        print(
            f"sentence-transformers: encoded {len(texts)} texts "
            f"(max {max(len(t) for t in texts)} chars) in {encoded - started:.2f}s, "
            f"converted in {time.perf_counter() - encoded:.2f}s",
            file=sys.stderr,
        )
        return result

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for "
                "RAG_EMBEDDING_BACKEND=sentence-transformers"
            ) from exc

        device = None if self.device == "auto" else self.device
        if device is not None and device.startswith("cuda"):
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError(
                    f"RAG_SENTENCE_TRANSFORMERS_DEVICE={device!r} but torch {torch.__version__} "
                    f"reports no usable CUDA device (torch.version.cuda={torch.version.cuda!r}). "
                    "Check that the job has a GPU allocated and that the CUDA runtime is on the "
                    "library path, or set RAG_SENTENCE_TRANSFORMERS_DEVICE=cpu explicitly."
                )
        started = time.perf_counter()
        self._model = SentenceTransformer(self.model_name, device=device)
        print(
            f"sentence-transformers: loaded {self.model_name} on device "
            f"{self._model.device} in {time.perf_counter() - started:.1f}s",
            file=sys.stderr,
        )
        return self._model


@dataclass
class CachedEmbeddingModel(EmbeddingModel):
    """Transparent disk-backed cache wrapping any EmbeddingModel.

    Cache file format (JSON):
        {"schema_version": 1, "model_name": "...", "entries": {"<sha256>": [...]}}

    Entries are invalidated when the wrapped model's name changes.
    """

    inner: EmbeddingModel
    cache_path: Path
    batch_size: int = 64
    _cache: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._load()

    @property
    def name(self) -> str:
        return self.inner.name

    def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        misses: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cached = self._cache.get(hashlib.sha256(text.encode()).hexdigest())
            if cached is not None:
                results[i] = cached
            else:
                misses.append((i, text))

        if misses:
            profile = os.environ.get("RAG_PROFILE_EMBEDDING", "").lower() in {"1", "true", "yes"}
            profiler = None
            if profile:
                import cProfile

                profiler = cProfile.Profile()
                profiler.enable()
            embed_started = time.perf_counter()
            for batch_index, batch in enumerate(_batches(misses, max(1, self.batch_size))):
                call_started = time.perf_counter()
                new_vectors = self.inner.embed([t for _, t in batch])
                call_seconds = time.perf_counter() - call_started
                for (i, text), vector in zip(batch, new_vectors):
                    self._cache[hashlib.sha256(text.encode()).hexdigest()] = vector
                    results[i] = vector
                if profile:
                    print(
                        f"embedding cache: batch {batch_index} of {len(batch)} texts: "
                        f"inner.embed wall {call_seconds:.2f}s, "
                        f"bookkeeping {time.perf_counter() - call_started - call_seconds:.3f}s",
                        file=sys.stderr,
                    )
            save_started = time.perf_counter()
            if profiler is not None:
                import io
                import pstats

                profiler.disable()
                stream = io.StringIO()
                pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(30)
                print("embedding cache: profile (top 30 by cumulative time)", file=sys.stderr)
                print(stream.getvalue(), file=sys.stderr)
            self._save()
            print(
                f"embedding cache: {len(misses)} misses / {len(texts)} texts embedded in "
                f"batches of {max(1, self.batch_size)} in {save_started - embed_started:.2f}s, "
                f"cache saved to {self.cache_path} in "
                f"{time.perf_counter() - save_started:.2f}s",
                file=sys.stderr,
            )

        return results  # type: ignore[return-value]

    def _load(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload.get("model_name") != self.inner.name:
                return  # model changed → stale, ignore
            self._cache = payload.get("entries", {})
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "model_name": self.inner.name,
            "entries": self._cache,
        }
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")


def _ollama_available(base_url: str, timeout: float = 2.0) -> bool:
    """Probe Ollama /api/tags endpoint; return True if reachable."""
    return bool(list_ollama_models(base_url, timeout=timeout))


def list_ollama_models(base_url: str, timeout: float = 2.0) -> list[str]:
    """Return installed Ollama model names, or an empty list when Ollama is unreachable."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{base_url.rstrip('/')}/api/tags"),
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                return []
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    models = data.get("models", [])
    if not isinstance(models, list):
        return []

    names = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def ollama_model_name_matches(configured: str, available: str) -> bool:
    if configured == available:
        return True
    if ":" not in configured and available == f"{configured}:latest":
        return True
    return False


def ollama_model_available(base_url: str, model: str, timeout: float = 2.0) -> bool:
    return any(
        ollama_model_name_matches(model, available)
        for available in list_ollama_models(base_url, timeout)
    )


def make_embedding_model(settings: Settings) -> tuple[EmbeddingModel, bool]:
    """Return (model, fallback_used).

    fallback_used is True when backend="auto" and Ollama was unreachable,
    causing automatic fallback to the hash backend.
    """
    backend = settings.embedding_backend
    fallback_used = False

    if backend == "auto":
        if ollama_model_available(settings.ollama_base_url, settings.ollama_embedding_model):
            backend = "ollama"
        else:
            backend = "hash"
            fallback_used = True

    if backend == "hash":
        inner: EmbeddingModel = HashingEmbeddingModel(dimensions=settings.hash_embedding_dimensions)
    elif backend == "ollama":
        inner = OllamaEmbeddingModel(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            timeout_seconds=settings.request_timeout_seconds,
        )
    elif backend == "api":
        if not settings.api_key:
            raise ValueError("RAG_API_KEY or OPENAI_API_KEY is required for API embeddings")
        inner = ApiEmbeddingModel(
            base_url=settings.api_base_url,
            api_key=settings.api_key,
            model=settings.api_embedding_model,
            timeout_seconds=settings.request_timeout_seconds,
        )
    elif backend in {"sentence-transformers", "sentence_transformers", "st"}:
        inner = SentenceTransformersEmbeddingModel(
            model_name=settings.sentence_transformers_model,
            device=settings.sentence_transformers_device,
            batch_size=settings.sentence_transformers_batch_size,
        )
    elif backend == "remote":
        inner = RemoteEmbeddingModel(
            base_url=settings.embedding_service_url,
            timeout_seconds=settings.embedding_service_timeout_seconds,
            batch_size=settings.remote_embed_batch_size,
            token=settings.embedding_service_token,
            expected_model_name=settings.embedding_service_expected_model,
        )
    else:
        raise ValueError(f"Unsupported embedding backend: {backend!r}")

    if settings.embedding_cache_path is not None:
        return (
            CachedEmbeddingModel(
                inner=inner,
                cache_path=settings.embedding_cache_path,
                batch_size=settings.embedding_batch_size,
            ),
            fallback_used,
        )
    return inner, fallback_used


def _batches(items: list[tuple[int, str]], batch_size: int) -> list[list[tuple[int, str]]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _text_batches(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _api_error_message(operation: str, exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        message = (payload.get("error") or {}).get("message")
        if isinstance(message, str) and message:
            detail = f": {message}"
    except Exception:
        detail = ""
    return f"Could not get API {operation} response from provider ({exc.code}){detail}"
