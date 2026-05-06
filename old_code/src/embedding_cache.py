"""
Persistent cache for embeddings to avoid recomputing identical texts.
"""

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

from src.logger import logger


class EmbeddingCache:
    """Persistent cache for storing and retrieving embeddings."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        """
        Initialize embedding cache.

        Args:
            cache_dir: Directory to store cache files. Defaults to ./data/embedding_cache
        """
        self.cache_dir = cache_dir or Path("./data/embedding_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache for faster access during session
        self.memory_cache: dict[str, list[float]] = {}

        # Load statistics from disk (persist across instances)
        self._stats_file = self.cache_dir / "cache_stats.json"
        self.stats = self._load_stats()

        logger.debug(f"Initialized embedding cache at {self.cache_dir}")

    def _load_stats(self) -> dict[str, int]:
        """Load stats from disk, or return defaults."""
        try:
            if self._stats_file.exists():
                with open(self._stats_file) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"hits": 0, "misses": 0, "saves": 0}

    def _save_stats(self) -> None:
        """Persist stats to disk."""
        try:
            with open(self._stats_file, "w") as f:
                json.dump(self.stats, f)
        except Exception:
            pass

    def _get_cache_key(self, text: str, model: str) -> str:
        """
        Generate cache key from text and model.

        Args:
            text: Text to embed
            model: Model name

        Returns:
            SHA256 hash as cache key
        """
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """
        Get file path for cache entry.

        Args:
            cache_key: Cache key (hash)

        Returns:
            Path to cache file
        """
        # Use subdirectories to avoid too many files in one directory
        subdir = cache_key[:2]
        cache_subdir = self.cache_dir / subdir
        cache_subdir.mkdir(exist_ok=True)

        return cache_subdir / f"{cache_key}.pkl"

    def get(self, text: str, model: str) -> list[float] | None:
        """
        Retrieve embedding from cache.

        Args:
            text: Text that was embedded
            model: Model used for embedding

        Returns:
            Embedding vector if found, None otherwise
        """
        cache_key = self._get_cache_key(text, model)

        # Check memory cache first
        if cache_key in self.memory_cache:
            self.stats["hits"] += 1
            self._save_stats()
            return self.memory_cache[cache_key]

        # Check disk cache
        cache_path = self._get_cache_path(cache_key)

        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    embedding = pickle.load(f)

                # Store in memory cache
                self.memory_cache[cache_key] = embedding
                self.stats["hits"] += 1

                return embedding

            except Exception as e:
                logger.warning(f"Failed to load cache entry {cache_key}: {e}")
                # Remove corrupted cache file
                cache_path.unlink(missing_ok=True)

        self.stats["misses"] += 1
        self._save_stats()
        return None

    def set(self, text: str, model: str, embedding: list[float]) -> None:
        """
        Store embedding in cache.

        Args:
            text: Text that was embedded
            model: Model used for embedding
            embedding: Embedding vector to cache
        """
        cache_key = self._get_cache_key(text, model)

        # Store in memory cache
        self.memory_cache[cache_key] = embedding

        # Store on disk
        cache_path = self._get_cache_path(cache_key)

        try:
            with open(cache_path, "wb") as f:
                pickle.dump(embedding, f)

            self.stats["saves"] += 1
            self._save_stats()

        except Exception as e:
            logger.warning(f"Failed to save cache entry {cache_key}: {e}")

    def get_many(self, texts: list[str], model: str) -> dict[int, list[float]]:
        """
        Retrieve multiple embeddings from cache.

        Args:
            texts: List of texts
            model: Model name

        Returns:
            Dictionary mapping text index to embedding (only for cached entries)
        """
        cached = {}

        for i, text in enumerate(texts):
            embedding = self.get(text, model)
            if embedding is not None:
                cached[i] = embedding

        return cached

    def set_many(self, texts: list[str], model: str, embeddings: list[list[float]]) -> None:
        """
        Store multiple embeddings in cache.

        Args:
            texts: List of texts
            model: Model name
            embeddings: List of embedding vectors
        """
        if len(texts) != len(embeddings):
            raise ValueError("texts and embeddings must have same length")

        for text, embedding in zip(texts, embeddings):
            self.set(text, model, embedding)

    def clear(self) -> None:
        """Clear all cache entries."""
        # Clear memory cache
        self.memory_cache.clear()

        # Clear disk cache
        try:
            import shutil

            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Cache cleared")
            self.stats = {"hits": 0, "misses": 0, "saves": 0}
            self._save_stats()

        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")

    def get_stats(self) -> dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with hits, misses, and saves counts
        """
        # Re-read from disk to get latest stats (may have been updated by another instance)
        self.stats = self._load_stats()
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total * 100) if total > 0 else 0.0

        return {**self.stats, "total_requests": total, "hit_rate_percent": round(hit_rate, 2)}

    def get_cache_size(self) -> dict[str, Any]:
        """
        Get cache size information.

        Returns:
            Dictionary with size statistics
        """
        if not self.cache_dir.exists():
            return {"file_count": 0, "size_mb": 0}

        file_count = sum(1 for _ in self.cache_dir.rglob("*.pkl"))

        total_size = sum(f.stat().st_size for f in self.cache_dir.rglob("*.pkl") if f.is_file())

        size_mb = total_size / (1024 * 1024)

        return {
            "file_count": file_count,
            "size_mb": round(size_mb, 2),
            "memory_entries": len(self.memory_cache),
        }
