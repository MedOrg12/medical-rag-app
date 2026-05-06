"""
Desktop application launcher for Medical RAG.
Handles Ollama detection, model verification, and application startup.
"""

import os
import platform
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import httpx

from src.logger import logger
from src.user_data import get_user_data_manager


class OllamaManager:
    """Manages Ollama installation and model availability."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama manager.

        Args:
            base_url: Ollama API base URL
        """
        self.base_url = base_url
        self.timeout = 5.0

    def is_installed(self) -> bool:
        """
        Check if Ollama is installed on the system.

        Returns:
            True if Ollama is installed, False otherwise
        """
        system = platform.system()

        if system == "Darwin":  # macOS
            # Check common installation paths
            paths = [
                "/usr/local/bin/ollama",
                "/opt/homebrew/bin/ollama",
                Path.home() / ".ollama" / "bin" / "ollama",
            ]
            for path in paths:
                if Path(path).exists():
                    logger.info(f"Found Ollama at: {path}")
                    return True

        elif system == "Windows":
            # Check if ollama.exe is in PATH or common locations
            paths = [
                "ollama.exe",  # In PATH
                Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.getenv("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
            ]
            for path in paths:
                try:
                    if isinstance(path, str):
                        # Check PATH
                        result = subprocess.run(
                            ["where", path],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if result.returncode == 0:
                            logger.info(f"Found Ollama in PATH")
                            return True
                    elif Path(path).exists():
                        logger.info(f"Found Ollama at: {path}")
                        return True
                except Exception:
                    pass

        elif system == "Linux":
            # Check common Linux paths
            paths = [
                "/usr/bin/ollama",
                "/usr/local/bin/ollama",
                Path.home() / ".local" / "bin" / "ollama",
            ]
            for path in paths:
                if Path(path).exists():
                    logger.info(f"Found Ollama at: {path}")
                    return True

        logger.warning("Ollama not found on system")
        return False

    def install_ollama(self) -> bool:
        """
        Download and install Ollama (Windows only for now).

        Returns:
            True if installation successful, False otherwise
        """
        system = platform.system()

        if system != "Windows":
            logger.error("Automatic installation only supported on Windows")
            return False

        try:
            import tempfile

            print("\n" + "=" * 60)
            print("OLLAMA INSTALLATION")
            print("=" * 60)
            print("\nOllama is required but not installed.")
            print("\nDownload size: ~570 MB")
            print("Installation requires administrator privileges.")
            print("\nWould you like to download and install it now?")
            print("=" * 60)

            response = input("\nContinue? (Y/N): ").strip().upper()

            if response != 'Y':
                print("\nInstallation cancelled.")
                print("\nTo install manually:")
                print("1. Visit: https://ollama.com/download/windows")
                print("2. Download and run the installer")
                print("3. Restart this application")
                return False

            print("\n" + "=" * 60)
            print("Downloading Ollama installer...")
            print("=" * 60)

            # Ollama Windows installer URL
            installer_url = "https://ollama.com/download/OllamaSetup.exe"

            # Download to temp directory
            temp_dir = Path(tempfile.gettempdir())
            installer_path = temp_dir / "OllamaSetup.exe"

            logger.info(f"Downloading Ollama from: {installer_url}")

            # Download with progress using httpx (handles SSL properly)
            with httpx.stream("GET", installer_url, follow_redirects=True, timeout=300.0) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))

                downloaded = 0
                with open(installer_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            mb_downloaded = downloaded / (1024 * 1024)
                            mb_total = total_size / (1024 * 1024)
                            print(f"\rProgress: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end='', flush=True)

            print("\n\nDownload complete!")

            # Run installer
            print("\n" + "=" * 60)
            print("Running installer...")
            print("=" * 60)
            print("\nA Windows UAC prompt will appear.")
            print("Please click 'Yes' to allow installation.\n")

            logger.info(f"Launching installer: {installer_path}")

            # Run installer and wait for completion
            result = subprocess.run(
                [str(installer_path), "/S"],  # /S for silent install
                check=False
            )

            if result.returncode == 0:
                print("\n✓ Ollama installed successfully!")
                logger.info("Ollama installation completed")

                # Wait a moment for service to start
                print("\nWaiting for Ollama service to start...")
                time.sleep(5)

                # Clean up installer
                try:
                    installer_path.unlink()
                except Exception:
                    pass

                return True
            else:
                print(f"\n✗ Installation failed with code: {result.returncode}")
                logger.error(f"Ollama installation failed: {result.returncode}")
                return False

        except Exception as e:
            print(f"\n✗ Installation error: {e}")
            logger.error(f"Failed to install Ollama: {e}")
            import traceback
            traceback.print_exc()
            return False

    def is_running(self) -> bool:
        """
        Check if Ollama service is running.

        Returns:
            True if Ollama is responding to API requests, False otherwise
        """
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            if response.status_code == 200:
                logger.info("Ollama service is running")
                return True
        except Exception as e:
            logger.debug(f"Ollama not responding: {e}")

        return False

    def get_installed_models(self) -> list[str]:
        """
        Get list of installed Ollama models.

        Returns:
            List of model names
        """
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [model["name"] for model in models]
                logger.info(f"Found {len(model_names)} installed models")
                return model_names
        except Exception as e:
            logger.error(f"Failed to get installed models: {e}")

        return []

    def has_required_models(self, required_models: list[str]) -> tuple[bool, list[str]]:
        """
        Check if required models are installed.

        Args:
            required_models: List of required model names

        Returns:
            Tuple of (all_present, missing_models)
        """
        installed = self.get_installed_models()
        missing = []

        for model in required_models:
            # Check if model (with or without tag) is installed
            model_base = model.split(":")[0]
            if not any(m.startswith(model_base) for m in installed):
                missing.append(model)

        return len(missing) == 0, missing

    def get_ollama_command(self) -> str:
        """
        Get the Ollama executable path or command.

        Returns:
            Path to ollama executable or "ollama" command
        """
        system = platform.system()

        if system == "Windows":
            # Check common Windows paths
            paths = [
                Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.getenv("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
            ]
            for path in paths:
                if path.exists():
                    return str(path)

        # Default to command in PATH
        return "ollama"

    def pull_model(self, model_name: str, callback=None) -> bool:
        """
        Pull/download an Ollama model.

        Args:
            model_name: Name of model to pull
            callback: Optional callback function for progress updates

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Pulling model: {model_name}")
        print(f"\nDownloading model: {model_name}")
        print("This may take a few minutes...")

        try:
            # Get ollama command/path
            ollama_cmd = self.get_ollama_command()
            cmd = [ollama_cmd, "pull", model_name]

            # Use UTF-8 encoding on Windows to handle special characters
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding='utf-8',
                errors='replace',  # Replace invalid chars instead of crashing
                bufsize=1,
            )

            # Collect output for error reporting
            all_output = []

            # Stream output
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        all_output.append(line)
                        print(line)
                        if callback:
                            callback(line)

            process.wait()

            if process.returncode == 0:
                logger.info(f"Successfully pulled model: {model_name}")
                print(f"✓ Model {model_name} downloaded successfully\n")
                return True
            else:
                # Show the actual error from Ollama
                error_output = '\n'.join(all_output[-15:]) if all_output else "No output captured"
                logger.error(f"Failed to pull model {model_name}. Return code: {process.returncode}")
                logger.error(f"Ollama output:\n{error_output}")
                print(f"\n✗ Failed to download model: {model_name}")
                print(f"Return code: {process.returncode}")
                print(f"\nLast output from Ollama:")
                print(error_output)
                print()
                return False

        except Exception as e:
            logger.error(f"Error pulling model: {e}")
            logger.exception("Full traceback:")
            print(f"✗ Error: {e}\n")
            return False

    def test_connection(self) -> bool:
        """
        Test if Ollama is responding to commands.

        Returns:
            True if Ollama responds, False otherwise
        """
        try:
            ollama_cmd = self.get_ollama_command()
            result = subprocess.run(
                [ollama_cmd, "list"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace',
            )

            if result.returncode == 0:
                logger.info("Ollama connection test successful")
                return True
            else:
                logger.error(f"Ollama list command failed with return code {result.returncode}")
                logger.error(f"Output: {result.stdout}")
                logger.error(f"Error: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Ollama connection test timed out")
            return False
        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return False

    def start_service(self) -> bool:
        """
        Attempt to start Ollama service.

        Returns:
            True if service started or already running, False otherwise
        """
        if self.is_running():
            return True

        logger.info("Attempting to start Ollama service...")
        system = platform.system()

        try:
            if system == "Darwin":  # macOS
                # Try to start Ollama as a background service
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Windows":
                # On Windows, Ollama usually runs as a service
                # Try to start it
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif system == "Linux":
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Wait a few seconds for service to start
            logger.info("Waiting for Ollama service to start...")
            for i in range(10):
                time.sleep(1)
                if self.is_running():
                    logger.info("Ollama service started successfully")
                    return True

            logger.warning("Ollama service did not start in time")
            return False

        except Exception as e:
            logger.error(f"Failed to start Ollama service: {e}")
            return False


class DesktopLauncher:
    """Desktop application launcher."""

    def __init__(self):
        """Initialize desktop launcher."""
        self.user_data = get_user_data_manager()
        self.ollama = OllamaManager()
        self.required_models = ["deepseek-llm:7b-chat", "nomic-embed-text"]

    def copy_bundled_pdfs(self) -> int:
        """
        Copy bundled PDFs to user data directory if they don't exist there.

        Returns:
            Number of PDFs copied
        """
        import shutil

        # Get bundled PDFs directory (in the executable)
        if getattr(sys, 'frozen', False):
            # Running as bundled executable
            bundle_dir = Path(sys._MEIPASS)  # PyInstaller temp directory
        else:
            # Running in development
            bundle_dir = Path.cwd()

        bundled_pdfs_dir = bundle_dir / "pdfs"
        user_pdfs_dir = self.user_data.get_pdfs_dir()

        if not bundled_pdfs_dir.exists():
            logger.debug("No bundled PDFs directory found")
            return 0

        # Get list of bundled PDFs
        bundled_pdfs = list(bundled_pdfs_dir.glob("*.pdf"))
        if not bundled_pdfs:
            logger.debug("No PDFs found in bundle")
            return 0

        # Copy PDFs that don't already exist in user directory
        copied = 0
        for pdf_file in bundled_pdfs:
            dest_file = user_pdfs_dir / pdf_file.name
            if not dest_file.exists():
                try:
                    shutil.copy2(pdf_file, dest_file)
                    logger.info(f"Copied bundled PDF: {pdf_file.name}")
                    copied += 1
                except Exception as e:
                    logger.error(f"Failed to copy {pdf_file.name}: {e}")

        if copied > 0:
            logger.info(f"Copied {copied} bundled PDF(s) to user data directory")

        return copied

    def check_prerequisites(self) -> bool:
        """
        Check if all prerequisites are met.

        Returns:
            True if ready to launch, False otherwise
        """
        print("\n" + "=" * 60)
        print("Medical Research RAG - Desktop Application")
        print("=" * 60 + "\n")

        # Check Ollama installation
        print("Checking prerequisites...")
        print(f"  [1/3] Ollama installation... ", end="")
        if not self.ollama.is_installed():
            print("✗ NOT FOUND")

            # Attempt automatic installation on Windows
            system = platform.system()
            if system == "Windows":
                if self.ollama.install_ollama():
                    # Installation successful, verify it's now detected
                    if self.ollama.is_installed():
                        print(f"  [1/3] Ollama installation... ✓ INSTALLED")
                    else:
                        print("\n✗ Installation completed but Ollama not detected.")
                        print("  Please restart this application.")
                        return False
                else:
                    # Installation cancelled or failed
                    logger.error("Prerequisites not met. Exiting.")
                    return False
            else:
                # macOS/Linux - show manual instructions
                self._show_ollama_install_instructions()
                return False
        else:
            print("✓ OK")

        # Check Ollama service
        print(f"  [2/3] Ollama service... ", end="")
        if not self.ollama.is_running():
            print("⚠ NOT RUNNING")
            print("         Attempting to start Ollama...")
            if not self.ollama.start_service():
                print("         ✗ Failed to start Ollama")
                print("\n  Please start Ollama manually and try again.")
                return False
            print("         ✓ Ollama started")
        else:
            print("✓ RUNNING")

        # Check required models
        print(f"  [3/3] Required models... ", end="")
        has_models, missing = self.ollama.has_required_models(self.required_models)
        if not has_models:
            print(f"⚠ MISSING: {', '.join(missing)}")
            if not self._download_missing_models(missing):
                return False
            print("         ✓ All models downloaded")
        else:
            print("✓ ALL PRESENT")

        print("\n✓ All prerequisites met!\n")
        return True

    def _show_ollama_install_instructions(self) -> None:
        """Show instructions for installing Ollama."""
        system = platform.system()
        print("\n" + "!" * 60)
        print("OLLAMA NOT FOUND")
        print("!" * 60)
        print("\nOllama is required to run this application.")
        print("\nInstallation instructions:")

        if system == "Darwin":  # macOS
            print("\n  1. Visit: https://ollama.com/download")
            print("  2. Download Ollama for macOS")
            print("  3. Install and restart this application")
            print("\n  Or use Homebrew:")
            print("     brew install ollama")

        elif system == "Windows":
            print("\n  1. Visit: https://ollama.com/download")
            print("  2. Download Ollama for Windows")
            print("  3. Run the installer")
            print("  4. Restart this application")

        elif system == "Linux":
            print("\n  Run in terminal:")
            print("     curl -fsSL https://ollama.com/install.sh | sh")

        print("\n" + "!" * 60 + "\n")

    def _download_missing_models(self, missing_models: list[str]) -> bool:
        """
        Download missing models.

        Args:
            missing_models: List of model names to download

        Returns:
            True if all models downloaded successfully
        """
        print("\n  Downloading missing models...")

        # Test Ollama connection first
        print("  Testing Ollama connection... ", end="")
        if not self.ollama.test_connection():
            print("✗ FAILED")
            print("\n  ✗ Cannot connect to Ollama")
            print("    Please ensure Ollama is running and try again.")
            return False
        print("✓ OK")

        for model in missing_models:
            print(f"\n  Downloading: {model}")
            if not self.ollama.pull_model(model):
                print(f"\n  ✗ Failed to download {model}")
                print("    Please check:")
                print("      - Model name is correct")
                print("      - Internet connection is working")
                print("      - Sufficient disk space available")
                return False

        return True

    def open_browser(self, url: str = "http://localhost:8000") -> None:
        """
        Open system browser to the application URL.

        Args:
            url: URL to open
        """
        print(f"Opening browser to {url}...")
        try:
            webbrowser.open(url)
            logger.info(f"Opened browser to: {url}")
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            print(f"\nPlease open your browser manually to: {url}")

    def launch(self, open_browser: bool = True) -> bool:
        """
        Launch the desktop application.

        Args:
            open_browser: Whether to auto-open browser

        Returns:
            True if launch successful
        """
        # Check prerequisites
        if not self.check_prerequisites():
            return False

        # Show user data location
        info = self.user_data.get_storage_info()
        print(f"User data directory: {info['base_directory']}")
        print(f"PDFs folder: {info['directories']['pdfs']}")
        print("")

        # Open browser if requested
        if open_browser:
            # Give the server a moment to start
            time.sleep(2)
            self.open_browser()

        return True


def main():
    """Main entry point for desktop launcher."""
    launcher = DesktopLauncher()
    success = launcher.launch(open_browser=False)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
