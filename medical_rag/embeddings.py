from __future__ import annotations

import hashlib
import json
import math
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
        vectors = model.encode(
            texts,
            batch_size=max(1, self.batch_size),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors.tolist()]

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
        self._model = SentenceTransformer(self.model_name, device=device)
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
            for batch in _batches(misses, max(1, self.batch_size)):
                new_vectors = self.inner.embed([t for _, t in batch])
                for (i, text), vector in zip(batch, new_vectors):
                    self._cache[hashlib.sha256(text.encode()).hexdigest()] = vector
                    results[i] = vector
            self._save()

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
