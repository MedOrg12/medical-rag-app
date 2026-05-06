"""
Query expansion module for improving retrieval recall.
Generates related queries and synonyms to find more relevant content.
"""


import ollama

from src.config import settings
from src.logger import logger


class QueryExpander:
    """
    Expands user queries with related terms and variations.
    """

    def __init__(self, model: str = None):
        """
        Initialize query expander.

        Args:
            model: Ollama model to use (defaults to config)
        """
        self.model = model or settings.ollama_model

        # Medical synonyms and related terms
        self.medical_synonyms = {
            "stroke": [
                "cerebrovascular accident",
                "CVA",
                "brain attack",
                "ischemic stroke",
                "hemorrhagic stroke",
            ],
            "heart attack": ["myocardial infarction", "MI", "cardiac event"],
            "high blood pressure": ["hypertension", "HTN", "elevated BP"],
            "diabetes": ["diabetes mellitus", "DM", "hyperglycemia"],
            "treatment": ["therapy", "intervention", "management", "therapeutic approach"],
            "risk factor": ["predictor", "determinant", "contributing factor"],
            "outcome": ["result", "endpoint", "prognosis", "consequence"],
            "patient": ["subject", "participant", "individual", "case"],
        }

    def expand_with_synonyms(self, query: str) -> list[str]:
        """
        Expand query with medical synonyms.

        Args:
            query: Original query

        Returns:
            List of query variations
        """
        query_lower = query.lower()
        expansions = [query]  # Include original

        # Find and replace with synonyms
        for term, synonyms in self.medical_synonyms.items():
            if term in query_lower:
                for synonym in synonyms:
                    expanded = query_lower.replace(term, synonym)
                    if expanded != query_lower:
                        expansions.append(expanded.capitalize())

        logger.info(f"Expanded query with synonyms: {len(expansions)} variations")
        return expansions[:5]  # Limit to 5

    def expand_with_llm(self, query: str, num_variations: int = 3) -> list[str]:
        """
        Generate query variations using LLM.

        Args:
            query: Original query
            num_variations: Number of variations to generate

        Returns:
            List of related queries
        """
        prompt = f"""Generate {num_variations} related medical research questions for this query:

Query: {query}

Generate questions that:
1. Use different medical terminology or synonyms
2. Focus on related aspects (causes, treatments, outcomes)
3. Are specific and answerable from research literature

Output only the questions, one per line, without numbering."""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.7},
            )

            content = response["message"]["content"].strip()

            # Parse questions (split by newlines, filter empty)
            questions = [
                q.strip().lstrip("0123456789.-) ") for q in content.split("\n") if q.strip()
            ]

            # Include original query
            all_queries = [query] + questions[:num_variations]

            logger.info(f"LLM generated {len(all_queries)-1} query variations")
            return all_queries

        except Exception as e:
            logger.warning(f"Error in LLM query expansion: {e}")
            return [query]  # Return original if expansion fails

    def expand_hybrid(self, query: str, num_llm_variations: int = 2) -> list[str]:
        """
        Combine synonym and LLM-based expansion.

        Args:
            query: Original query
            num_llm_variations: Number of LLM variations

        Returns:
            Combined list of query variations
        """
        # Get synonym expansions
        synonym_queries = self.expand_with_synonyms(query)

        # Get LLM expansions
        llm_queries = self.expand_with_llm(query, num_llm_variations)

        # Combine and deduplicate
        all_queries = list(dict.fromkeys(synonym_queries + llm_queries))

        logger.info(f"Hybrid expansion generated {len(all_queries)} total queries")
        return all_queries

    def extract_key_terms(self, query: str) -> set[str]:
        """
        Extract key medical terms from query.

        Args:
            query: User query

        Returns:
            Set of key terms
        """
        # Remove common stop words
        stop_words = {
            "what",
            "when",
            "where",
            "who",
            "why",
            "how",
            "is",
            "are",
            "was",
            "were",
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
        }

        words = query.lower().split()
        key_terms = {
            word.strip("?,.") for word in words if word.lower() not in stop_words and len(word) > 2
        }

        return key_terms


class MultiQueryRetriever:
    """
    Retrieves documents using multiple query variations.
    Aggregates and re-ranks results.
    """

    def __init__(self, expander: QueryExpander, vector_db):
        """
        Initialize multi-query retriever.

        Args:
            expander: QueryExpander instance
            vector_db: VectorDatabase instance
        """
        self.expander = expander
        self.vector_db = vector_db

    def retrieve(self, query: str, top_k: int = 5, expansion_method: str = "hybrid") -> list:
        """
        Retrieve using multiple query variations.

        Args:
            query: Original query
            top_k: Number of final results
            expansion_method: "synonym", "llm", or "hybrid"

        Returns:
            Aggregated and re-ranked results
        """
        # Expand query
        if expansion_method == "synonym":
            queries = self.expander.expand_with_synonyms(query)
        elif expansion_method == "llm":
            queries = self.expander.expand_with_llm(query)
        else:  # hybrid
            queries = self.expander.expand_hybrid(query)

        logger.info(f"Retrieving with {len(queries)} query variations")

        # Retrieve for each query variation
        all_results = {}  # chunk_id -> result with scores

        for q in queries:
            try:
                results = self.vector_db.query(q, top_k=top_k * 2)

                for result in results:
                    chunk_id = result.get("metadata", {}).get("chunk_id", "")

                    if chunk_id in all_results:
                        # Aggregate scores (max or average)
                        all_results[chunk_id]["similarity"] = max(
                            all_results[chunk_id]["similarity"], result.get("similarity", 0)
                        )
                        all_results[chunk_id]["hit_count"] += 1
                    else:
                        result["hit_count"] = 1
                        all_results[chunk_id] = result

            except Exception as e:
                logger.warning(f"Error retrieving with query '{q}': {e}")

        # Re-rank by combined score
        for chunk_id, result in all_results.items():
            # Boost chunks that match multiple query variations
            result["multi_query_score"] = (
                result["similarity"] * 0.7 + (result["hit_count"] / len(queries)) * 0.3
            )

        # Sort and return top-k
        ranked_results = sorted(
            all_results.values(), key=lambda x: x["multi_query_score"], reverse=True
        )

        logger.info(f"Multi-query retrieval returned {len(ranked_results[:top_k])} results")
        return ranked_results[:top_k]


if __name__ == "__main__":
    # Test query expansion
    expander = QueryExpander()

    test_query = "What are the risk factors for stroke?"

    print("Original Query:")
    print(f"  {test_query}\n")

    print("Synonym Expansion:")
    synonym_queries = expander.expand_with_synonyms(test_query)
    for i, q in enumerate(synonym_queries, 1):
        print(f"  {i}. {q}")

    print("\nLLM Expansion:")
    llm_queries = expander.expand_with_llm(test_query, num_variations=3)
    for i, q in enumerate(llm_queries, 1):
        print(f"  {i}. {q}")

    print("\nHybrid Expansion:")
    hybrid_queries = expander.expand_hybrid(test_query)
    for i, q in enumerate(hybrid_queries, 1):
        print(f"  {i}. {q}")

    print("\nKey Terms:")
    print(f"  {expander.extract_key_terms(test_query)}")
