"""
Tests for embedding cache module.
"""


import pytest

from src.embedding_cache import EmbeddingCache


class TestEmbeddingCache:
    """Tests for EmbeddingCache class."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a temporary cache for testing."""
        return EmbeddingCache(cache_dir=tmp_path / "test_cache")

    def test_cache_initialization(self, cache):
        """Test cache initializes correctly."""
        assert cache.cache_dir.exists()
        assert cache.stats["hits"] == 0
        assert cache.stats["misses"] == 0

    def test_get_miss_returns_none(self, cache):
        """Test that cache miss returns None."""
        result = cache.get("test text", "test-model")
        assert result is None
        assert cache.stats["misses"] == 1

    def test_set_and_get(self, cache):
        """Test setting and getting embedding."""
        embedding = [0.1, 0.2, 0.3]
        cache.set("test text", "test-model", embedding)

        result = cache.get("test text", "test-model")
        assert result == embedding
        assert cache.stats["hits"] == 1
        assert cache.stats["saves"] == 1

    def test_different_models_different_cache(self, cache):
        """Test that different models have separate cache entries."""
        embedding1 = [0.1, 0.2, 0.3]
        embedding2 = [0.4, 0.5, 0.6]

        cache.set("test text", "model1", embedding1)
        cache.set("test text", "model2", embedding2)

        result1 = cache.get("test text", "model1")
        result2 = cache.get("test text", "model2")

        assert result1 == embedding1
        assert result2 == embedding2

    def test_memory_cache(self, cache):
        """Test that memory cache works."""
        embedding = [0.1, 0.2, 0.3]
        cache.set("test text", "test-model", embedding)

        # First get reads from disk, stores in memory
        result1 = cache.get("test text", "test-model")
        # Second get should hit memory cache
        result2 = cache.get("test text", "test-model")

        assert result1 == result2 == embedding
        assert cache.stats["hits"] == 2

    def test_get_many(self, cache):
        """Test batch retrieval."""
        texts = ["text1", "text2", "text3"]
        embeddings = [[0.1], [0.2], [0.3]]

        # Cache first and third
        cache.set(texts[0], "model", embeddings[0])
        cache.set(texts[2], "model", embeddings[2])

        results = cache.get_many(texts, "model")

        assert len(results) == 2
        assert results[0] == embeddings[0]
        assert results[2] == embeddings[2]
        assert 1 not in results

    def test_set_many(self, cache):
        """Test batch storage."""
        texts = ["text1", "text2", "text3"]
        embeddings = [[0.1], [0.2], [0.3]]

        cache.set_many(texts, "model", embeddings)

        for i, text in enumerate(texts):
            result = cache.get(text, "model")
            assert result == embeddings[i]

    def test_set_many_length_mismatch_raises_error(self, cache):
        """Test that mismatched lengths raise error."""
        with pytest.raises(ValueError, match="must have same length"):
            cache.set_many(["text1"], "model", [[0.1], [0.2]])

    def test_clear(self, cache):
        """Test clearing cache."""
        cache.set("text", "model", [0.1])
        assert cache.get("text", "model") is not None

        cache.clear()

        assert cache.get("text", "model") is None
        assert cache.stats["hits"] == 0
        assert cache.stats["saves"] == 0

    def test_get_stats(self, cache):
        """Test getting cache statistics."""
        cache.set("text1", "model", [0.1])
        cache.get("text1", "model")  # hit
        cache.get("text2", "model")  # miss

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["saves"] == 1
        assert stats["total_requests"] == 2
        assert stats["hit_rate_percent"] == 50.0

    def test_get_cache_size(self, cache):
        """Test getting cache size information."""
        cache.set("text1", "model", [0.1] * 768)
        cache.set("text2", "model", [0.2] * 768)

        size_info = cache.get_cache_size()

        assert size_info["file_count"] == 2
        assert size_info["size_mb"] > 0
        assert size_info["memory_entries"] == 2
