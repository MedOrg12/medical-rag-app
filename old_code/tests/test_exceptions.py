"""
Tests for exceptions module.
"""

import pytest

from src.exceptions import (
    ChunkingError,
    ConfigurationError,
    EmbeddingError,
    FileOperationError,
    LLMError,
    PDFProcessingError,
    RAGPipelineError,
    ValidationError,
    VectorDatabaseError,
)


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_all_inherit_from_base(self):
        """Test that all exceptions inherit from RAGPipelineError."""
        exceptions = [
            PDFProcessingError,
            ChunkingError,
            EmbeddingError,
            VectorDatabaseError,
            LLMError,
            ConfigurationError,
            ValidationError,
            FileOperationError,
        ]

        for exc_class in exceptions:
            assert issubclass(exc_class, RAGPipelineError)

    def test_base_inherits_from_exception(self):
        """Test that base error inherits from Exception."""
        assert issubclass(RAGPipelineError, Exception)

    def test_exceptions_can_be_raised(self):
        """Test that exceptions can be raised with messages."""
        with pytest.raises(PDFProcessingError, match="test error"):
            raise PDFProcessingError("test error")

    def test_catch_with_base_class(self):
        """Test that specific exceptions can be caught with base class."""
        try:
            raise EmbeddingError("embedding failed")
        except RAGPipelineError as e:
            assert str(e) == "embedding failed"
            assert isinstance(e, EmbeddingError)

    def test_exception_messages(self):
        """Test that exception messages are preserved."""
        error_msg = "This is a detailed error message"
        error = VectorDatabaseError(error_msg)
        assert str(error) == error_msg
