# Medical RAG - Native Installation Guide

## Overview

Medical RAG is now available as a native desktop application for **macOS** and **Windows**. No Docker required!

## Prerequisites

### Required: Ollama

Medical RAG requires **Ollama** to be installed for AI model inference.

#### macOS

```bash
# Option 1: Homebrew
brew install ollama

# Option 2: Download installer
# Visit: https://ollama.com/download
```

#### Windows

1. Visit https://ollama.com/download
2. Download "Ollama for Windows"
3. Run the installer
4. Ollama will start automatically

#### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

---

## Installation

### macOS

#### Option 1: DMG Installer (Recommended)

1. Download `MedicalRAG-v1.0.0.dmg`
2. Open the DMG file
3. Drag **Medical RAG.app** to your Applications folder
4. Launch from Applications or Spotlight

#### Option 2: .app Bundle

1. Download the `.app` bundle
2. Move to `/Applications/`
3. Right-click → Open (first time only, due to Gatekeeper)

**First Launch:**
- The app will check for Ollama
- Required models will be downloaded automatically (~1.2 GB)
- This may take 5-10 minutes on first run
- Your browser will open automatically to http://localhost:8000

### Windows

#### Option 1: Installer (Recommended)

1. Download `MedicalRAG-Setup-v1.0.0.exe`
2. Run the installer
3. Follow the installation wizard
4. Launch from Start Menu or Desktop shortcut

#### Option 2: Portable Executable

1. Download the `.exe` file
2. Place in a folder of your choice
3. Double-click to run

**First Launch:**
- The app will check for Ollama
- Required models will be downloaded automatically (~1.2 GB)
- This may take 5-10 minutes on first run
- Your browser will open automatically to http://localhost:8000

---

## First Run Setup

### 1. Model Download

On first launch, Medical RAG will automatically download required AI models:

- **deepseek-r1:1.5b** (~1.1 GB) - Main reasoning model
- **nomic-embed-text** (~270 MB) - Embedding model

**Total download:** ~1.4 GB

This is a one-time download. Subsequent launches will be instant.

### 2. User Data Location

Medical RAG stores your data in platform-specific locations:

#### macOS
```
~/Library/Application Support/MedicalRAG/
├── pdfs/          # Your PDF documents
├── vector_db/     # Embedded knowledge base
├── data/          # Cache and progress files
├── logs/          # Application logs
└── .env           # Configuration (optional)
```

#### Windows
```
%APPDATA%\MedicalRAG\
├── pdfs\          # Your PDF documents
├── vector_db\     # Embedded knowledge base
├── data\          # Cache and progress files
├── logs\          # Application logs
└── .env           # Configuration (optional)
```

### 3. Adding Documents

1. **Option A:** Use the web interface
   - Open http://localhost:8000
   - Click "Upload PDFs"
   - Select your documents

2. **Option B:** Drop files in the pdfs folder
   - Navigate to the user data directory (see above)
   - Copy PDFs to the `pdfs/` folder
   - Restart the application

---

## Usage

### Starting the Application

**macOS:**
- Open from Applications folder
- Or use Spotlight: Press Cmd+Space, type "Medical RAG"

**Windows:**
- Start Menu → Medical RAG
- Or use Desktop shortcut

### Using the Application

1. Application starts automatically
2. Browser opens to http://localhost:8000
3. Upload PDFs or use pre-loaded documents
4. Ask questions in the search box
5. Get AI-powered answers with sources

### Stopping the Application

- **macOS:** Cmd+Q or close from Dock
- **Windows:** Close the console window or click X
- **Both:** Press Ctrl+C in the terminal/console

---

## Configuration

### Advanced Settings

Create or edit `.env` file in your user data directory:

```env
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:1.5b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# RAG Settings
TOP_K_RESULTS=5
TEMPERATURE=0.1
MAX_TOKENS=2048

# Chunking
CHUNK_SIZE=512
CHUNK_OVERLAP=50
```

Restart the application for changes to take effect.

---

## Troubleshooting

### "Ollama not found"

**Solution:** Install Ollama (see Prerequisites above)

### "Failed to download models"

**Causes:**
- No internet connection
- Firewall blocking Ollama
- Insufficient disk space (~1.5 GB required)

**Solution:**
1. Check internet connection
2. Manually download models:
   ```bash
   ollama pull deepseek-r1:1.5b
   ollama pull nomic-embed-text
   ```

### "Port 8000 already in use"

**Cause:** Another application is using port 8000

**Solution:**
1. Close other applications
2. Or change port in `.env`:
   ```env
   PORT=8001
   ```

### Application won't start

**macOS:**
- Check Gatekeeper: Right-click app → Open
- View logs: `~/Library/Application Support/MedicalRAG/logs/`

**Windows:**
- Run as Administrator
- Check Windows Defender
- View logs: `%APPDATA%\MedicalRAG\logs\`

### Slow performance

**M1/M2 Mac:** Make sure you're using native Ollama (not Docker)

**Performance varies by CPU:**
- M1/M2 Mac with Metal GPU: ~30-50 tokens/sec
- Modern CPU only: ~5-15 tokens/sec
- Older systems: May be very slow

---

## Uninstallation

### macOS

1. Delete app: Drag **Medical RAG.app** to Trash
2. Delete user data (optional):
   ```bash
   rm -rf ~/Library/Application\ Support/MedicalRAG
   ```

### Windows

1. Run uninstaller from Control Panel → Programs
2. Or delete executable and folder
3. Delete user data (optional):
   ```
   rmdir /s "%APPDATA%\MedicalRAG"
   ```

### Keep Your Data

If you want to keep your PDFs and knowledge base:
- Backup the user data folder before uninstalling
- Restore after reinstalling

---

## Support

For issues, questions, or feature requests:

1. Check this guide first
2. Review logs in the user data directory
3. Create an issue on GitHub (if open source)

---

## System Requirements

### Minimum

- **OS:** macOS 11+ or Windows 10+
- **RAM:** 4 GB
- **Disk:** 5 GB free (includes models)
- **Internet:** Required for first-time model download

### Recommended

- **OS:** macOS 12+ (M1/M2) or Windows 11
- **RAM:** 8 GB+
- **Disk:** 10 GB+ free
- **CPU:** Modern multi-core processor
- **GPU:** M1/M2 chip (Mac) for best performance
