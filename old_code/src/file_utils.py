"""
File operation utilities with safety checks.
"""

import os
import shutil
from pathlib import Path

from src.exceptions import FileOperationError


def check_file_readable(file_path: str | Path) -> Path:
    """
    Validate file exists and is readable.

    Args:
        file_path: Path to file to check

    Returns:
        Resolved Path object

    Raises:
        FileOperationError: If file is not readable
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileOperationError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise FileOperationError(f"Not a file: {file_path}")

    if not os.access(file_path, os.R_OK):
        raise FileOperationError(f"File not readable (permission denied): {file_path}")

    return file_path.resolve()


def check_directory_writable(dir_path: str | Path, create_if_missing: bool = True) -> Path:
    """
    Validate directory exists and is writable.

    Args:
        dir_path: Path to directory to check
        create_if_missing: Create directory if it doesn't exist

    Returns:
        Resolved Path object

    Raises:
        FileOperationError: If directory is not writable
    """
    dir_path = Path(dir_path)

    if not dir_path.exists():
        if create_if_missing:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise FileOperationError(f"Cannot create directory {dir_path}: {e}")
        else:
            raise FileOperationError(f"Directory not found: {dir_path}")

    if not dir_path.is_dir():
        raise FileOperationError(f"Not a directory: {dir_path}")

    if not os.access(dir_path, os.W_OK):
        raise FileOperationError(f"Directory not writable (permission denied): {dir_path}")

    return dir_path.resolve()


def check_disk_space(path: str | Path, required_mb: int = 100) -> None:
    """
    Check if enough disk space is available.

    Args:
        path: Path to check (file or directory)
        required_mb: Required space in megabytes

    Raises:
        FileOperationError: If insufficient disk space
    """
    path = Path(path)

    # Get parent directory if path is a file
    if path.is_file() or not path.exists():
        path = path.parent

    try:
        stat = shutil.disk_usage(path)
        available_mb = stat.free / (1024 * 1024)

        if available_mb < required_mb:
            raise FileOperationError(
                f"Insufficient disk space. Required: {required_mb}MB, "
                f"Available: {available_mb:.0f}MB"
            )
    except OSError as e:
        raise FileOperationError(f"Cannot check disk space: {e}")


def safe_read_file(file_path: str | Path, encoding: str = "utf-8") -> str:
    """
    Safely read a file with all necessary checks.

    Args:
        file_path: Path to file to read
        encoding: File encoding

    Returns:
        File contents as string

    Raises:
        FileOperationError: If file cannot be read
    """
    file_path = check_file_readable(file_path)

    try:
        return file_path.read_text(encoding=encoding)
    except Exception as e:
        raise FileOperationError(f"Failed to read file {file_path}: {e}")


def safe_write_file(
    file_path: str | Path, content: str, encoding: str = "utf-8", check_space: bool = True
) -> None:
    """
    Safely write to a file with all necessary checks.

    Args:
        file_path: Path to file to write
        content: Content to write
        encoding: File encoding
        check_space: Whether to check disk space

    Raises:
        FileOperationError: If file cannot be written
    """
    file_path = Path(file_path)

    # Check parent directory is writable
    check_directory_writable(file_path.parent, create_if_missing=True)

    # Check disk space if requested
    if check_space:
        content_size_mb = len(content.encode(encoding)) / (1024 * 1024)
        required_mb = max(10, int(content_size_mb * 1.5))  # 50% buffer
        check_disk_space(file_path.parent, required_mb=required_mb)

    try:
        file_path.write_text(content, encoding=encoding)
    except Exception as e:
        raise FileOperationError(f"Failed to write file {file_path}: {e}")


def list_files_safely(
    directory: str | Path, pattern: str = "*", recursive: bool = False
) -> list[Path]:
    """
    Safely list files in a directory.

    Args:
        directory: Directory to list
        pattern: Glob pattern to match
        recursive: Whether to search recursively

    Returns:
        List of Path objects

    Raises:
        FileOperationError: If directory cannot be read
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        raise FileOperationError(f"Directory not found: {dir_path}")

    if not dir_path.is_dir():
        raise FileOperationError(f"Not a directory: {dir_path}")

    if not os.access(dir_path, os.R_OK):
        raise FileOperationError(f"Directory not readable: {dir_path}")

    try:
        if recursive:
            return list(dir_path.rglob(pattern))
        else:
            return list(dir_path.glob(pattern))
    except Exception as e:
        raise FileOperationError(f"Failed to list directory {dir_path}: {e}")
