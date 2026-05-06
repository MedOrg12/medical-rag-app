#!/usr/bin/env python3
"""
Create a portable distribution package of the Medical Research RAG system.
This script packages the entire project for easy distribution and deployment.
"""

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

# Project version
VERSION = "2.1.0"

# Files and directories to include
INCLUDE_FILES = [
    "src/",
    "ingest.py",
    "query.py",
    "query_enhanced.py",
    "requirements.txt",
    "README.md",
    "QUICKSTART.md",
    "INSTALLATION.md",
    "IMPROVEMENTS.md",
    "V2.1_FEATURES.md",
    "COMPLETE_IMPLEMENTATION_SUMMARY.md",
    ".env.example",
    "Modelfile.example",
]

# Files to exclude
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    "*.egg-info",
    ".DS_Store",
]


def create_setup_scripts():
    """Create setup scripts for different platforms."""

    # Unix setup script
    unix_setup = f"""#!/bin/bash
# Medical Research RAG - Automated Setup Script
# For macOS and Linux

set -e

echo "=================================="
echo "Medical Research RAG v{VERSION}"
echo "Automated Setup"
echo "=================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || {{ echo "Error: Python 3 not found. Please install Python 3.10+"; exit 1; }}

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python $REQUIRED_VERSION or higher required. Found $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION found"
echo ""

# Check for Ollama
echo "Checking for Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "Ollama not found. Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✓ Ollama installed"
else
    echo "✓ Ollama already installed"
fi
echo ""

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
echo "✓ Virtual environment created"
echo ""

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# Create necessary directories
echo "Creating directories..."
mkdir -p pdfs data logs chroma_db
echo "✓ Directories created"
echo ""

# Copy example .env if not exists
if [ ! -f .env ]; then
    echo "Creating .env configuration..."
    cp .env.example .env
    echo "✓ .env created from template"
else
    echo "✓ .env already exists"
fi
echo ""

# Pull Ollama models
echo "Pulling required Ollama models..."
echo "This may take several minutes depending on your connection..."
ollama pull nomic-embed-text
ollama pull llama3.2:3b
echo "✓ Models downloaded"
echo ""

echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Activate the environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. Add your PDF files to the 'pdfs' folder"
echo ""
echo "3. Run ingestion:"
echo "   python ingest.py"
echo ""
echo "4. Start querying:"
echo "   python query_enhanced.py --interactive --all-features"
echo ""
echo "For more information, see INSTALLATION.md and QUICKSTART.md"
echo ""
"""

    # Windows setup script
    windows_setup = f"""@echo off
REM Medical Research RAG - Automated Setup Script
REM For Windows

echo ==================================
echo Medical Research RAG v{VERSION}
echo Automated Setup
echo ==================================
echo.

REM Check Python version
echo Checking Python version...
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.10+
    exit /b 1
)
echo Python found
echo.

REM Check for Ollama
echo Checking for Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
    echo Ollama not found. Please install Ollama from:
    echo https://ollama.com/download
    echo.
    echo After installing Ollama, run this script again.
    pause
    exit /b 1
)
echo Ollama found
echo.

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Error creating virtual environment
    exit /b 1
)
echo Virtual environment created
echo.

REM Activate and install dependencies
echo Installing dependencies...
call venv\\Scripts\\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Error installing dependencies
    exit /b 1
)
echo Dependencies installed
echo.

REM Create directories
echo Creating directories...
if not exist pdfs mkdir pdfs
if not exist data mkdir data
if not exist logs mkdir logs
if not exist chroma_db mkdir chroma_db
echo Directories created
echo.

REM Copy example .env
if not exist .env (
    echo Creating .env configuration...
    copy .env.example .env
    echo .env created from template
) else (
    echo .env already exists
)
echo.

REM Pull Ollama models
echo Pulling required Ollama models...
echo This may take several minutes...
ollama pull nomic-embed-text
ollama pull llama3.2:3b
echo Models downloaded
echo.

echo ==================================
echo Setup Complete!
echo ==================================
echo.
echo Next steps:
echo 1. Activate the environment:
echo    venv\\Scripts\\activate.bat
echo.
echo 2. Add your PDF files to the 'pdfs' folder
echo.
echo 3. Run ingestion:
echo    python ingest.py
echo.
echo 4. Start querying:
echo    python query_enhanced.py --interactive --all-features
echo.
echo For more information, see INSTALLATION.md and QUICKSTART.md
echo.
pause
"""

    return unix_setup, windows_setup


def create_manifest():
    """Create a manifest file with package information."""
    manifest = {
        "name": "Medical Research RAG",
        "version": VERSION,
        "created": datetime.now().isoformat(),
        "description": "A complete local RAG pipeline for medical research papers",
        "features": [
            "Hybrid Search (vector + keyword)",
            "Re-ranking for precision",
            "Conversation memory",
            "Enhanced metadata extraction",
            "Query expansion",
            "Enhanced PDF parsing (tables, figures, references)",
            "Question classification and adaptive retrieval",
        ],
        "requirements": {
            "python": ">=3.10",
            "ollama": "latest",
            "disk_space": "10GB",
            "ram": "8GB (16GB recommended)",
        },
        "included_files": INCLUDE_FILES,
    }
    return manifest


def should_exclude(path: Path) -> bool:
    """Check if a path should be excluded."""
    path_str = str(path)
    for pattern in EXCLUDE_PATTERNS:
        if pattern.replace("*", "") in path_str:
            return True
    return False


def create_portable_package():
    """Create the portable distribution package."""

    print(f"Creating Medical Research RAG v{VERSION} portable package...")
    print()

    # Create temporary build directory
    build_dir = Path("build/portable")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    # Copy files
    print("Copying files...")
    for item in INCLUDE_FILES:
        item_path = Path(item)

        if not item_path.exists():
            print(f"  ⚠️  Warning: {item} not found, skipping")
            continue

        if item_path.is_dir():
            # Copy directory
            dest = build_dir / item_path
            shutil.copytree(
                item_path,
                dest,
                ignore=lambda d, files: [f for f in files if should_exclude(Path(d) / f)],
            )
            print(f"  ✓ Copied directory: {item}")
        else:
            # Copy file
            dest = build_dir / item_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item_path, dest)
            print(f"  ✓ Copied file: {item}")

    # Create setup scripts
    print("\nCreating setup scripts...")
    unix_setup, windows_setup = create_setup_scripts()

    (build_dir / "setup.sh").write_text(unix_setup)
    (build_dir / "setup.sh").chmod(0o755)  # Make executable
    print("  ✓ Created setup.sh")

    (build_dir / "setup.bat").write_text(windows_setup)
    print("  ✓ Created setup.bat")

    # Create manifest
    print("\nCreating manifest...")
    manifest = create_manifest()
    (build_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print("  ✓ Created MANIFEST.json")

    # Create README for portable version
    print("\nCreating portable README...")
    portable_readme = f"""# Medical Research RAG v{VERSION} - Portable Distribution

This is a portable distribution of the Medical Research RAG system.

## Quick Start

### macOS/Linux:
```bash
./setup.sh
```

### Windows:
```cmd
setup.bat
```

The setup script will:
- Check Python installation
- Install Ollama if needed
- Create virtual environment
- Install dependencies
- Pull required models
- Create necessary directories

## After Setup

1. Add your PDF files to the `pdfs/` folder
2. Run ingestion: `python ingest.py`
3. Start querying: `python query_enhanced.py --interactive --all-features`

## Documentation

- **INSTALLATION.md** - Detailed installation instructions
- **QUICKSTART.md** - Quick start guide
- **IMPROVEMENTS.md** - Feature documentation
- **V2.1_FEATURES.md** - Latest features

## Requirements

- Python 3.10 or higher
- 8GB RAM (16GB recommended)
- 10GB free disk space
- Internet connection (for initial model download)

## Support

For issues or questions, see INSTALLATION.md troubleshooting section.

**Version:** {VERSION}
**Created:** {datetime.now().strftime("%Y-%m-%d")}
"""
    (build_dir / "README_PORTABLE.txt").write_text(portable_readme)
    print("  ✓ Created README_PORTABLE.txt")

    # Create ZIP archive
    print("\nCreating ZIP archive...")
    zip_filename = f"medical-rag-portable-v{VERSION}.zip"
    zip_path = Path(zip_filename)

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in build_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(build_dir.parent)
                zipf.write(file_path, arcname)

    # Get file size
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ Created {zip_filename} ({size_mb:.1f} MB)")

    # Clean up build directory
    shutil.rmtree("build")

    print()
    print("=" * 60)
    print("Package creation complete!")
    print("=" * 60)
    print()
    print(f"Package: {zip_filename}")
    print(f"Size: {size_mb:.1f} MB")
    print()
    print("To use this package:")
    print(f"1. Send {zip_filename} to target computer")
    print("2. Extract the ZIP file")
    print("3. Run setup.sh (Unix) or setup.bat (Windows)")
    print()
    print("The recipient will need:")
    print("- Python 3.10+")
    print("- Internet connection (for Ollama model download)")
    print("- 8GB+ RAM")
    print()


if __name__ == "__main__":
    try:
        create_portable_package()
    except Exception as e:
        print(f"\n❌ Error creating package: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
