#!/usr/bin/env python3
"""
Medical Research RAG - Query Interface

This script provides multiple ways to query the RAG system:
1. Single query mode (command-line argument)
2. Interactive mode (conversation-style Q&A)
3. Batch query mode (from file)

Usage:
    # Single query
    python query.py "What are the main findings?"

    # Interactive mode
    python query.py --interactive

    # Batch queries from file
    python query.py --batch queries.txt

    # Use custom model
    python query.py --model medical-assistant --interactive

    # Adjust number of retrieved chunks
    python query.py --top-k 10 "What is the methodology?"

    # Verbosity control
    python query.py --verbose "What is the methodology?"
    python query.py --quiet --interactive
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import settings
from src.logging_config import get_logger, setup_logging
from src.metrics import get_metrics
from src.rag_pipeline import MedicalRAG
from src.validation import ValidationError, validate_positive_integer, validate_query
from src.vector_db import VectorDatabase


def print_response(response, verbose: bool = False):
    """
    Print RAG response in a formatted way.

    Args:
        response: RAGResponse object
        verbose: Whether to show detailed information
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
        print(
            f"\n{i}. File: {source['file']}\n"
            f"   Title: {source['title']}\n"
            f"   Section: {source['section']}\n"
            f"   Page(s): {pages}\n"
            f"   Similarity: {source['similarity']:.3f}"
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


def single_query_mode(rag: MedicalRAG, question: str, top_k: int, verbose: bool, logger=None):
    """
    Execute a single query.

    Args:
        rag: MedicalRAG instance
        question: Question to ask
        top_k: Number of chunks to retrieve
        verbose: Show detailed information
        logger: Logger instance (optional)
    """
    if logger is None:
        logger = get_logger()

    metrics = get_metrics()

    # Validate query input
    try:
        question = validate_query(question)
    except ValidationError as e:
        logger.error(f"Invalid query: {e}")
        print(f"\n❌ Invalid input: {e}")
        sys.exit(1)

    logger.info(f"Processing single query: {question}")

    metrics.start_timer("query_processing")
    response = rag.query(question=question, top_k=top_k, return_context=verbose)
    query_time = metrics.stop_timer("query_processing")

    print_response(response, verbose=verbose)
    logger.info(f"Query processed in {query_time:.2f}s")


def batch_query_mode(
    rag: MedicalRAG, batch_file: Path, top_k: int, output_file: Path | None = None, logger=None
):
    """
    Execute queries from a batch file.

    Args:
        rag: MedicalRAG instance
        batch_file: Path to file with questions (one per line)
        top_k: Number of chunks to retrieve
        output_file: Optional output file for results
        logger: Logger instance (optional)
    """
    if logger is None:
        logger = get_logger()

    metrics = get_metrics()

    if not batch_file.exists():
        logger.error(f"Batch file not found: {batch_file}")
        sys.exit(1)

    # Read questions
    with open(batch_file) as f:
        questions = [line.strip() for line in f if line.strip()]

    logger.info(f"Processing {len(questions)} queries from {batch_file}")
    metrics.start_timer("batch_processing")
    metrics.record("total_queries", len(questions))

    results = []

    for i, question in enumerate(questions, 1):
        # Validate each query
        try:
            question = validate_query(question)
        except ValidationError as e:
            logger.warning(f"Skipping invalid query {i}: {e}")
            print(f"\n❌ Skipping invalid query {i}: {e}")
            continue

        logger.info(f"Query {i}/{len(questions)}: {question}")

        response = rag.query(question=question, top_k=top_k, return_context=False)

        print(f"\n{'='*80}")
        print(f"Query {i}/{len(questions)}")
        print_response(response, verbose=False)

        # Store for output file
        results.append(
            {"question": response.question, "answer": response.answer, "sources": response.sources}
        )

    # Save to output file if specified
    if output_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved results to {output_file}")

    batch_time = metrics.stop_timer("batch_processing")
    metrics.record("queries_processed", len(results))
    logger.info(f"\nBatch processing completed in {batch_time:.2f}s")
    logger.info(f"Average time per query: {batch_time / len(results):.2f}s")


def interactive_mode(rag: MedicalRAG):
    """
    Start interactive Q&A session.

    Args:
        rag: MedicalRAG instance
    """
    rag.interactive_session()


def main():
    """Main query interface."""
    parser = argparse.ArgumentParser(
        description="Query the Medical Research RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python query.py "What are the main findings?"
  python query.py --interactive
  python query.py --batch queries.txt --output results.json
  python query.py --model medical-assistant --top-k 10 "Describe the methodology"
        """,
    )

    parser.add_argument("question", nargs="?", help="Question to ask (for single query mode)")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Start interactive Q&A session"
    )
    parser.add_argument(
        "--batch", "-b", type=Path, help="Batch query mode: file with questions (one per line)"
    )
    parser.add_argument(
        "--output", "-o", type=Path, help="Output file for batch query results (JSON)"
    )
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
        "--temperature",
        "-t",
        type=float,
        default=None,
        help=f"Generation temperature (default: {settings.temperature})",
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
    if not args.interactive and not args.question and not args.batch:
        parser.error("Must provide either a question, --interactive, or --batch")

    # Validate numeric parameters
    if args.top_k is not None:
        try:
            args.top_k = validate_positive_integer(args.top_k, "top_k", max_value=100)
        except ValidationError as e:
            parser.error(str(e))

    if args.temperature is not None:
        if not (0.0 <= args.temperature <= 2.0):
            parser.error("Temperature must be between 0.0 and 2.0")

    # Initialize RAG system
    logger.info("Initializing Medical Research RAG system...")

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

        # Initialize RAG
        rag = MedicalRAG(vector_db=vector_db, model=args.model, temperature=args.temperature)

        # Determine mode and execute
        if args.interactive:
            interactive_mode(rag)
        elif args.batch:
            batch_query_mode(
                rag, args.batch, args.top_k or settings.top_k_results, args.output, logger=logger
            )
        else:
            single_query_mode(
                rag,
                args.question,
                args.top_k or settings.top_k_results,
                args.verbose,
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
