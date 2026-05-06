"""
Re-ranking module for improving retrieval precision.
Uses cross-encoder models or LLM-based re-ranking.
"""

from typing import Any

import ollama

from src.config import settings
from src.logger import logger


class LLMReRanker:
    """
    Re-rank retrieved chunks using LLM to assess relevance.
    Lightweight alternative to cross-encoder models.
    """

    def __init__(self, model: str = None):
        """
        Initialize the re-ranker.

        Args:
            model: Ollama model to use for re-ranking (defaults to config)
        """
        self.model = model or settings.ollama_model

    def rerank(
        self, query: str, chunks: list[dict[str, Any]], top_k: int = None
    ) -> list[dict[str, Any]]:
        """
        Re-rank chunks based on relevance to query.

        Args:
            query: User query
            chunks: List of retrieved chunks with content and metadata
            top_k: Number of top results to return

        Returns:
            Re-ranked list of chunks with rerank_score
        """
        if not chunks:
            return []

        top_k = top_k or len(chunks)

        logger.info(f"Re-ranking {len(chunks)} chunks for query: '{query[:50]}...'")

        # Score each chunk
        for i, chunk in enumerate(chunks):
            try:
                relevance_score = self._score_relevance(query, chunk["content"])
                chunk["rerank_score"] = relevance_score

                # Combine with original similarity (weighted average)
                original_score = chunk.get("similarity", 0.5)
                chunk["combined_score"] = (
                    relevance_score * 0.6  # LLM relevance weight
                    + original_score * 0.4  # Vector similarity weight
                )

            except Exception as e:
                logger.warning(f"Error re-ranking chunk {i}: {e}")
                chunk["rerank_score"] = chunk.get("similarity", 0.0)
                chunk["combined_score"] = chunk.get("similarity", 0.0)

        # Sort by combined score
        reranked = sorted(chunks, key=lambda x: x["combined_score"], reverse=True)

        logger.info(f"Re-ranking completed, returning top {top_k} results")
        return reranked[:top_k]

    def _score_relevance(self, query: str, content: str, max_content_length: int = None) -> float:
        """
        Score relevance of content to query using LLM.

        Args:
            query: User query
            content: Chunk content
            max_content_length: Maximum content length to send to LLM (uses config default if None)

        Returns:
            Relevance score between 0 and 1
        """
        # Use configured truncation length if not specified
        if max_content_length is None:
            max_content_length = settings.rerank_chunk_truncation

        # Truncate content if too long
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."

        prompt = f"""Rate how relevant this text is to answering the query.
Respond with ONLY a number between 0 and 1, where:
- 0 = completely irrelevant
- 0.5 = somewhat relevant
- 1 = highly relevant

Query: {query}

Text: {content}

Relevance score (0-1):"""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0},  # Deterministic scoring
            )

            # Extract score from response
            score_text = response["message"]["content"].strip()

            # Try to parse as float
            score = float(score_text)

            # Clamp to [0, 1]
            score = max(0.0, min(1.0, score))

            return score

        except Exception as e:
            logger.warning(
                f"Error scoring relevance: {e}, "
                f"using default score {settings.default_relevance_score}"
            )
            return settings.default_relevance_score


class SimpleReRanker:
    """
    Lightweight re-ranker using keyword matching and position.
    Fast alternative when LLM re-ranking is too slow.
    """

    def rerank(
        self, query: str, chunks: list[dict[str, Any]], top_k: int = None
    ) -> list[dict[str, Any]]:
        """
        Re-rank using keyword matching and other heuristics.

        Args:
            query: User query
            chunks: Retrieved chunks
            top_k: Number of results to return

        Returns:
            Re-ranked chunks
        """
        if not chunks:
            return []

        top_k = top_k or len(chunks)
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        for chunk in chunks:
            content_lower = chunk["content"].lower()

            # Keyword matching score
            matched = sum(1 for term in query_terms if term in content_lower)
            keyword_score = matched / len(query_terms) if query_terms else 0

            # Exact phrase matching (bonus)
            phrase_bonus = 0.2 if query_lower in content_lower else 0

            # Position of first match (earlier is better)
            position_score = 0
            for term in query_terms:
                if term in content_lower:
                    pos = content_lower.index(term)
                    # Normalize by content length, invert (earlier = higher score)
                    position_score = max(position_score, 1 - (pos / len(content_lower)))

            # Combine scores
            original_score = chunk.get("similarity", 0.5)
            chunk["rerank_score"] = (
                keyword_score * 0.4 + phrase_bonus + position_score * 0.2 + original_score * 0.4
            )

        # Sort by rerank score
        reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)

        logger.info(f"Simple re-ranking completed for {len(chunks)} chunks")
        return reranked[:top_k]


if __name__ == "__main__":
    # Test re-ranking
    test_chunks = [
        {
            "content": "Stroke is caused by various risk factors including hypertension.",
            "similarity": 0.75,
        },
        {
            "content": "The weather today is sunny and warm.",
            "similarity": 0.80,  # High similarity but irrelevant
        },
        {
            "content": "Hypertension is the primary risk factor for stroke in adults.",
            "similarity": 0.70,
        },
    ]

    # Test LLM re-ranker
    llm_reranker = LLMReRanker()
    results = llm_reranker.rerank("What are stroke risk factors?", test_chunks)

    print("\nLLM Re-ranking Results:")
    for i, chunk in enumerate(results, 1):
        print(f"{i}. Score: {chunk['combined_score']:.3f} - {chunk['content'][:50]}...")

    # Test simple re-ranker
    simple_reranker = SimpleReRanker()
    results = simple_reranker.rerank("What are stroke risk factors?", test_chunks)

    print("\nSimple Re-ranking Results:")
    for i, chunk in enumerate(results, 1):
        print(f"{i}. Score: {chunk['rerank_score']:.3f} - {chunk['content'][:50]}...")
