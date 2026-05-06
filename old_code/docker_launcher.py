#!/usr/bin/env python3
"""
Cross-platform Docker launcher for Medical RAG.
Checks for Docker, prompts installation if missing, starts containers,
shows live ingestion progress, and opens browser when ready.

Compiled into .exe (Windows) or .app (macOS) via PyInstaller.
"""

import os
import platform
import subprocess
import sys
import time
import webbrowser
import urllib.request
import urllib.error


APP_NAME = "Medical Research RAG"
HEALTH_URL = "http://localhost:8000/health"
CONTAINER_NAME = "medical-rag-app"
DOCKER_INSTALL_URLS = {
    "Windows": "https://docs.docker.com/desktop/setup/install/windows-install/",
    "Darwin": "https://docs.docker.com/desktop/setup/install/mac-install/",
    "Linux": "https://docs.docker.com/engine/install/",
}


def get_app_dir():
    """Get the directory where docker-compose.yml lives.

    For a macOS .app bundle, navigate out of Contents/MacOS/ to the folder
    containing the .app. For a plain exe (Windows/Linux), use its directory.
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        # If we're inside a macOS .app bundle (.../MedicalRAG-Docker.app/Contents/MacOS),
        # walk up to the folder containing the .app
        if "/Contents/MacOS" in exe_dir.replace(os.sep, "/"):
            # exe_dir ends with .app/Contents/MacOS — go up three levels
            parent = os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
            return parent
        return exe_dir
    else:
        return os.path.dirname(os.path.abspath(__file__))


def print_banner():
    print("=" * 55)
    print(f"  {APP_NAME} - Docker Edition")
    print("=" * 55)
    print()


def check_docker_installed():
    """Check if Docker CLI is available."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_docker_running():
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def prompt_docker_install():
    """Prompt user to install Docker Desktop."""
    system = platform.system()
    url = DOCKER_INSTALL_URLS.get(system, DOCKER_INSTALL_URLS["Linux"])

    print("Docker is not installed on this system.")
    print()
    print("Docker Desktop is required to run this application.")
    print(f"Download it from: {url}")
    print()

    try:
        answer = input("Open the Docker download page in your browser? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            webbrowser.open(url)
            print()
            print("After installing Docker Desktop:")
            print("  1. Start Docker Desktop")
            print("  2. Wait for it to finish starting (whale icon in taskbar)")
            print("  3. Run this application again")
    except (EOFError, KeyboardInterrupt):
        pass

    print()
    input("Press Enter to exit...")
    sys.exit(1)


def prompt_docker_start():
    """Prompt user to start Docker Desktop."""
    print("Docker is installed but not running.")
    print()
    print("Please start Docker Desktop:")

    system = platform.system()
    if system == "Windows":
        print('  - Search for "Docker Desktop" in the Start menu')
    elif system == "Darwin":
        print("  - Open Docker from Applications or Spotlight")
    else:
        print("  - Run: sudo systemctl start docker")

    print("  - Wait for it to fully start (this takes ~30 seconds)")
    print()

    try:
        answer = input("Wait for Docker to start? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            print()
            print("Waiting for Docker to start", end="", flush=True)
            for _ in range(60):
                if check_docker_running():
                    print(" Ready!")
                    return True
                print(".", end="", flush=True)
                time.sleep(3)
            print()
            print("Docker did not start in time. Please start it manually and try again.")
    except (EOFError, KeyboardInterrupt):
        pass

    input("Press Enter to exit...")
    sys.exit(1)


def cleanup_stale_containers():
    """Remove stale containers from previous runs that might conflict."""
    stale = ["medical-rag-ollama", "medical-rag-app"]
    for name in stale:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, text=True, timeout=30
        )


def run_docker_compose(app_dir):
    """Start the Docker containers."""
    print("[Step 1/3] Starting Docker containers...")
    print("  (First run builds the image and downloads AI models - this takes 5-15 min)")
    print()

    # Clean up any leftover containers from previous runs
    cleanup_stale_containers()

    result = subprocess.run(
        ["docker", "compose", "up", "--build", "-d"],
        cwd=app_dir,
        capture_output=False,
        timeout=600
    )

    if result.returncode != 0:
        print()
        print("Failed to start containers. Check Docker Desktop is running.")
        input("Press Enter to exit...")
        sys.exit(1)


def format_log_line(line):
    """Clean up a container log line for display."""
    line = line.strip()
    if not line:
        return None
    # Remove timestamp prefix (e.g. "2026-04-09 12:00:00,123 - medical_rag - INFO - ")
    if " - medical_rag - " in line:
        line = line.split(" - medical_rag - ", 1)[-1]
        # Remove log level prefix
        for prefix in ("INFO - ", "WARNING - ", "ERROR - "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
    # Skip noisy/irrelevant lines
    skip_patterns = ["GET /", "POST /", "HTTP/1.1", "Loaded progress:", "uvicorn", "Application startup"]
    if any(p in line for p in skip_patterns):
        return None
    return line[:120] if line else None


def get_container_logs(since_seconds=6):
    """Get recent log lines from the app container."""
    try:
        result = subprocess.run(
            ["docker", "logs", CONTAINER_NAME, "--since", f"{since_seconds}s"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            text = result.stdout + result.stderr
            lines = []
            for raw in text.strip().split("\n"):
                cleaned = format_log_line(raw)
                if cleaned:
                    lines.append(cleaned)
            return lines
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def check_health():
    """Check if the app health endpoint returns 200."""
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        # 503 = still ingesting, not an error to show
        return False
    except (urllib.error.URLError, OSError, ValueError):
        # Connection refused = containers still starting
        return False


def wait_for_ready():
    """Poll health endpoint, showing live container logs."""
    print("[Step 2/3] Waiting for application to be ready...")
    print()

    shown = set()
    while True:
        if check_health():
            return

        # Show new log lines from the container
        for line in get_container_logs():
            if line not in shown:
                print(f"  {line}")
                shown.add(line)
                # Keep the set from growing forever
                if len(shown) > 500:
                    shown = set(list(shown)[-200:])

        time.sleep(5)


def open_browser():
    """Open the app in the default browser."""
    print()
    print("[Step 3/3] Opening browser...")
    print()
    print("=" * 55)
    print(f"  {APP_NAME} is ready!")
    print("  http://localhost:8000")
    print("=" * 55)
    print()
    webbrowser.open("http://localhost:8000")


def stop_containers(app_dir):
    """Stop Docker containers."""
    print("Stopping containers...")
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=app_dir,
        capture_output=True,
        timeout=60
    )
    print("Stopped.")


def main():
    app_dir = get_app_dir()
    os.chdir(app_dir)

    print_banner()

    # Check Docker
    print("Checking Docker installation...")
    if not check_docker_installed():
        prompt_docker_install()
        return

    print("  Docker is installed.")

    if not check_docker_running():
        prompt_docker_start()

    print("  Docker is running.")
    print()

    # Verify docker-compose.yml exists
    compose_file = os.path.join(app_dir, "docker-compose.yml")
    if not os.path.exists(compose_file):
        print(f"ERROR: docker-compose.yml not found in {app_dir}")
        print("Make sure this executable is in the same folder as docker-compose.yml")
        input("Press Enter to exit...")
        sys.exit(1)

    # Start containers
    run_docker_compose(app_dir)
    print()

    # Wait for ready
    try:
        wait_for_ready()
    except KeyboardInterrupt:
        print()
        print()
        stop_containers(app_dir)
        sys.exit(0)

    # Open browser
    open_browser()

    # Keep running
    print("The application is running in Docker.")
    print("To stop: close this window or press Ctrl+C")
    print()

    try:
        while True:
            time.sleep(60)
            if not check_health():
                print("  Application appears to have stopped. Check Docker Desktop.")
    except KeyboardInterrupt:
        print()
        stop_containers(app_dir)


if __name__ == "__main__":
    main()
