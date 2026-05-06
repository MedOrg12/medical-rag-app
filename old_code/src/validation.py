"""
Input validation utilities for user input sanitization and security.
"""

import re
from pathlib import Path

from src.config import settings
from src.exceptions import ValidationError


def validate_query(query: str, max_length: int | None = None) -> str:
    """
    Validate and sanitize user query input.

    Args:
        query: User input query string
        max_length: Maximum allowed query length

    Returns:
        Sanitized query string

    Raises:
        ValidationError: If query is invalid
    """
    if max_length is None:
        max_length = settings.max_query_length

    if not query or not query.strip():
        raise ValidationError("Query cannot be empty")

    query = query.strip()

    if len(query) > max_length:
        raise ValidationError(f"Query exceeds maximum length of {max_length} characters")

    # Check for suspicious path traversal patterns
    if re.search(r"\.\.[/\\]", query):
        raise ValidationError("Query contains suspicious path traversal patterns")

    return query


def validate_file_path(path: str | Path, base_dir: Path) -> Path:
    """
    Validate file path is within allowed directory.

    Args:
        path: File path to validate
        base_dir: Base directory that path must be within

    Returns:
        Resolved Path object

    Raises:
        ValidationError: If path is invalid or outside base directory
    """
    try:
        path_obj = Path(path).resolve()
        base_dir = base_dir.resolve()
    except (OSError, RuntimeError) as e:
        raise ValidationError(f"Invalid path: {e}")

    # Check if path is within base directory
    try:
        path_obj.relative_to(base_dir)
    except ValueError:
        raise ValidationError(f"Path must be within {base_dir}, got {path_obj}")

    return path_obj


def validate_positive_integer(value: int, name: str, max_value: int | None = None) -> int:
    """
    Validate that value is a positive integer within bounds.

    Args:
        value: Integer value to validate
        name: Name of the parameter (for error messages)
        max_value: Optional maximum allowed value

    Returns:
        Validated integer

    Raises:
        ValidationError: If value is invalid
    """
    if not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")

    if value <= 0:
        raise ValidationError(f"{name} must be positive")

    if max_value is not None and value > max_value:
        raise ValidationError(f"{name} cannot exceed {max_value}")

    return value


def validate_model_name(model_name: str) -> str:
    """
    Validate model name format.

    Args:
        model_name: Model name to validate

    Returns:
        Validated model name

    Raises:
        ValidationError: If model name is invalid
    """
    if not model_name or not model_name.strip():
        raise ValidationError("Model name cannot be empty")

    model_name = model_name.strip()

    # Model names: alphanumeric with hyphens, colons, dots, underscores, and
    # forward slashes (for HuggingFace-style names like "hf.co/user/model").
    if not re.match(r"^[a-zA-Z0-9_:\-\./]+$", model_name):
        raise ValidationError(
            "Model name can only contain letters, numbers, hyphens, colons, dots, slashes, and underscores"
        )

    return model_name


def validate_filename(filename: str, allowed_extensions: list[str] | None = None) -> str:
    """
    Validate filename for security issues.

    Args:
        filename: Filename to validate
        allowed_extensions: List of allowed file extensions (e.g., [".pdf", ".txt"])

    Returns:
        Validated filename

    Raises:
        ValidationError: If filename is invalid or insecure
    """
    if not filename or not filename.strip():
        raise ValidationError("Filename cannot be empty")

    filename = filename.strip()

    # Check for path traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValidationError("Filename contains invalid characters")

    # Check for null bytes (security issue)
    if "\x00" in filename:
        raise ValidationError("Filename contains null bytes")

    # Check for overly long filenames (filesystem limits)
    if len(filename) > 255:
        raise ValidationError("Filename exceeds maximum length of 255 characters")

    # Validate extension if provided
    if allowed_extensions:
        if not any(filename.lower().endswith(ext.lower()) for ext in allowed_extensions):
            raise ValidationError(
                f"File extension not allowed. Allowed extensions: {', '.join(allowed_extensions)}"
            )

    return filename


def sanitize_text_input(text: str, max_length: int = 10000) -> str:
    """
    Sanitize text input for safe processing.

    Args:
        text: Text input to sanitize
        max_length: Maximum allowed text length

    Returns:
        Sanitized text

    Raises:
        ValidationError: If text is invalid
    """
    if not isinstance(text, str):
        raise ValidationError("Input must be a string")

    # Remove null bytes
    text = text.replace("\x00", "")

    # Normalize whitespace (replace multiple spaces/newlines with single)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        raise ValidationError(f"Text exceeds maximum length of {max_length} characters")

    return text


def validate_temperature(temperature: float) -> float:
    """
    Validate temperature parameter for LLM generation.

    Args:
        temperature: Temperature value to validate

    Returns:
        Validated temperature

    Raises:
        ValidationError: If temperature is invalid
    """
    if not isinstance(temperature, (int, float)):
        raise ValidationError("Temperature must be a number")

    temperature = float(temperature)

    if temperature < 0.0 or temperature > 2.0:
        raise ValidationError("Temperature must be between 0.0 and 2.0")

    return temperature


def validate_top_k(top_k: int, max_value: int = 20) -> int:
    """
    Validate top_k parameter for retrieval.

    Args:
        top_k: Number of results to retrieve
        max_value: Maximum allowed value

    Returns:
        Validated top_k

    Raises:
        ValidationError: If top_k is invalid
    """
    if not isinstance(top_k, int):
        raise ValidationError("top_k must be an integer")

    if top_k < 1:
        raise ValidationError("top_k must be at least 1")

    if top_k > max_value:
        raise ValidationError(f"top_k cannot exceed {max_value}")

    return top_k
