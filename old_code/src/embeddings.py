"""
Embedding module using Ollama's nomic-embed-text model.
Provides local embeddings without external API calls.
"""

import asyncio
import logging

import httpx
import ollama
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.embedding_cache import EmbeddingCache
from src.logger import logger


class OllamaEmbeddings:
    """Wrapper for Ollama embeddings using nomic-embed-text."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        use_cache: bool = True,
    ):
        """
        Initialize Ollama embeddings.

        Args:
            model: Embedding model name (defaults to config)
            base_url: Ollama server URL (defaults to config)
            timeout: Request timeout in seconds
            use_cache: Whether to use embedding cache
        """
        self.model = model or settings.ollama_embedding_model
        self.base_url = base_url or settings.ollama_base_url
        self.timeout = timeout

        # Initialize Ollama client with correct host
        self.ollama_client = ollama.Client(host=self.base_url)

        # Initialize cache
        self.use_cache = use_cache
        if use_cache:
            self.cache = EmbeddingCache()
            logger.debug("Embedding cache enabled")
        else:
            self.cache = None
            logger.info("Embedding cache disabled")

        # Test connection to Ollama
        self._check_ollama_connection()
        self._ensure_model_available()

    def _check_ollama_connection(self) -> None:
        """Check if Ollama is running and accessible."""
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=settings.connection_timeout)
            response.raise_for_status()
            logger.debug(f"Successfully connected to Ollama at {self.base_url}")
        except httpx.ConnectError:
            logger.error(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Please ensure Ollama is running with 'ollama serve'"
            )
            raise ConnectionError(f"Ollama is not accessible at {self.base_url}")
        except Exception as e:
            logger.error(f"Error connecting to Ollama: {e}")
            raise

    def _ensure_model_available(self) -> None:
        """Check if embedding model is available, pull if needed."""
        try:
            # List available models
            response = httpx.get(f"{self.base_url}/api/tags", timeout=settings.connection_timeout)
            response.raise_for_status()
            models = response.json().get("models", [])

            model_names = [m.get("name", "").split(":")[0] for m in models]

            if self.model not in model_names and not any(
                self.model in name for name in model_names
            ):
                logger.warning(
                    f"Embedding model '{self.model}' not found locally. "
                    f"Pulling from Ollama registry... (this may take several minutes)"
                )
                # Pull the model using ollama client with correct host
                # Note: ollama.pull() doesn't support timeout parameter
                # Model downloads can take 5-15 minutes depending on size and connection
                try:
                    # Use the ollama client initialized with correct base URL
                    self.ollama_client.pull(self.model)
                    logger.info(f"Successfully pulled model '{self.model}'")
                except Exception as e:
                    logger.error(f"Failed to pull model '{self.model}': {e}")
                    raise
            else:
                logger.debug(f"Embedding model '{self.model}' is available")

        except Exception as e:
            logger.error(f"Error checking model availability: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.ConnectError, ConnectionError)
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text with caching and retry logic.

        Args:
            text: Input text to embed

        Returns:
            Embedding vector as list of floats
        """
        # Check cache first
        if self.use_cache and self.cache:
            cached = self.cache.get(text, self.model)
            if cached is not None:
                return cached

        # Generate embedding with automatic retries
        try:
            response = self.ollama_client.embeddings(model=self.model, prompt=text)
            embedding = response.get("embedding")

            if not embedding:
                raise ValueError(f"No embedding returned for text: {text[:50]}...")

            # Store in cache
            if self.use_cache and self.cache:
                self.cache.set(text, self.model, embedding)

            return embedding

        except (httpx.TimeoutException, httpx.ConnectError, ConnectionError) as e:
            logger.warning(f"Connection issue, will retry: {e}")
            raise  # Tenacity will retry
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    async def embed_text_async(self, text: str) -> list[float]:
        """
        Generate embedding for a single text asynchronously.

        Args:
            text: Input text to embed

        Returns:
            Embedding vector as list of floats
        """
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.model, "prompt": text}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                embedding = result.get("embedding")

                if not embedding:
                    raise ValueError(f"No embedding returned for text: {text[:50]}...")

                return embedding
            except Exception as e:
                logger.error(f"Error generating async embedding: {e}")
                raise

    async def embed_texts_async_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """
        Generate embeddings in parallel batches asynchronously.

        Args:
            texts: List of input texts
            batch_size: Number of concurrent requests per batch

        Returns:
            List of embedding vectors
        """
        if batch_size is None:
            batch_size = settings.embedding_batch_size

        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            try:
                # Process batch in parallel
                batch_embeddings = await asyncio.gather(
                    *[self.embed_text_async(text) for text in batch], return_exceptions=True
                )

                # Handle any exceptions in the batch
                for j, result in enumerate(batch_embeddings):
                    if isinstance(result, Exception):
                        logger.error(f"Failed to embed text in batch: {str(result)}")
                        # Use zero vector as fallback
                        all_embeddings.append([0.0] * settings.nomic_embed_dimensions)
                    else:
                        all_embeddings.append(result)

            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                # Add zero vectors for entire batch
                for _ in batch:
                    all_embeddings.append([0.0] * settings.nomic_embed_dimensions)

        return all_embeddings

    def embed_texts(self, texts: list[str], show_progress: bool = True) -> list[list[float]]:
        """
        Generate embeddings for multiple texts using async batch processing with caching.

        Args:
            texts: List of input texts
            show_progress: Whether to show progress bar

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Check cache for existing embeddings
        embeddings = [None] * len(texts)
        texts_to_generate = []
        indices_to_generate = []

        if self.use_cache and self.cache:
            cached_embeddings = self.cache.get_many(texts, self.model)

            for idx, embedding in cached_embeddings.items():
                embeddings[idx] = embedding

            # Find texts that need to be generated
            for i, emb in enumerate(embeddings):
                if emb is None:
                    texts_to_generate.append(texts[i])
                    indices_to_generate.append(i)

            cache_stats = self.cache.get_stats()
            logger.info(
                f"Cache: {len(cached_embeddings)}/{len(texts)} cached "
                f"(hit rate: {cache_stats['hit_rate_percent']}%)"
            )
        else:
            texts_to_generate = texts
            indices_to_generate = list(range(len(texts)))

        # Generate remaining embeddings
        if texts_to_generate:
            logger.info(
                f"Generating {len(texts_to_generate)} new embeddings using async batch processing..."
            )

            try:
                new_embeddings = asyncio.run(
                    self.embed_texts_async_batch(texts_to_generate)
                )

                # Place generated embeddings in correct positions
                for idx, embedding in zip(indices_to_generate, new_embeddings):
                    embeddings[idx] = embedding

                # Cache new embeddings
                if self.use_cache and self.cache:
                    self.cache.set_many(texts_to_generate, self.model, new_embeddings)

                if show_progress:
                    logger.info(f"✓ Generated {len(new_embeddings)} new embeddings")

            except Exception as e:
                logger.error(f"Async batch embedding failed, falling back to sequential: {e}")
                return self._embed_texts_sequential(texts, show_progress)
        else:
            logger.info("All embeddings retrieved from cache!")

        return embeddings

    def _embed_texts_sequential(self, texts: list[str], show_progress: bool) -> list[list[float]]:
        """
        Fallback method for sequential embedding generation.

        Args:
            texts: List of input texts
            show_progress: Whether to show progress bar

        Returns:
            List of embedding vectors
        """
        embeddings = []

        if show_progress:
            from tqdm import tqdm

            texts_iter = tqdm(texts, desc="Generating embeddings")
        else:
            texts_iter = texts

        for text in texts_iter:
            try:
                embedding = self.embed_text(text)
                embeddings.append(embedding)
            except Exception as e:
                logger.error(f"Failed to embed text: {text[:50]}... Error: {e}")
                # Return zero vector as fallback
                if embeddings:
                    embeddings.append([0.0] * len(embeddings[0]))
                else:
                    embeddings.append([0.0] * settings.nomic_embed_dimensions)

        logger.info(f"Generated {len(embeddings)} embeddings")
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a query (alias for embed_text).

        Args:
            query: Query text

        Returns:
            Embedding vector
        """
        return self.embed_text(query)


if __name__ == "__main__":
    # Test embeddings
    embedder = OllamaEmbeddings()

    test_texts = [
        "This is a test sentence about medical research.",
        "Another sentence about healthcare and treatment.",
        "Machine learning in diagnostic imaging.",
    ]

    embeddings = embedder.embed_texts(test_texts)
    print(f"Generated {len(embeddings)} embeddings")
    print(f"Embedding dimension: {len(embeddings[0])}")
    print(f"Sample embedding (first 10 values): {embeddings[0][:10]}")
