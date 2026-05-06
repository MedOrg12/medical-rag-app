"""
User data directory management for the Medical RAG Desktop Application.
Handles platform-specific user data paths and ensures proper directory structure.
"""

import os
import platform
import sys
from pathlib import Path
from typing import Optional

from src.logger import logger


class UserDataManager:
    """Manages user data directories for the desktop application."""

    def __init__(self, app_name: str = "MedicalRAG"):
        """
        Initialize user data manager.

        Args:
            app_name: Application name for directory naming
        """
        self.app_name = app_name
        self._base_dir: Optional[Path] = None
        self._is_docker_mode: bool = self._check_docker_mode()
        self._is_dev_mode: bool = self._check_dev_mode()

    def _check_docker_mode(self) -> bool:
        """
        Check if running in Docker container.

        Returns:
            True if in Docker, False otherwise
        """
        # Check for .dockerenv file
        if os.path.exists('/.dockerenv'):
            return True

        # Check for DOCKER_CONTAINER environment variable
        if os.getenv('DOCKER_CONTAINER', '').lower() in ('true', '1', 'yes'):
            return True

        # Check cgroup for docker
        try:
            with open('/proc/1/cgroup', 'rt') as f:
                return 'docker' in f.read()
        except Exception:
            pass

        return False

    def _check_dev_mode(self) -> bool:
        """
        Check if running in development mode (not bundled executable).

        Returns:
            True if in development mode, False if bundled
        """
        # PyInstaller sets sys.frozen when bundled
        is_frozen = getattr(sys, "frozen", False)
        return not is_frozen

    def get_base_dir(self) -> Path:
        """
        Get the base user data directory.

        In Docker: Uses /app directory
        In development: Uses current working directory
        In production: Uses platform-specific app data directory

        Returns:
            Path to base user data directory
        """
        if self._base_dir:
            return self._base_dir

        if self._is_docker_mode:
            # Docker mode: use /app directory
            self._base_dir = Path("/app")
            logger.info(f"Running in Docker mode, using: {self._base_dir}")
        elif self._is_dev_mode:
            # Development mode: use current directory
            self._base_dir = Path.cwd()
            logger.info(f"Running in development mode, using: {self._base_dir}")
        else:
            # Production mode: use platform-specific directory
            system = platform.system()

            if system == "Darwin":  # macOS
                base = Path.home() / "Library" / "Application Support" / self.app_name
            elif system == "Windows":
                appdata = os.getenv("APPDATA")
                if appdata:
                    base = Path(appdata) / self.app_name
                else:
                    base = Path.home() / "AppData" / "Roaming" / self.app_name
            elif system == "Linux":
                base = Path.home() / ".local" / "share" / self.app_name
            else:
                # Fallback to home directory
                base = Path.home() / f".{self.app_name.lower()}"

            self._base_dir = base
            logger.info(f"Running in production mode, using: {self._base_dir}")

        # Ensure base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)
        return self._base_dir

    def get_pdfs_dir(self) -> Path:
        """Get the PDFs directory."""
        path = self.get_base_dir() / "pdfs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_vector_db_dir(self) -> Path:
        """Get the vector database directory."""
        path = self.get_base_dir() / "vector_db"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_data_dir(self) -> Path:
        """Get the data/cache directory."""
        path = self.get_base_dir() / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_logs_dir(self) -> Path:
        """Get the logs directory."""
        path = self.get_base_dir() / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_config_file(self) -> Path:
        """Get the user configuration file path."""
        return self.get_base_dir() / ".env"

    def initialize_directories(self) -> None:
        """
        Initialize all required directories for the application.
        Creates directory structure if it doesn't exist.
        """
        dirs_to_create = [
            ("PDFs", self.get_pdfs_dir()),
            ("Vector DB", self.get_vector_db_dir()),
            ("Data/Cache", self.get_data_dir()),
            ("Logs", self.get_logs_dir()),
        ]

        logger.info("Initializing user data directories...")
        for name, path in dirs_to_create:
            if path.exists():
                logger.debug(f"{name} directory exists: {path}")
            else:
                path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created {name} directory: {path}")

        # Create default .env if it doesn't exist
        config_file = self.get_config_file()
        if not config_file.exists():
            logger.info(f"Creating default configuration: {config_file}")
            self._create_default_config(config_file)

    def _create_default_config(self, config_path: Path) -> None:
        """
        Create default .env configuration file.

        Args:
            config_path: Path to .env file
        """
        default_config = """# Medical RAG Desktop Application Configuration

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:1.5b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# RAG Configuration
TOP_K_RESULTS=5
TEMPERATURE=0.1
MAX_TOKENS=2048

# Chunking Configuration
CHUNK_SIZE=512
CHUNK_OVERLAP=50
MIN_CHUNK_SIZE=100

# Logging
LOG_LEVEL=INFO
"""
        config_path.write_text(default_config)

    def get_storage_info(self) -> dict:
        """
        Get information about user data storage.

        Returns:
            Dictionary with storage information
        """
        import shutil

        base_dir = self.get_base_dir()
        pdfs_dir = self.get_pdfs_dir()
        vector_db_dir = self.get_vector_db_dir()
        data_dir = self.get_data_dir()

        def get_dir_size(path: Path) -> int:
            """Calculate directory size in bytes."""
            total = 0
            try:
                for entry in path.rglob("*"):
                    if entry.is_file():
                        total += entry.stat().st_size
            except (PermissionError, OSError):
                pass
            return total

        def format_size(size_bytes: int) -> str:
            """Format bytes to human-readable string."""
            for unit in ["B", "KB", "MB", "GB"]:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f} TB"

        # Get disk usage
        disk_usage = shutil.disk_usage(base_dir)

        return {
            "base_directory": str(base_dir),
            "is_development_mode": self._is_dev_mode,
            "directories": {
                "pdfs": str(pdfs_dir),
                "vector_db": str(vector_db_dir),
                "data": str(data_dir),
                "logs": str(self.get_logs_dir()),
            },
            "storage_used": {
                "pdfs": format_size(get_dir_size(pdfs_dir)),
                "vector_db": format_size(get_dir_size(vector_db_dir)),
                "data": format_size(get_dir_size(data_dir)),
                "total": format_size(get_dir_size(base_dir)),
            },
            "disk_space": {
                "total": format_size(disk_usage.total),
                "used": format_size(disk_usage.used),
                "free": format_size(disk_usage.free),
            },
        }


# Global instance
_user_data_manager: Optional[UserDataManager] = None


def get_user_data_manager() -> UserDataManager:
    """
    Get the global UserDataManager instance.

    Returns:
        Global UserDataManager instance
    """
    global _user_data_manager
    if _user_data_manager is None:
        _user_data_manager = UserDataManager()
        _user_data_manager.initialize_directories()
    return _user_data_manager


if __name__ == "__main__":
    # Test the user data manager
    manager = get_user_data_manager()
    info = manager.get_storage_info()

    print("\n=== User Data Manager Information ===")
    print(f"Base Directory: {info['base_directory']}")
    print(f"Development Mode: {info['is_development_mode']}")
    print("\nDirectories:")
    for name, path in info["directories"].items():
        print(f"  {name}: {path}")
    print("\nStorage Used:")
    for name, size in info["storage_used"].items():
        print(f"  {name}: {size}")
    print("\nDisk Space:")
    for name, size in info["disk_space"].items():
        print(f"  {name}: {size}")
