#!/usr/bin/env python3
"""
Enhanced Medical Research RAG - Query Interface

Advanced query interface with:
- Hybrid search (vector + keyword)
- Re-ranking for precision
- Conversation memory
- Query expansion
- Multi-query retrieval

Usage:
    # Interactive mode with all features
    python query_enhanced.py --interactive

    # Single query with hybrid search
    python query_enhanced.py --hybrid "What are stroke risk factors?"

    # With re-ranking
    python query_enhanced.py --rerank "Describe the methodology"

    # With query expansion
    python query_enhanced.py --expand "treatment outcomes"

    # All features enabled
    python query_enhanced.py --all-features --interactive

    # Verbosity control
    python query_enhanced.py --verbose --all-features --interactive
    python query_enhanced.py --quiet "What are the findings?"
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import settings
from src.conversational_rag import ConversationalRAG
from src.logging_config import get_logger, setup_logging
from src.query_expansion import MultiQueryRetriever, QueryExpander
from src.validation import ValidationError, validate_query
from src.vector_db import VectorDatabase


def print_response(response, verbose: bool = False, show_scores: bool = True):
    """
    Print RAG response in a formatted way.

    Args:
        response: RAGResponse object
        verbose: Whether to show detailed information
        show_scores: Whether to show all scoring details
    """
    print("\n" + "=" * 80)
    print("QUESTION:")
    print("-" * 80)
    print(response.question)

    print("\n" + "=" * 80)
    print("ANSWER:")
    print("-" * 80)
    print(response.answer)

    print("\n" + "=" * 80)
    print("SOURCES:")
    print("-" * 80)

    for i, source in enumerate(response.sources, 1):
        pages = ", ".join(map(str, source["pages"])) if source["pages"] else "Unknown"

        score_parts = [f"Similarity: {source['similarity']:.3f}"]

        if show_scores:
            if source.get("hybrid_score"):
                score_parts.append(f"Hybrid: {source['hybrid_score']:.3f}")
            if source.get("rerank_score"):
                score_parts.append(f"Rerank: {source['rerank_score']:.3f}")

        score_info = ", ".join(score_parts)

        print(
            f"\n{i}. File: {source['file']}\n"
            f"   Title: {source['title']}\n"
            f"   Section: {source['section']}\n"
            f"   Page(s): {pages}\n"
            f"   Scores: {score_info}"
        )

    if verbose and response.context_chunks:
        print("\n" + "=" * 80)
        print("CONTEXT CHUNKS:")
        print("-" * 80)

        for i, chunk in enumerate(response.context_chunks, 1):
            print(f"\n--- Chunk {i} ---")
            print(chunk[:300] + "..." if len(chunk) > 300 else chunk)

    print("\n" + "=" * 80)
    print(f"Model: {response.model_used}")
    print("=" * 80 + "\n")


def single_query_mode(
    rag: ConversationalRAG,
    question: str,
    top_k: int,
    verbose: bool,
    use_expansion: bool = False,
    logger=None,
):
    """
    Execute a single query.

    Args:
        rag: ConversationalRAG instance
        question: Question to ask
        top_k: Number of chunks to retrieve
        verbose: Show detailed information
        use_expansion: Use query expansion
        logger: Logger instance (optional)
    """
    if logger is None:
        logger = get_logger()

    # Validate query input
    try:
        question = validate_query(question)
    except ValidationError as e:
        logger.error(f"Invalid query: {e}")
        print(f"\n❌ Invalid input: {e}")
        sys.exit(1)

    logger.info(f"Processing single query: {question}")

    if use_expansion:
        # Use multi-query retrieval
        expander = QueryExpander()
        multi_retriever = MultiQueryRetriever(expander, rag.vector_db)

        print("\n" + "-" * 80)
        print("Expanding query...")
        print("-" * 80)

        # Get expanded queries (will show in logs)
        expanded_queries = expander.expand_hybrid(question, num_llm_variations=2)
        print("\nQuery variations:")
        for i, q in enumerate(expanded_queries, 1):
            print(f"  {i}. {q}")

        print("\nRetrieving with multiple queries...")
        results = multi_retriever.retrieve(question, top_k=top_k, expansion_method="hybrid")

        # Format as RAGResponse
        context = rag.format_context(results)
        answer = rag.generate_answer(question, context)

        sources = []
        for chunk in results:
            metadata = chunk["metadata"]
            sources.append(
                {
                    "file": metadata.get("source_file", "Unknown"),
                    "title": metadata.get("source_title", "Unknown"),
                    "section": metadata.get("section_title", "N/A"),
                    "pages": metadata.get("page_numbers", []),
                    "similarity": chunk.get("similarity", 0.0),
                    "multi_query_score": chunk.get("multi_query_score", None),
                }
            )

        from src.rag_pipeline import RAGResponse

        response = RAGResponse(
            question=question,
            answer=answer,
            sources=sources,
            context_chunks=[c["content"] for c in results] if verbose else [],
            model_used=rag.model,
        )
    else:
        response = rag.query(question=question, top_k=top_k, return_context=verbose)

    print_response(response, verbose=verbose)


def main():
    """Main enhanced query interface."""
    parser = argparse.ArgumentParser(
        description="Enhanced Medical Research RAG Query Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive with all features
  python query_enhanced.py --all-features --interactive

  # Single query with hybrid search
  python query_enhanced.py --hybrid "What are stroke risk factors?"

  # With re-ranking
  python query_enhanced.py --rerank "Describe the methodology"

  # With query expansion
  python query_enhanced.py --expand "treatment outcomes"

  # All features for single query
  python query_enhanced.py --all-features "What are the main findings?"
        """,
    )

    parser.add_argument("question", nargs="?", help="Question to ask (for single query mode)")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Start interactive Q&A session"
    )
    parser.add_argument(
        "--hybrid", action="store_true", help="Enable hybrid search (vector + keyword)"
    )
    parser.add_argument(
        "--rerank", action="store_true", help="Enable re-ranking for better precision"
    )
    parser.add_argument("--expand", action="store_true", help="Enable query expansion")
    parser.add_argument("--all-features", action="store_true", help="Enable all advanced features")
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=None,
        help=f"Ollama model to use (default: {settings.ollama_model})",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=None,
        help=f"Number of chunks to retrieve (default: {settings.top_k_results})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed debug logging and context chunks",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Show only warnings and errors")

    args = parser.parse_args()

    # Setup logging based on verbosity flags
    if args.quiet:
        log_level = "ERROR"
    elif args.verbose:
        log_level = "DEBUG"
    else:
        log_level = "INFO"

    setup_logging(log_level=log_level, log_file=Path(settings.log_file), log_to_console=True)

    logger = get_logger()

    # Validate arguments
    if not args.interactive and not args.question:
        parser.error("Must provide either a question or --interactive")

    # Determine which features to enable
    use_hybrid = args.hybrid or args.all_features
    use_rerank = args.rerank or args.all_features
    use_expand = args.expand or args.all_features

    # Initialize enhanced RAG system
    logger.info("Initializing Enhanced Medical Research RAG system...")

    try:
        # Check if vector database has data
        vector_db = VectorDatabase()
        stats = vector_db.get_collection_stats()

        if stats["total_chunks"] == 0:
            logger.error(
                "\nVector database is empty. Please run the ingestion pipeline first:\n"
                "  python ingest.py\n"
            )
            sys.exit(1)

        logger.info(f"Loaded database with {stats['total_chunks']} chunks")

        # Initialize ConversationalRAG with features
        rag = ConversationalRAG(
            vector_db=vector_db,
            model=args.model,
            use_hybrid_search=use_hybrid,
            use_reranking=use_rerank,
        )

        # Show enabled features
        print("\n" + "=" * 80)
        print("Enhanced Medical Research RAG")
        print("=" * 80)
        print(f"Model: {rag.model}")
        print(f"Database: {stats['total_chunks']} chunks")
        print("\nFeatures Enabled:")
        print(f"  • Hybrid Search (vector + keyword): {'✓' if use_hybrid else '✗'}")
        print(f"  • Re-ranking: {'✓' if use_rerank else '✗'}")
        print(f"  • Query Expansion: {'✓' if use_expand else '✗'}")
        print("  • Conversation Memory: ✓")
        print("=" * 80 + "\n")

        # Determine mode and execute
        if args.interactive:
            rag.interactive_session()
        else:
            single_query_mode(
                rag,
                args.question,
                args.top_k or settings.top_k_results,
                args.verbose,
                use_expansion=use_expand,
                logger=logger,
            )

    except KeyboardInterrupt:
        logger.info("\n\nQuery interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\nQuery failed with error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
