"""
Custom exceptions for the Medical Research RAG Pipeline.
"""


class RAGPipelineError(Exception):
    """Base exception for all RAG pipeline errors."""

    pass


class PDFProcessingError(RAGPipelineError):
    """Error occurred while processing PDF file."""

    pass


class ChunkingError(RAGPipelineError):
    """Error occurred during document chunking."""

    pass


class EmbeddingError(RAGPipelineError):
    """Error occurred while generating embeddings."""

    pass


class VectorDatabaseError(RAGPipelineError):
    """Error occurred with vector database operations."""

    pass


class LLMError(RAGPipelineError):
    """Error occurred with LLM generation."""

    pass


class ConfigurationError(RAGPipelineError):
    """Error in configuration or settings."""

    pass


class ValidationError(RAGPipelineError):
    """Error in input validation."""

    pass


class FileOperationError(RAGPipelineError):
    """Error in file operations."""

    pass
