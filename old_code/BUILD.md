# Medical RAG - Build Documentation

This guide explains how to build native executables for macOS and Windows.

## Prerequisites

### All Platforms

- Python 3.10 or higher
- Git (for cloning repository)
- 5GB+ free disk space

### macOS

```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12
brew install python@3.12

# Install create-dmg (for DMG creation)
brew install create-dmg

# Install Ollama (for testing)
brew install ollama
```

### Windows

1. Install Python 3.10+ from https://python.org/downloads
   - Check "Add Python to PATH" during installation
2. Install Ollama from https://ollama.com/download
3. (Optional) Install Inno Setup for creating installers: https://jrsoftware.org/isinfo.php

---

## Building for macOS

### 1. Clone and Setup

```bash
# Clone repository
git clone <repository-url>
cd healthcare-project

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install production dependencies
pip install --upgrade pip
pip install -r requirements-prod.txt
```

### 2. Run Build Script

```bash
# Make script executable (first time only)
chmod +x build_macos.sh

# Run build
./build_macos.sh
```

### 3. Output

The script creates:

- `dist/MedicalRAG.app` - Application bundle
- `dist/MedicalRAG-v1.0.0.dmg` - DMG installer (if create-dmg installed)

### 4. Test

```bash
# Test the app
open dist/MedicalRAG.app
```

### Manual Build (if script fails)

```bash
# Activate venv
source venv/bin/activate

# Clean previous builds
rm -rf build dist

# Run PyInstaller
pyinstaller build_macos.spec

# Create DMG manually
create-dmg \
    --volname "MedicalRAG" \
    --window-pos 200 120 \
    --window-size 800 400 \
    --icon-size 100 \
    --icon "MedicalRAG.app" 200 190 \
    --hide-extension "MedicalRAG.app" \
    --app-drop-link 600 185 \
    "dist/MedicalRAG-v1.0.0.dmg" \
    "dist/MedicalRAG.app"
```

---

## Building for Windows

### 1. Clone and Setup

```batch
REM Clone repository
git clone <repository-url>
cd healthcare-project

REM Create virtual environment
python -m venv venv
venv\Scripts\activate.bat

REM Install production dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements-prod.txt
```

### 2. Run Build Script

```batch
REM Run build
build_windows.bat
```

### 3. Output

The script creates:

- `dist\MedicalRAG\MedicalRAG.exe` - Executable
- All required DLLs and dependencies in `dist\MedicalRAG\`

### 4. Test

```batch
REM Test the executable
dist\MedicalRAG\MedicalRAG.exe
```

### Manual Build (if script fails)

```batch
REM Activate venv
venv\Scripts\activate.bat

REM Clean previous builds
rmdir /s /q build
rmdir /s /q dist

REM Run PyInstaller
pyinstaller build_windows.spec
```

---

## Creating Installers

### macOS DMG

The `build_macos.sh` script automatically creates a DMG if `create-dmg` is installed.

**Manual DMG Creation:**

```bash
create-dmg \
    --volname "MedicalRAG" \
    --volicon "icon.icns" \
    --window-pos 200 120 \
    --window-size 800 400 \
    --icon-size 100 \
    --icon "MedicalRAG.app" 200 190 \
    --hide-extension "MedicalRAG.app" \
    --app-drop-link 600 185 \
    "MedicalRAG-v1.0.0.dmg" \
    "dist/MedicalRAG.app"
```

### Windows Installer (Inno Setup)

Create `installer.iss`:

```iss
[Setup]
AppName=Medical RAG
AppVersion=1.0.0
DefaultDirName={pf}\MedicalRAG
DefaultGroupName=Medical RAG
OutputDir=dist
OutputBaseFilename=MedicalRAG-Setup-v1.0.0
Compression=lzma2
SolidCompression=yes

[Files]
Source: "dist\MedicalRAG\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Medical RAG"; Filename: "{app}\MedicalRAG.exe"
Name: "{commondesktop}\Medical RAG"; Filename: "{app}\MedicalRAG.exe"

[Run]
Filename: "{app}\MedicalRAG.exe"; Description: "Launch Medical RAG"; Flags: postinstall nowait
```

Compile with:

```batch
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

---

## Troubleshooting

### "Module not found" errors

**Cause:** Missing dependencies in PyInstaller spec

**Solution:** Add to `hiddenimports` in `.spec` file:

```python
hiddenimports = [
    'missing.module',
    # ... other imports
]
```

### Build succeeds but app won't run

**Check:**
1. Test in terminal to see error messages
2. Check included data files in `.spec`
3. Verify all dependencies are in `requirements-prod.txt`

**macOS:**
```bash
# Run from terminal to see errors
./dist/MedicalRAG.app/Contents/MacOS/MedicalRAG
```

**Windows:**
```batch
REM Run from command prompt to see errors
dist\MedicalRAG\MedicalRAG.exe
```

### Large executable size

**Current size:** ~400-500 MB (includes Python runtime + dependencies)

**To reduce:**
1. Remove unused imports
2. Use UPX compression (enabled by default)
3. Exclude unnecessary packages in `.spec`:

```python
excludes=[
    'pytest',
    'IPython',
    'jupyter',
    # Add more if not needed
]
```

### "Application is damaged" (macOS)

**Cause:** Gatekeeper security on unsigned apps

**Solution:**
```bash
# Remove quarantine attribute
xattr -cr dist/MedicalRAG.app
```

**Or sign the app:**
```bash
# Requires Apple Developer account
codesign --deep --force --sign "Developer ID" dist/MedicalRAG.app
```

---

## Build Configuration

### PyInstaller Specs

Build configuration is in:
- `build_macos.spec` - macOS configuration
- `build_windows.spec` - Windows configuration

### Key Settings

**Include data files:**
```python
datas = [
    ('static', 'static'),  # Web UI
    ('src', 'src'),        # Source code
    ('api', 'api'),        # API modules
]
```

**Hide imports (if not auto-detected):**
```python
hiddenimports = [
    'uvicorn.logging',
    'chromadb',
    # ... more modules
]
```

**Exclude unnecessary packages:**
```python
excludes = [
    'pytest',
    'black',
    'mypy',
]
```

---

## CI/CD Integration

### GitHub Actions Example

Create `.github/workflows/build.yml`:

```yaml
name: Build Native Apps

on:
  push:
    tags:
      - 'v*'

jobs:
  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements-prod.txt
          brew install create-dmg
      - name: Build
        run: ./build_macos.sh
      - name: Upload artifact
        uses: actions/upload-artifact@v2
        with:
          name: MedicalRAG-macOS
          path: dist/*.dmg

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -r requirements-prod.txt
      - name: Build
        run: .\build_windows.bat
      - name: Upload artifact
        uses: actions/upload-artifact@v2
        with:
          name: MedicalRAG-Windows
          path: dist\MedicalRAG
```

---

## Version Management

Update version in multiple files:

1. `build_macos.spec` - `VERSION = '1.0.0'`
2. `build_windows.spec` - `VERSION = '1.0.0'`
3. `build_macos.sh` - `VERSION="1.0.0"`
4. `build_windows.bat` - `set VERSION=1.0.0`

Consider using a script to sync versions:

```python
# scripts/update_version.py
import re

VERSION = "1.0.0"

files = {
    "build_macos.spec": r"VERSION = '[^']*'",
    "build_windows.spec": r"VERSION = '[^']*'",
    "build_macos.sh": r'VERSION="[^"]*"',
    "build_windows.bat": r'set VERSION=[^\r\n]*',
}

for file, pattern in files.items():
    with open(file, 'r') as f:
        content = f.read()

    new_content = re.sub(pattern, f"VERSION = '{VERSION}'", content)

    with open(file, 'w') as f:
        f.write(new_content)

print(f"Updated version to {VERSION}")
```

---

## Testing Builds

### Automated Testing

Create `tests/test_build.py`:

```python
import subprocess
import sys
from pathlib import Path

def test_app_starts():
    """Test that built app starts without errors."""
    if sys.platform == "darwin":
        app_path = Path("dist/MedicalRAG.app/Contents/MacOS/MedicalRAG")
    else:
        app_path = Path("dist/MedicalRAG/MedicalRAG.exe")

    assert app_path.exists(), f"App not found: {app_path}"

    # Try to start (will fail without Ollama, but should load)
    proc = subprocess.Popen(
        [str(app_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give it a moment
    import time
    time.sleep(2)

    proc.terminate()

    # Check it didn't crash immediately
    assert proc.poll() is None or proc.returncode == 0
```

### Manual Testing Checklist

- [ ] App launches without errors
- [ ] Ollama detection works
- [ ] Models download automatically
- [ ] Browser opens automatically
- [ ] PDFs can be uploaded
- [ ] Queries return results
- [ ] User data persists after restart
- [ ] App can be quit gracefully

---

## Distribution

### macOS

**Upload to:**
- GitHub Releases
- Direct download link
- (Optional) Mac App Store (requires signing + review)

**Requirements:**
- Sign with Developer ID for Gatekeeper
- Notarize for macOS 10.15+

### Windows

**Upload to:**
- GitHub Releases
- Direct download link
- (Optional) Microsoft Store

**Requirements:**
- (Optional) Code signing certificate for SmartScreen

---

## Support

For build issues:

1. Check this guide
2. Review PyInstaller documentation
3. Check GitHub issues
4. Create new issue with build logs
