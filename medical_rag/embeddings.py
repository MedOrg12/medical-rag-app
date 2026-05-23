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
        return [self._embed_one(text) for text in texts]

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
class CachedEmbeddingModel(EmbeddingModel):
    """Transparent disk-backed cache wrapping any EmbeddingModel.

    Cache file format (JSON):
        {"schema_version": 1, "model_name": "...", "entries": {"<sha256>": [...]}}

    Entries are invalidated when the wrapped model's name changes.
    """

    inner: EmbeddingModel
    cache_path: Path
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
            new_vectors = self.inner.embed([t for _, t in misses])
            for (i, text), vector in zip(misses, new_vectors):
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


def make_embedding_model(settings: Settings) -> EmbeddingModel:
    if settings.embedding_backend == "hash":
        inner: EmbeddingModel = HashingEmbeddingModel(dimensions=settings.hash_embedding_dimensions)
    elif settings.embedding_backend == "ollama":
        inner = OllamaEmbeddingModel(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            timeout_seconds=settings.request_timeout_seconds,
        )
    else:
        raise ValueError(f"Unsupported embedding backend: {settings.embedding_backend}")

    if settings.embedding_cache_path is not None:
        return CachedEmbeddingModel(inner=inner, cache_path=settings.embedding_cache_path)
    return inner


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
