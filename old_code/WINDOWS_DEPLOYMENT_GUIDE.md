# Windows Deployment Guide
## Medical Research RAG Pipeline - Complete Installation Process

This guide explains how to transfer your Medical Research RAG system from Mac to Windows and create a professional installer.

---

## Overview

Your project is **ready for Windows deployment!** All necessary files are in place:
- ✅ Docker configuration (docker-compose.yml, Dockerfile)
- ✅ Windows batch scripts (START_APP.bat, STOP_APP.bat, etc.)
- ✅ Inno Setup installer configuration (installer.iss)
- ✅ Comprehensive documentation
- ✅ Backup/restore tools
- ✅ LICENSE and .dockerignore files

**What you get:** A professional `MedicalResearchRAG_Setup.exe` installer that users can download and install with one click.

---

## Phase 1: Transfer Project to Windows

### Option A: Using GitHub (Recommended)

1. **On your Mac:**
   ```bash
   cd "/Users/User/healthcare project"
   git add .
   git commit -m "Prepare Windows installer configuration"
   git push origin main
   ```

2. **On Windows machine:**
   ```powershell
   # Open PowerShell or Command Prompt
   cd C:\
   mkdir Projects
   cd Projects
   git clone https://github.com/MoCode98/medical-research-rag.git
   cd medical-research-rag
   ```

### Option B: Direct Transfer

1. **Copy entire project folder** from Mac to Windows via:
   - USB drive
   - Network share
   - OneDrive/Dropbox/Google Drive

2. **Place in:** `C:\Projects\medical-research-rag\` (or your preferred location)

---

## Phase 2: Install Prerequisites on Windows

### 1. Install Inno Setup Compiler

**Download:** https://jrsoftware.org/isdl.php

**Steps:**
1. Download `innosetup-6.x.x.exe` (latest version)
2. Run the installer
3. Accept default installation options
4. Verify installation: Start Menu → Inno Setup → Inno Setup Compiler

### 2. Verify Docker Desktop (Optional - for testing)

If you want to test the application before building the installer:

**Download:** https://www.docker.com/products/docker-desktop/

**Note:** End users will install Docker Desktop when they run your installer. You don't need it to *build* the installer, only to *test* it.

---

## Phase 3: Build the Installer

### Method 1: Using Inno Setup GUI (Easiest)

1. **Open Inno Setup Compiler** from Start Menu

2. **Open the script:**
   - File → Open
   - Navigate to: `C:\Projects\medical-research-rag\installer.iss`
   - Click Open

3. **Compile:**
   - Click: Build → Compile (or press Ctrl+F9)
   - Wait for compilation to complete (~30 seconds)

4. **Verify output:**
   - Check: `C:\Projects\medical-research-rag\installer_output\`
   - You should see: `MedicalResearchRAG_Setup.exe` (~25-30MB)

### Method 2: Using Command Line

```powershell
cd "C:\Projects\medical-research-rag"
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

**Output will be in:** `installer_output\MedicalResearchRAG_Setup.exe`

---

## Phase 4: Test the Installer

### Before Distributing - Test on Clean System

1. **Copy installer to test location:**
   ```powershell
   copy installer_output\MedicalResearchRAG_Setup.exe C:\Users\YourName\Desktop\
   ```

2. **Run installer:**
   - Double-click `MedicalResearchRAG_Setup.exe`
   - Follow installation wizard
   - Choose installation location (default: `C:\Program Files\MedicalResearchRAG`)

3. **Verify installation:**
   - Check Start Menu → Medical Research RAG Pipeline
   - You should see 7 shortcuts:
     1. Start Medical RAG
     2. Stop Medical RAG
     3. Check Status
     4. Download AI Models
     5. Debug Ingestion
     6. Open Web Interface
     7. Uninstall

### Test Core Functionality

1. **Start the application:**
   - Start Menu → Medical Research RAG Pipeline → Start Medical RAG
   - First time: Will prompt to download models (~5GB)
   - Containers will start (takes ~2 minutes first time)

2. **Verify web interface:**
   - Browser should auto-open to: http://localhost:8000
   - Check all 3 tabs: Ingest, Query, Metrics

3. **Test PDF ingestion:**
   - Go to: `C:\Program Files\MedicalResearchRAG\pdfs\`
   - PDFs should already be there from installation
   - Check web UI → Ingest tab for ingestion status

4. **Test query:**
   - Web UI → Query tab
   - Enter: "What are the risk factors for stroke?"
   - Verify answer with sources

5. **Test backup:**
   - Navigate to: `C:\Program Files\MedicalResearchRAG\scripts\`
   - Run: `backup.bat`
   - Verify backup created in: `C:\Program Files\MedicalResearchRAG\backups\`

6. **Test stop:**
   - Start Menu → Medical Research RAG Pipeline → Stop Medical RAG
   - Verify containers stopped: `docker ps` should show no medical-rag containers

### Test Uninstallation

1. **Uninstall:**
   - Control Panel → Programs and Features
   - Find: "Medical Research RAG Pipeline"
   - Click Uninstall

2. **Verify clean removal:**
   - Check: `C:\Program Files\MedicalResearchRAG\` should be deleted
   - Start Menu shortcuts should be removed

---

## Phase 5: Distribute the Installer

### Option A: GitHub Releases (Recommended)

1. **Create release on GitHub:**
   ```powershell
   # Make sure git is installed and you're in the project directory
   git tag v1.0.0
   git push origin v1.0.0
   ```

2. **Upload installer:**
   - Go to: https://github.com/MoCode98/medical-research-rag/releases
   - Click "Draft a new release"
   - Tag: v1.0.0
   - Title: "Medical Research RAG Pipeline v1.0.0"
   - Description: (See template below)
   - Attach file: `MedicalResearchRAG_Setup.exe`
   - Click "Publish release"

**Release Description Template:**
```markdown
# Medical Research RAG Pipeline v1.0.0

Professional RAG system for medical research with Ollama AI.

## Features
- 🔍 Semantic search across medical research papers
- 🤖 AI-powered question answering with DeepSeek-R1 7B
- 📄 Automatic PDF ingestion and chunking
- 🌐 Modern web interface with real-time updates
- 💾 Built-in backup and restore tools
- 🐳 Docker-based deployment (cross-platform)

## Installation

1. **Download:** `MedicalResearchRAG_Setup.exe` (below)
2. **Run installer** and follow prompts
3. **Install Docker Desktop** if prompted
4. **Start application:** Start Menu → Medical Research RAG Pipeline → Start Medical RAG
5. **Open browser:** http://localhost:8000

## Requirements
- Windows 10/11 64-bit
- 8GB RAM minimum (16GB recommended)
- 20GB free disk space (for models and data)
- Docker Desktop (installer will prompt if missing)

## Documentation
Included in installation:
- WINDOWS_INSTALLER_README.txt (Quick start guide)
- DOCKER_SETUP.md (Detailed setup instructions)
- WINDOWS_INGESTION_TROUBLESHOOTING.md (Debug guide)

## Support
- 📖 Full README: [Link to README.md]
- 🐛 Report issues: [Link to Issues]
```

### Option B: Direct Download Link

1. **Upload to file hosting:**
   - Google Drive
   - Dropbox
   - OneDrive
   - Your own web server

2. **Share link** with download instructions

---

## Troubleshooting

### Build Errors

**Error: "Cannot find LICENSE file"**
- Solution: LICENSE file exists, make sure you're in the correct directory

**Error: "Cannot find source file"**
- Solution: Run Inno Setup from the project root directory
- Ensure all paths in installer.iss are correct

**Error: "Permission denied"**
- Solution: Run Inno Setup as Administrator
- Right-click → Run as Administrator

### Installer Errors

**"Docker Desktop not installed" prompt**
- This is normal! Users need Docker Desktop
- Installer will prompt them to download it

**Installation fails**
- Check disk space (need ~100MB for installation)
- Verify user has admin rights (or install to user directory)

**Shortcuts not created**
- Reinstall with "Create Start Menu shortcuts" checked
- Verify Windows user has permission to write to Start Menu

### Runtime Errors

**Docker containers won't start**
- Verify Docker Desktop is running
- Check WSL2 is installed (Windows 10/11 requirement)
- Run: `docker compose up -d` from installation directory

**Web interface doesn't open**
- Check containers are running: `docker ps`
- Verify port 8000 is not in use by another application
- Manually open: http://localhost:8000

**Models download fails**
- Check internet connection
- Models are large (~5GB) - download takes 10-30 minutes
- Can manually download: Start Menu → Download AI Models

---

## What Gets Installed

### Installation Directory Structure
```
C:\Program Files\MedicalResearchRAG\
├── api/                          # API endpoints
├── src/                          # Core source code
├── static/                       # Web UI files
├── scripts/                      # Backup/restore/metadata tools
├── pdfs/                         # Medical research papers
├── vector_db/                    # ChromaDB database (created on first run)
├── data/                         # Cache and progress files
├── logs/                         # Application logs
├── docker-compose.yml            # Docker configuration
├── Dockerfile                    # Container build instructions
├── requirements.txt              # Python dependencies
├── app.py                        # FastAPI application
├── *.bat                         # Windows batch scripts
└── *.md, *.txt                   # Documentation
```

### Start Menu Shortcuts
```
Start Menu\Programs\Medical Research RAG Pipeline\
├── Start Medical RAG              # Launches containers
├── Stop Medical RAG               # Stops containers
├── Check Status                   # Shows container health
├── Download AI Models             # Downloads LLM models
├── Debug Ingestion                # Troubleshooting tool
├── Open Web Interface             # Opens http://localhost:8000
└── Uninstall                      # Removes application
```

---

## Advanced: Customizing the Installer

### Change Application Name/Version

Edit `installer.iss` lines 11-14:
```iss
#define MyAppName "Medical Research RAG Pipeline"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "YourName"
#define MyAppURL "https://github.com/YourUsername/your-repo"
```

### Add Custom Icon

1. Create or download a 256x256 PNG icon
2. Convert to ICO format (use online tool: https://convertio.co/png-ico/)
3. Save as `icon.ico` in project root
4. Edit `installer.iss` line 33:
   ```iss
   SetupIconFile=icon.ico
   ```

### Change Installation Directory

Edit `installer.iss` line 26:
```iss
DefaultDirName={autopf}\MedicalResearchRAG
```

Options:
- `{autopf}` = Program Files (requires admin)
- `{localappdata}` = C:\Users\Username\AppData\Local (no admin needed)
- `{userdocs}` = Documents folder

### Require Administrator Rights

Edit `installer.iss` line 30:
```iss
PrivilegesRequired=admin
```

---

## Support and Next Steps

### Your Project Status
- ✅ All files ready for Windows deployment
- ✅ Installer configuration complete
- ✅ Documentation comprehensive
- ✅ Backup/restore tools included
- ✅ Professional batch scripts
- ✅ Docker setup optimized for Windows

### Recommended Next Steps

1. **Build installer on Windows** (15 minutes)
2. **Test thoroughly** (1 hour)
3. **Upload to GitHub Releases** (15 minutes)
4. **Share with users** (ongoing)

### Future Enhancements

Consider adding:
- Custom icon.ico for professional look
- Auto-update mechanism
- Usage analytics (privacy-respecting)
- More language models (Llama, Mistral)
- Advanced RAG features (re-ranking, hybrid search)

---

## Quick Reference Commands

### Building Installer
```powershell
cd "C:\Projects\medical-research-rag"
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

### Testing Installation
```powershell
# Install
.\installer_output\MedicalResearchRAG_Setup.exe

# Check containers
docker ps

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Development
```powershell
# Rebuild containers
docker compose build --no-cache

# Start in foreground (see logs)
docker compose up

# Run backup
.\scripts\backup.bat
```

---

## Conclusion

Your Medical Research RAG system is **production-ready** for Windows deployment!

The installer provides a **professional, user-friendly experience** with:
- One-click installation
- Automatic dependency checking
- Start Menu shortcuts
- Built-in troubleshooting
- Clean uninstallation

**Total deployment time:** ~2 hours (mostly testing)

**End result:** Professional Windows installer that anyone can use!

Good luck with your deployment! 🚀
