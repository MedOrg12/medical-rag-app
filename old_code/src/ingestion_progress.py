"""
Progress tracking for ingestion pipeline to enable resumption after failures.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logger import logger


class IngestionProgress:
    """Track ingestion progress to enable resumption after failures."""

    def __init__(self, progress_file: Path | None = None) -> None:
        """
        Initialize ingestion progress tracker.

        Args:
            progress_file: Path to progress file. Defaults to ./data/ingestion_progress.json
        """
        self.progress_file = progress_file or Path("./data/ingestion_progress.json")
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)

        self.processed_files: set[str] = set()
        self.failed_files: dict[str, str] = {}  # filename -> error message
        self.started_at: str = ""
        self.last_updated: str = ""

        self._load_progress()

    def _load_progress(self) -> None:
        """Load progress from disk."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    data = json.load(f)

                self.processed_files = set(data.get("processed_files", []))
                self.failed_files = data.get("failed_files", {})
                self.started_at = data.get("started_at", "")
                self.last_updated = data.get("last_updated", "")

                logger.debug(
                    f"Loaded progress: {len(self.processed_files)} processed, "
                    f"{len(self.failed_files)} failed"
                )

            except Exception as e:
                logger.warning(f"Failed to load progress file: {e}")
                self.processed_files = set()
                self.failed_files = {}

        if not self.started_at:
            self.started_at = datetime.now().isoformat()

    def _save_progress(self) -> None:
        """Save progress to disk."""
        self.last_updated = datetime.now().isoformat()

        data = {
            "processed_files": list(self.processed_files),
            "failed_files": self.failed_files,
            "started_at": self.started_at,
            "last_updated": self.last_updated,
        }

        try:
            with open(self.progress_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")

    def mark_processed(self, file_path: str) -> None:
        """
        Mark file as successfully processed.

        Args:
            file_path: Path to processed file
        """
        self.processed_files.add(file_path)

        # Remove from failed files if it was there
        self.failed_files.pop(file_path, None)

        self._save_progress()

    def mark_failed(self, file_path: str, error: str) -> None:
        """
        Mark file as failed with error message.

        Args:
            file_path: Path to failed file
            error: Error message
        """
        self.failed_files[file_path] = error
        self._save_progress()

    def is_processed(self, file_path: str) -> bool:
        """
        Check if file has been successfully processed.

        Args:
            file_path: Path to file

        Returns:
            True if file was successfully processed
        """
        return file_path in self.processed_files

    def is_failed(self, file_path: str) -> bool:
        """
        Check if file previously failed.

        Args:
            file_path: Path to file

        Returns:
            True if file previously failed
        """
        return file_path in self.failed_files

    def get_status(self) -> dict[str, Any]:
        """
        Get current progress status.

        Returns:
            Dictionary with progress statistics
        """
        return {
            "total_processed": len(self.processed_files),
            "total_failed": len(self.failed_files),
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "processed_files": list(self.processed_files),
            "failed_files": list(self.failed_files.keys()),
        }

    def clear(self) -> None:
        """Clear all progress."""
        self.processed_files = set()
        self.failed_files = {}
        self.started_at = datetime.now().isoformat()
        self.last_updated = ""

        if self.progress_file.exists():
            self.progress_file.unlink()

        logger.info("Progress cleared")

    def get_remaining_files(self, all_files: list[Path]) -> list[Path]:
        """
        Get list of files that still need to be processed.

        Args:
            all_files: List of all PDF files

        Returns:
            List of files not yet processed
        """
        remaining = []

        for file_path in all_files:
            file_str = str(file_path)
            if not self.is_processed(file_str):
                remaining.append(file_path)

        return remaining

    def should_retry_failed(self, file_path: str) -> bool:
        """
        Check if a previously failed file should be retried.

        Args:
            file_path: Path to file

        Returns:
            True if file should be retried
        """
        # For now, don't retry failed files automatically
        # User can clear progress to retry everything
        return False
