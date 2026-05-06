#!/usr/bin/env python3
"""
Medical Research RAG - Data Ingestion Pipeline

This script:
1. Parses all PDFs in ./pdf folder
2. Chunks the documents intelligently
3. Generates embeddings and stores in vector database
4. Optionally generates fine-tuning dataset

Usage:
    python ingest.py [--reset] [--generate-finetune] [--verbose] [--quiet]

Options:
    --reset: Delete existing vector database and start fresh
    --generate-finetune: Generate fine-tuning dataset from PDFs
    --verbose: Show detailed debug information
    --quiet: Show only warnings and errors
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.chunker import IntelligentChunker
from src.config import settings
from src.file_utils import (
    FileOperationError,
    check_directory_writable,
    check_disk_space,
)
from src.finetune_dataset import FineTuneDatasetGenerator
from src.ingestion_progress import IngestionProgress
from src.logging_config import get_logger, setup_logging
from src.metrics import get_metrics
from src.pdf_parser import PDFParser
from src.vector_db import VectorDatabase


def main():
    """Main ingestion pipeline."""
    parser = argparse.ArgumentParser(description="Ingest medical research PDFs into RAG pipeline")
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing vector database and start fresh"
    )
    parser.add_argument(
        "--generate-finetune", action="store_true", help="Generate fine-tuning dataset from PDFs"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed debug information"
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
    metrics = get_metrics()

    logger.info("=" * 80)
    logger.info("Medical Research RAG - Data Ingestion Pipeline")
    logger.info("=" * 80)

    # Initialize variables
    examples = None

    # Start overall timing
    metrics.start_timer("total_ingestion")

    # Validate directories and disk space before starting
    try:
        logger.info("\nValidating environment...")
        pdf_dir = Path(settings.pdf_folder)

        # Check PDF directory exists and is readable
        if not pdf_dir.exists():
            logger.error(f"PDF directory not found: {pdf_dir}")
            logger.error("Please create the directory and add PDF files.")
            sys.exit(1)

        # Check output directories are writable
        check_directory_writable(Path(settings.data_folder), create_if_missing=True)
        check_directory_writable(Path(settings.vector_db_path).parent, create_if_missing=True)
        check_directory_writable(Path(settings.log_file).parent, create_if_missing=True)

        # Check disk space (require at least 500MB)
        check_disk_space(Path(settings.data_folder), required_mb=500)

        logger.info("✓ Environment validation passed")

    except FileOperationError as e:
        logger.error(f"Environment validation failed: {e}")
        sys.exit(1)

    # Initialize progress tracking
    progress = IngestionProgress()

    if args.reset:
        logger.info("Reset flag detected - clearing previous progress")
        progress.clear()

    # Step 1: Parse PDFs
    logger.info("\nStep 1: Parsing PDFs from ./pdf folder")
    logger.info("-" * 80)

    metrics.start_timer("pdf_parsing")
    pdf_parser = PDFParser()
    pdf_files = pdf_parser.get_pdf_files()
    metrics.record("total_pdf_files", len(pdf_files))

    if not pdf_files:
        logger.error(
            f"\nNo PDF files found in {settings.pdf_folder}\n"
            "Please add PDF files to the ./pdf folder and run again."
        )
        sys.exit(1)

    # Filter out already processed files
    remaining_files = progress.get_remaining_files(pdf_files)

    logger.info(f"Found {len(pdf_files)} PDF files")
    if len(remaining_files) < len(pdf_files):
        logger.info(f"  {len(pdf_files) - len(remaining_files)} already processed")
        logger.info(f"  {len(remaining_files)} remaining to process")

    if not remaining_files:
        logger.info("All PDFs already processed! Use --reset to reprocess.")
        # Still show stats and exit
        vector_db = VectorDatabase()
        stats = vector_db.get_collection_stats()
        logger.info("\nCurrent Vector Database Statistics:")
        logger.info(f"  Total chunks: {stats['total_chunks']}")
        logger.info(f"  Collection: {stats['collection_name']}")
        sys.exit(0)

    for pdf_file in remaining_files:
        logger.info(f"  - {pdf_file.name}")

    # Parse only remaining files
    documents = []
    for pdf_file in remaining_files:
        try:
            logger.info(f"Processing: {pdf_file.name}")
            doc = pdf_parser.parse_pdf(pdf_file)
            if doc:
                documents.append(doc)
                progress.mark_processed(str(pdf_file))
                logger.info(f"  ✓ Completed: {pdf_file.name}")
            else:
                logger.warning(f"  ⚠ No content extracted from {pdf_file.name}")
                progress.mark_failed(str(pdf_file), "No content extracted")
        except Exception as e:
            logger.error(f"  ✗ Failed: {pdf_file.name} - {e}")
            progress.mark_failed(str(pdf_file), str(e))

    if not documents:
        logger.error("Failed to parse any documents. Please check PDF files and try again.")
        sys.exit(1)

    metrics.stop_timer("pdf_parsing")
    metrics.record("documents_parsed", len(documents))
    logger.info(f"\nSuccessfully parsed {len(documents)} documents")

    # Step 2: Chunk documents
    logger.info("\nStep 2: Chunking documents")
    logger.info("-" * 80)

    metrics.start_timer("chunking")
    chunker = IntelligentChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        min_chunk_size=settings.min_chunk_size,
    )

    chunks = chunker.chunk_documents(documents)

    if not chunks:
        logger.error("Failed to create chunks. Please check documents and try again.")
        sys.exit(1)

    metrics.stop_timer("chunking")
    metrics.record("total_chunks", len(chunks))
    logger.info(f"\nCreated {len(chunks)} chunks from {len(documents)} documents")

    # Statistics
    avg_chunk_size = sum(c.token_count for c in chunks) / len(chunks)
    metrics.record("avg_chunk_size", avg_chunk_size)
    logger.info(f"Average chunk size: {avg_chunk_size:.1f} tokens")

    # Step 3: Store in vector database
    logger.info("\nStep 3: Storing chunks in vector database")
    logger.info("-" * 80)

    metrics.start_timer("vector_db_storage")
    vector_db = VectorDatabase(reset=args.reset)

    if args.reset:
        logger.info("Reset flag detected - starting with fresh database")

    vector_db.add_chunks(chunks)
    metrics.stop_timer("vector_db_storage")

    # Show database stats
    stats = vector_db.get_collection_stats()
    logger.info("\nVector Database Statistics:")
    logger.info(f"  Total chunks: {stats['total_chunks']}")
    logger.info(f"  Collection: {stats['collection_name']}")
    logger.info(f"  Path: {stats['db_path']}")

    # Step 4: Generate fine-tuning dataset (optional)
    if args.generate_finetune:
        logger.info("\nStep 4: Generating fine-tuning dataset")
        logger.info("-" * 80)

        ft_generator = FineTuneDatasetGenerator()
        examples = ft_generator.generate_dataset(documents)

        if examples:
            # Save in multiple formats
            alpaca_path = ft_generator.save_dataset(examples, "finetune_alpaca.jsonl", "alpaca")
            chatml_path = ft_generator.save_dataset(examples, "finetune_chatml.jsonl", "chatml")

            # Create instructions
            instructions = ft_generator.create_unsloth_instructions(alpaca_path)
            instructions_path = settings.data_folder / "FINETUNING_INSTRUCTIONS.md"

            with open(instructions_path, "w") as f:
                f.write(instructions)

            logger.info(f"\nGenerated {len(examples)} training examples")
            logger.info("Saved to:")
            logger.info(f"  - {alpaca_path}")
            logger.info(f"  - {chatml_path}")
            logger.info(f"  - {instructions_path}")
        else:
            logger.warning("No fine-tuning examples generated")

    # Summary with progress status
    progress_status = progress.get_status()

    logger.info("\n" + "=" * 80)
    logger.info("Ingestion Pipeline Complete!")
    logger.info("=" * 80)
    logger.info("\nSummary:")
    logger.info(f"  PDFs processed this run: {len(documents)}")
    logger.info(f"  Total PDFs processed: {progress_status['total_processed']}")
    logger.info(f"  Failed PDFs: {progress_status['total_failed']}")
    logger.info(f"  Chunks created: {len(chunks)}")
    logger.info(f"  Average chunk size: {avg_chunk_size:.1f} tokens")
    logger.info(f"  Vector database: {stats['db_path']}")

    if progress_status["total_failed"] > 0:
        logger.warning("\nFailed files:")
        for failed_file in progress_status["failed_files"]:
            logger.warning(f"  - {failed_file}")

    if args.generate_finetune and examples:
        logger.info(f"  Fine-tune examples: {len(examples)}")

    # Stop total timer and log metrics
    metrics.stop_timer("total_ingestion")

    # Get embedding cache stats if available
    try:
        from src.embeddings import OllamaEmbeddings

        embeddings = OllamaEmbeddings()
        if hasattr(embeddings, "cache") and embeddings.cache:
            cache_stats = embeddings.cache.get_stats()
            metrics.record("cache_hits", cache_stats["hits"])
            metrics.record("cache_misses", cache_stats["misses"])
            metrics.record("cache_hit_rate", cache_stats["hit_rate_percent"])
            logger.info("\nEmbedding Cache Statistics:")
            logger.info(f"  Cache hits: {cache_stats['hits']}")
            logger.info(f"  Cache misses: {cache_stats['misses']}")
            logger.info(f"  Hit rate: {cache_stats['hit_rate_percent']:.1f}%")
    except Exception:
        pass  # Cache stats are optional

    # Log performance metrics
    metrics.log_summary("Ingestion Performance Metrics")

    logger.info("\nNext steps:")
    logger.info("  1. Run queries: python query.py")
    logger.info("  2. Interactive mode: python query.py --interactive")
    logger.info("  3. Create custom model: ollama create medical-assistant -f Modelfile")
    logger.info("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nIngestion interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nIngestion failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
