"""
RAG (Retrieval-Augmented Generation) pipeline for medical research queries.
Combines vector search with LLM generation using Ollama.
"""

import json
from dataclasses import dataclass
from typing import Any

import ollama

from src.config import settings
from src.logger import logger
from src.vector_db import VectorDatabase


@dataclass
class RAGResponse:
    """Response from the RAG pipeline."""

    question: str
    answer: str
    sources: list[dict[str, Any]]
    context_chunks: list[str]
    model_used: str


class MedicalRAG:
    """
    RAG pipeline for medical research question answering.
    Retrieves relevant context and generates answers using local Ollama models.
    """

    def __init__(
        self,
        vector_db: VectorDatabase = None,
        model: str = None,
        base_url: str | None = None,
        temperature: float = None,
        max_tokens: int = None,
        system_prompt: str = None,
    ):
        """
        Initialize the RAG pipeline.

        Args:
            vector_db: VectorDatabase instance (creates new if None)
            model: Ollama model name (defaults to config)
            base_url: Ollama base URL (defaults to config)
            temperature: Generation temperature (defaults to config)
            max_tokens: Maximum tokens to generate (defaults to config)
            system_prompt: Custom system prompt (uses default if None)
        """
        self.vector_db = vector_db or VectorDatabase()
        self.model = model or settings.ollama_model
        self.base_url = base_url or settings.ollama_base_url
        self.temperature = temperature or settings.temperature
        self.max_tokens = max_tokens or settings.max_tokens

        # Initialize Ollama client with correct host
        self.ollama_client = ollama.Client(host=self.base_url)

        # Default medical research assistant prompt
        self.system_prompt = system_prompt or self._get_default_system_prompt()

        # Check if model is available
        self._check_model_availability()

        logger.info(f"Initialized RAG pipeline with model: {self.model}")

    def _get_default_system_prompt(self) -> str:
        """Get the default system prompt for medical research assistant."""
        return """You are a friendly, knowledgeable medical research assistant — imagine you're a doctor explaining things to a curious patient or student. Be warm and conversational, not stiff or academic.

**This is a multi-turn conversation.** Earlier turns (if any) appear above as prior user/assistant messages. If the user asks a follow-up like "what does that mean?", "tell me more", "expand on that", "why?", or uses pronouns like "it"/"that"/"those", you MUST treat it as a continuation of YOUR previous answer. Expand and elaborate — explain things in different words, bring in extra detail and nuance you didn't mention before, and never just repeat what you already said.

How to write your answers:
- **Answer ONLY what was asked.** If the user asks "what is a stroke?", define a stroke and give the most essential context. Do not also explain symptoms, classification, risk factors, prevention, or diagnosis unless they specifically asked. If they ask "what are stroke symptoms?", list symptoms only — do not redefine what a stroke is.
- **Length should match the question.** Use these defaults:
  - One-fact question ("how many lobes does the brain have?") → 1-2 sentences.
  - Definition / "what is X" → one solid paragraph (~60-100 words). Define the term, give the most essential nuance, and stop. NOT a single sentence.
  - "How does X work" / comparisons → 2-3 short paragraphs.
  - Follow-ups like "what does that mean?", "tell me more", "explain that", "expand on it" → 3-5 paragraphs that go DEEPER than your previous answer. Bring in extra angles and detail. The user is asking for depth.
  - Multi-part question → one short paragraph per part.
  - Explicit request for detail/comprehensive/thorough → as long as needed, with headings if it helps.
- Speak naturally, like you're explaining to a real person sitting across from you. Use plain language and define medical terms the first time you use them.
- Start your answer directly with the explanation. Do NOT open with a heading, a title, a label like "Introduction", or a section number. Just begin talking.
- For short and medium answers (the default), use NO headings and NO bullet lists — just flowing prose. Headings and lists are only for long, multi-section answers the user specifically asked for.
- When you DO use headings (rare), use `##` for main sections and `###` for sub-sections. Never use `####` or deeper. Never number your headings.
- Separate paragraphs with a blank line. Keep paragraphs short.
- Do NOT include a "summary" or "in summary" sentence at the end. Do not restate what you just said.
- When you need to make a factual claim from the research, cite it with a simple bracketed number that matches the context number you're drawing from: [1], [2], [3], etc. For example: "Studies have shown that aspirin reduces cardiovascular events [1]." Do NOT write things like "[Source: filename]" or "(Context 2)" — just the number in brackets.
- You can cite multiple sources for one claim like [1][3] or [2][4].
- ABSOLUTELY CRITICAL: Never use the words "context", "Context 1", "Context 2", "the context", "outlined in 1", "additional contexts", "these sources", "the provided research", "the documents", or anything similar. The user CANNOT see the context — to them, you simply know the answer. Phrases like "Context 2 outlines..." or "as detailed in 4" are forbidden. Just state the fact and put the citation number in brackets at the end of the sentence.
- WRONG: "Context 2 outlines prevention strategies, emphasizing early recognition [2]."
- RIGHT: "Prevention strategies emphasize early recognition of symptoms [2]."
- WRONG: "This definition, outlined in 1, serves as a fundamental understanding."
- RIGHT: "A stroke is a focal neurological deficit caused by acute injury to the brain [1]."
- If the research doesn't answer the question, say so plainly and kindly.
- Acknowledge uncertainty where it exists, and mention conflicting findings if you see them.
- Don't make claims that aren't supported by what you've been given.

Be accurate, honest, and easy to read."""

    def _check_model_availability(self) -> None:
        """Check if the configured model is available in Ollama."""
        try:
            response = self.ollama_client.list()
            available_models = [model["name"].split(":")[0] for model in response.get("models", [])]

            if self.model.split(":")[0] not in available_models:
                logger.warning(
                    f"Model '{self.model}' may not be available. "
                    f"Available models: {', '.join(available_models)}"
                )
        except Exception as e:
            logger.warning(f"Could not check model availability: {e}")

    def retrieve_context(
        self, query: str, top_k: int = None, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant context for a query.

        Args:
            query: User question
            top_k: Number of chunks to retrieve (defaults to config)
            filter_metadata: Optional metadata filters

        Returns:
            List of retrieved chunks with metadata
        """
        top_k = top_k or settings.top_k_results

        try:
            results = self.vector_db.query(
                query_text=query, top_k=top_k, filter_metadata=filter_metadata
            )

            logger.info(f"Retrieved {len(results)} context chunks for query")
            return results

        except Exception as e:
            logger.error(f"Error retrieving context: {e}")
            raise

    def format_context(self, retrieved_chunks: list[dict[str, Any]]) -> str:
        """
        Format retrieved chunks into context string for the LLM.

        Args:
            retrieved_chunks: List of retrieved chunks with metadata

        Returns:
            Formatted context string
        """
        context_parts = []

        for i, chunk in enumerate(retrieved_chunks, 1):
            metadata = chunk["metadata"]
            source_file = metadata.get("source_file", "Unknown")
            section = metadata.get("section_title", "N/A")
            pages = metadata.get("page_numbers", [])
            page_str = f"Page(s): {', '.join(map(str, pages))}" if pages else "Page: Unknown"

            context_parts.append(
                f"[Context {i}]\n"
                f"Source: {source_file}\n"
                f"Section: {section}\n"
                f"{page_str}\n"
                f"Content: {chunk['content']}\n"
            )

        return "\n---\n".join(context_parts)

    def generate_answer(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
        stream: bool = False,
    ) -> str:
        """
        Generate answer using Ollama model.

        Args:
            query: User question
            context: Retrieved context
            history: Optional list of prior chat messages [{role, content}, ...]
                that go between the system prompt and the current user message.
            stream: Whether to stream the response

        Returns:
            Generated answer
        """
        # Construct the prompt
        user_message = f"""Use the research context below to answer the question. The context is numbered — when you draw a fact from a passage, cite it with the matching number in square brackets like [1] or [2]. Do not write the source filename inline; just the number.

CONTEXT:
{context}

QUESTION: {query}

Answer ONLY this exact question. Match the length to the question size (definition → one paragraph; follow-up like "what does that mean?" or "tell me more" → 3-5 paragraphs that go deeper than your previous answer). If the user is following up, expand on what you said before — don't repeat it. Don't drift into related topics they didn't ask about. No headings or bullets unless the answer is genuinely long. No "in summary" closer. Friendly conversational tone, cite with [1], [2]:"""

        # Build the full message list: system → prior turns → current question
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.ollama_client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )

            answer = response["message"]["content"]
            logger.info(f"Generated answer ({len(answer)} chars)")

            return answer

        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            raise

    def query(
        self,
        question: str,
        top_k: int = None,
        filter_metadata: dict[str, Any] | None = None,
        return_context: bool = True,
    ) -> RAGResponse:
        """
        Complete RAG query: retrieve context and generate answer.

        Args:
            question: User question
            top_k: Number of chunks to retrieve
            filter_metadata: Optional metadata filters
            return_context: Whether to include context chunks in response

        Returns:
            RAGResponse with answer and sources
        """
        logger.info(f"Processing RAG query: '{question[:100]}...'")

        # Step 1: Retrieve context
        retrieved_chunks = self.retrieve_context(
            query=question, top_k=top_k, filter_metadata=filter_metadata
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

        # Step 2: Format context
        context = self.format_context(retrieved_chunks)

        # Step 3: Generate answer
        answer = self.generate_answer(question, context)

        # Step 4: Prepare sources
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
                    "context": chunk.get("content", ""),  # Include context text
                }
            )

        # Step 5: Create response
        response = RAGResponse(
            question=question,
            answer=answer,
            sources=sources,
            context_chunks=[c["content"] for c in retrieved_chunks] if return_context else [],
            model_used=self.model,
        )

        logger.info("RAG query completed successfully")
        return response

    def interactive_session(self) -> None:
        """
        Start an interactive Q&A session.
        """
        print("\n" + "=" * 80)
        print("Medical Research RAG Assistant - Interactive Session")
        print("=" * 80)
        print(f"Model: {self.model}")
        print(
            f"Database: {self.vector_db.collection_name} ({self.vector_db.collection.count()} chunks)"
        )
        print("\nType 'quit' or 'exit' to end the session.")
        print("Type 'stats' to see database statistics.")
        print("=" * 80 + "\n")

        while True:
            try:
                question = input("\nYour question: ").strip()

                if not question:
                    continue

                if question.lower() in ["quit", "exit", "q"]:
                    print("\nGoodbye!")
                    break

                if question.lower() == "stats":
                    stats = self.vector_db.get_collection_stats()
                    print("\nDatabase Statistics:")
                    print(json.dumps(stats, indent=2))
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
                    print(
                        f"{i}. {source['file']} - {source['section']} "
                        f"(Page(s): {pages}, Similarity: {source['similarity']:.3f})"
                    )

                print("\n" + "-" * 80)

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                logger.error(f"Error in interactive session: {e}")
                print(f"\nError: {e}\n")


if __name__ == "__main__":
    # Test RAG pipeline
    try:
        # Initialize RAG
        rag = MedicalRAG()

        # Check if database has data
        stats = rag.vector_db.get_collection_stats()
        if stats["total_chunks"] == 0:
            print("No data in vector database. Please run the ingestion pipeline first.")
            print("Run: python src/ingest.py")
        else:
            # Start interactive session
            rag.interactive_session()

    except Exception as e:
        logger.error(f"Error starting RAG pipeline: {e}")
        print(f"Error: {e}")
