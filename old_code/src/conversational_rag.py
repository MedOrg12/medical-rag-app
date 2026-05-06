"""
Conversational RAG with memory for multi-turn dialogues.
Extends the base RAG pipeline with conversation tracking.
"""

import json
from pathlib import Path
from typing import Any

from src.config import settings
from src.conversation import ConversationMemory
from src.logger import logger
from src.rag_pipeline import MedicalRAG, RAGResponse
from src.reranker import SimpleReRanker
from src.validation import ValidationError, validate_query


class ConversationalRAG(MedicalRAG):
    """
    RAG pipeline with conversation memory and context awareness.
    """

    def __init__(
        self,
        vector_db=None,
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        system_prompt: str = None,
        max_history: int = 10,
        conversation_save_path: Path | None = None,
        use_reranking: bool = False,
        use_hybrid_search: bool = False,
    ):
        """
        Initialize conversational RAG.

        Args:
            vector_db: VectorDatabase instance
            model: Ollama model name
            temperature: Generation temperature
            max_tokens: Max tokens to generate
            system_prompt: Custom system prompt
            max_history: Maximum conversation turns to remember
            conversation_save_path: Path to save conversation history
            use_reranking: Whether to use LLM re-ranking
            use_hybrid_search: Whether to use hybrid search
        """
        # Use keyword args — MedicalRAG.__init__ has `base_url` in slot 3,
        # so positional passing would put `temperature` into `base_url`.
        super().__init__(
            vector_db=vector_db,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

        self.memory = ConversationMemory(max_history=max_history, save_path=conversation_save_path)

        # Enhanced retrieval options
        self.use_reranking = use_reranking
        self.use_hybrid_search = use_hybrid_search

        if self.use_reranking:
            # Use simple re-ranker by default (faster)
            self.reranker = SimpleReRanker()
            logger.info("Enabled simple re-ranking")

        logger.info(
            f"Initialized conversational RAG "
            f"(hybrid={use_hybrid_search}, rerank={use_reranking})"
        )

    # Words that, in a short question, suggest the user is following up on
    # something just said rather than starting a new topic.
    _FOLLOWUP_MARKERS = (
        "that", "this", "it", "those", "these", "more", "explain", "expand",
        "elaborate", "clarify", "and", "why", "how so", "what about", "such",
        "really", "mean", "means",
    )

    def _build_search_query(self, question: str) -> str:
        """
        Build the query string used for vector retrieval.

        Short pronoun-heavy follow-ups ("what does that mean?", "tell me more")
        have no semantic content, so retrieving by their embedding returns
        garbage. When we detect one, fuse it with the most recent user
        question so retrieval anchors on the original topic. The model still
        sees the original short question for generation — it knows it's
        being asked to elaborate, not to re-answer.
        """
        if not self.memory.history:
            return question
        words = question.lower().split()
        if len(words) > 6:
            return question
        if not any(marker in words for marker in self._FOLLOWUP_MARKERS):
            return question
        prev_q = self.memory.history[-1].question
        return f"{prev_q} {question}"

    def query(
        self,
        question: str,
        top_k: int = None,
        filter_metadata: dict[str, Any] | None = None,
        return_context: bool = True,
        use_conversation_context: bool = True,
    ) -> RAGResponse:
        """
        Query with conversation context.

        Args:
            question: User question
            top_k: Number of chunks to retrieve
            filter_metadata: Metadata filters
            return_context: Include context chunks in response
            use_conversation_context: Whether to use conversation history

        Returns:
            RAGResponse with answer and sources
        """
        logger.info(f"Processing conversational query: '{question[:100]}...'")

        # If this is a short follow-up like "what does that mean?", fuse it
        # with the previous user question so retrieval has something concrete
        # to anchor on. Generation still sees the original short question.
        search_query = self._build_search_query(question) if use_conversation_context else question
        if search_query != question:
            logger.info(f"Follow-up detected — searching with fused query: '{search_query[:100]}'")

        # Step 1: Retrieve context (using the possibly-fused search query)
        if self.use_hybrid_search:
            logger.info("Using hybrid search for retrieval")
            retrieved_chunks = self.vector_db.hybrid_search(
                query_text=search_query,
                top_k=top_k or settings.top_k_results,
                filter_metadata=filter_metadata,
            )
        else:
            retrieved_chunks = self.retrieve_context(
                query=search_query, top_k=top_k, filter_metadata=filter_metadata
            )

        # Step 2: Re-rank if enabled
        if self.use_reranking and retrieved_chunks:
            logger.info("Re-ranking retrieved chunks")
            retrieved_chunks = self.reranker.rerank(
                query=question, chunks=retrieved_chunks, top_k=top_k or settings.top_k_results
            )

        if not retrieved_chunks:
            logger.warning("No context retrieved for query")
            return RAGResponse(
                question=question,
                answer="I couldn't find relevant information in the available research documents to answer this question.",
                sources=[],
                context_chunks=[],
                model_used=self.model,
            )

        # Step 3: Format the retrieved context (research only — conversation
        # history is now passed as real chat messages, not embedded here).
        context = self.format_context(retrieved_chunks)

        # Step 4: Build chat-message history from prior turns. Each turn
        # contributes a user question and the assistant answer, in order.
        history_messages: list[dict[str, str]] = []
        if use_conversation_context and self.memory.history:
            for turn in self.memory.history[-3:]:
                history_messages.append({"role": "user", "content": turn.question})
                history_messages.append({"role": "assistant", "content": turn.answer})
            logger.info(f"Threading {len(history_messages) // 2} prior turns into chat history")

        # Step 5: Generate answer
        answer = self.generate_answer(question, context, history=history_messages)

        # Step 5: Prepare sources
        sources = []
        for chunk in retrieved_chunks:
            metadata = chunk["metadata"]
            sources.append(
                {
                    "file": metadata.get("source_file", "Unknown"),
                    "title": metadata.get("source_title", "Unknown"),
                    "section": metadata.get("section_title", "N/A"),
                    "pages": metadata.get("page_numbers", []),
                    "similarity": chunk.get("similarity", 0.0),
                    "hybrid_score": chunk.get("hybrid_score", None),
                    "rerank_score": chunk.get("rerank_score", None),
                    "context": chunk.get("content", ""),  # Include context text
                }
            )

        # Step 6: Create response
        response = RAGResponse(
            question=question,
            answer=answer,
            sources=sources,
            context_chunks=[c["content"] for c in retrieved_chunks] if return_context else [],
            model_used=self.model,
        )

        # Step 7: Add to conversation memory
        self.memory.add_turn(question=question, answer=answer, sources=sources)

        logger.info("Conversational query completed successfully")
        return response

    def get_conversation_summary(self) -> str:
        """Get a summary of the current conversation."""
        return self.memory.get_summary()

    def get_conversation_history(self) -> list[dict[str, Any]]:
        """Get full conversation history."""
        return self.memory.get_full_history()

    def clear_conversation(self) -> None:
        """Clear conversation history."""
        self.memory.clear()
        logger.info("Cleared conversation history")

    def save_conversation(self, path: Path | None = None) -> None:
        """Save conversation to file."""
        self.memory.save(path)

    def load_conversation(self, path: Path | None = None) -> None:
        """Load conversation from file."""
        self.memory.load(path)

    def interactive_session(self, enable_features: bool = True) -> None:
        """
        Start an interactive Q&A session with all features enabled.

        Args:
            enable_features: Enable hybrid search and re-ranking
        """
        print("\n" + "=" * 80)
        print("Medical Research RAG Assistant - Conversational Mode")
        print("=" * 80)
        print(f"Model: {self.model}")
        print(
            f"Database: {self.vector_db.collection_name} ({self.vector_db.collection.count()} chunks)"
        )
        print(f"Hybrid Search: {'Enabled' if self.use_hybrid_search else 'Disabled'}")
        print(f"Re-ranking: {'Enabled' if self.use_reranking else 'Disabled'}")
        print("\nCommands:")
        print("  'quit' or 'exit' - End session")
        print("  'stats' - Database statistics")
        print("  'history' - Show conversation history")
        print("  'clear' - Clear conversation history")
        print("  'save' - Save conversation")
        print("=" * 80 + "\n")

        while True:
            try:
                question = input("\nYour question: ").strip()

                if not question:
                    continue

                if question.lower() in ["quit", "exit", "q"]:
                    print("\nGoodbye!")
                    break

                # Validate user input for regular queries
                if question.lower() not in ["stats", "history", "clear", "save"]:
                    try:
                        question = validate_query(question)
                    except ValidationError as e:
                        print(f"\n❌ Invalid input: {e}")
                        continue

                if question.lower() == "stats":
                    stats = self.vector_db.get_collection_stats()
                    print("\nDatabase Statistics:")
                    print(json.dumps(stats, indent=2))
                    continue

                if question.lower() == "history":
                    print(f"\n{self.get_conversation_summary()}")
                    print("\nRecent questions:")
                    for turn in self.memory.history[-5:]:
                        print(f"  {turn.turn_number}. {turn.question}")
                    continue

                if question.lower() == "clear":
                    self.clear_conversation()
                    print("\nConversation history cleared.")
                    continue

                if question.lower() == "save":
                    save_path = Path(settings.data_folder) / "conversation.json"
                    self.save_conversation(save_path)
                    print(f"\nConversation saved to {save_path}")
                    continue

                # Process query
                print("\n" + "-" * 80)
                print("Retrieving context and generating answer...")
                print("-" * 80 + "\n")

                response = self.query(question, return_context=False)

                # Display answer
                print(f"ANSWER:\n{response.answer}\n")

                # Display sources
                print("\nSOURCES:")
                for i, source in enumerate(response.sources, 1):
                    pages = ", ".join(map(str, source["pages"])) if source["pages"] else "Unknown"
                    score_info = f"Similarity: {source['similarity']:.3f}"

                    if source.get("hybrid_score"):
                        score_info += f", Hybrid: {source['hybrid_score']:.3f}"
                    if source.get("rerank_score"):
                        score_info += f", Rerank: {source['rerank_score']:.3f}"

                    print(
                        f"{i}. {source['file']} - {source['section']} "
                        f"(Page(s): {pages}, {score_info})"
                    )

                print("\n" + "-" * 80)

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                logger.error(f"Error in interactive session: {e}")
                print(f"\nError: {e}\n")


if __name__ == "__main__":
    # Test conversational RAG
    try:
        # Initialize with all features
        rag = ConversationalRAG(use_hybrid_search=True, use_reranking=True)

        # Check if database has data
        stats = rag.vector_db.get_collection_stats()
        if stats["total_chunks"] == 0:
            print("No data in vector database. Please run the ingestion pipeline first.")
            print("Run: python ingest.py")
        else:
            # Start interactive session
            rag.interactive_session()

    except Exception as e:
        logger.error(f"Error starting conversational RAG: {e}")
        print(f"Error: {e}")
