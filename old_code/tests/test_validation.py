"""
Tests for validation module.
"""


import pytest

from src.validation import (
    ValidationError,
    validate_file_path,
    validate_model_name,
    validate_positive_integer,
    validate_query,
)


class TestValidateQuery:
    """Tests for validate_query function."""

    def test_valid_query(self):
        """Test validation of valid query."""
        result = validate_query("What are the main findings?")
        assert result == "What are the main findings?"

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        result = validate_query("  test query  ")
        assert result == "test query"

    def test_empty_query_raises_error(self):
        """Test that empty query raises ValidationError."""
        with pytest.raises(ValidationError, match="Query cannot be empty"):
            validate_query("")

    def test_whitespace_only_raises_error(self):
        """Test that whitespace-only query raises ValidationError."""
        with pytest.raises(ValidationError, match="Query cannot be empty"):
            validate_query("   ")

    def test_query_too_long_raises_error(self):
        """Test that query exceeding max length raises ValidationError."""
        long_query = "x" * 2001
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_query(long_query)

    def test_custom_max_length(self):
        """Test validation with custom max length."""
        with pytest.raises(ValidationError, match="exceeds maximum length of 10"):
            validate_query("this is too long", max_length=10)

    def test_path_traversal_detected(self):
        """Test that path traversal patterns are detected."""
        with pytest.raises(ValidationError, match="suspicious path traversal"):
            validate_query("../../etc/passwd")


class TestValidateFilePath:
    """Tests for validate_file_path function."""

    def test_valid_path_within_base(self, tmp_path):
        """Test validation of path within base directory."""
        base_dir = tmp_path
        file_path = base_dir / "test.txt"
        result = validate_file_path(file_path, base_dir)
        assert result.is_relative_to(base_dir)

    def test_path_outside_base_raises_error(self, tmp_path):
        """Test that path outside base directory raises ValidationError."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        outside_path = tmp_path / "outside.txt"

        with pytest.raises(ValidationError, match="Path must be within"):
            validate_file_path(outside_path, base_dir)


class TestValidatePositiveInteger:
    """Tests for validate_positive_integer function."""

    def test_valid_positive_integer(self):
        """Test validation of valid positive integer."""
        result = validate_positive_integer(5, "test_param")
        assert result == 5

    def test_zero_raises_error(self):
        """Test that zero raises ValidationError."""
        with pytest.raises(ValidationError, match="must be positive"):
            validate_positive_integer(0, "test_param")

    def test_negative_raises_error(self):
        """Test that negative value raises ValidationError."""
        with pytest.raises(ValidationError, match="must be positive"):
            validate_positive_integer(-5, "test_param")

    def test_non_integer_raises_error(self):
        """Test that non-integer raises ValidationError."""
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_positive_integer("5", "test_param")  # type: ignore

    def test_max_value_enforced(self):
        """Test that max_value is enforced."""
        with pytest.raises(ValidationError, match="cannot exceed 10"):
            validate_positive_integer(15, "test_param", max_value=10)

    def test_max_value_boundary(self):
        """Test that max_value boundary is inclusive."""
        result = validate_positive_integer(10, "test_param", max_value=10)
        assert result == 10


class TestValidateModelName:
    """Tests for validate_model_name function."""

    def test_valid_model_name(self):
        """Test validation of valid model name."""
        result = validate_model_name("nomic-embed-text")
        assert result == "nomic-embed-text"

    def test_model_with_version(self):
        """Test validation of model name with version."""
        result = validate_model_name("deepseek-r1:7b")
        assert result == "deepseek-r1:7b"

    def test_empty_model_name_raises_error(self):
        """Test that empty model name raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_model_name("")

    def test_invalid_characters_raise_error(self):
        """Test that invalid characters raise ValidationError."""
        with pytest.raises(ValidationError, match="can only contain"):
            validate_model_name("model@name")

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        result = validate_model_name("  model-name  ")
        assert result == "model-name"
