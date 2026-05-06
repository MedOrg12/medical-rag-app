# Windows Build Checklist
## Quick Reference for Building the Installer

Use this checklist to ensure all steps are completed correctly.

---

## ☑️ Pre-Build Checklist (On Mac - COMPLETED)

- [x] LICENSE file exists
- [x] .dockerignore file exists
- [x] static/index.html exists
- [x] installer.iss updated with scripts/ folder
- [x] installer.iss includes DEBUG_INGESTION.bat
- [x] All Windows batch scripts present:
  - [x] START_APP.bat
  - [x] STOP_APP.bat
  - [x] CHECK_STATUS.bat
  - [x] DOWNLOAD_MODELS.bat
  - [x] DEBUG_INGESTION.bat
- [x] All documentation files present:
  - [x] README.md
  - [x] DOCKER_SETUP.md
  - [x] BUILD_INSTALLER.md
  - [x] WINDOWS_INSTALLER_README.txt
  - [x] WINDOWS_INGESTION_TROUBLESHOOTING.md
  - [x] WINDOWS_DEPLOYMENT_GUIDE.md (NEW)
- [x] scripts/ folder with backup/restore/metadata tools
- [x] Docker configuration files ready
- [x] API fixes applied (slowapi rate limiting)

**Status: ✅ ALL PRE-BUILD REQUIREMENTS COMPLETE**

---

## ☑️ Transfer to Windows

### Option A: GitHub
- [ ] Commit all changes on Mac
- [ ] Push to GitHub: `git push origin main`
- [ ] Clone on Windows: `git clone https://github.com/MoCode98/medical-research-rag.git`

### Option B: Direct Transfer
- [ ] Copy project folder to USB/network drive
- [ ] Transfer to Windows machine
- [ ] Extract to: `C:\Projects\medical-research-rag\`

**Location on Windows:** ___________________________________

---

## ☑️ Windows Setup

### Install Prerequisites
- [ ] Download Inno Setup from: https://jrsoftware.org/isdl.php
- [ ] Install Inno Setup (accept defaults)
- [ ] Verify installation: Start Menu → Inno Setup Compiler

### Optional (for testing)
- [ ] Install Docker Desktop: https://www.docker.com/products/docker-desktop/
- [ ] Install Git (if using GitHub method)

---

## ☑️ Build Installer

### Using Inno Setup GUI
1. [ ] Open Inno Setup Compiler
2. [ ] File → Open → `installer.iss`
3. [ ] Build → Compile (or Ctrl+F9)
4. [ ] Wait for compilation (~30 seconds)
5. [ ] Check for success message

### Verify Output
- [ ] File exists: `installer_output\MedicalResearchRAG_Setup.exe`
- [ ] File size: ~25-30MB
- [ ] No error messages in compiler output

**Build Date/Time:** ___________________________________

**Installer Size:** ___________________________________

---

## ☑️ Test Installation (IMPORTANT!)

### Test 1: Fresh Install
- [ ] Copy installer to Desktop
- [ ] Run `MedicalResearchRAG_Setup.exe`
- [ ] Follow installation wizard
- [ ] Accept license
- [ ] Choose installation directory
- [ ] Installation completes successfully
- [ ] Post-install README opens

### Test 2: Verify Installation
- [ ] Check installation directory exists
- [ ] All files copied correctly
- [ ] Start Menu shortcuts created (7 shortcuts):
  - [ ] Start Medical RAG
  - [ ] Stop Medical RAG
  - [ ] Check Status
  - [ ] Download AI Models
  - [ ] Debug Ingestion
  - [ ] Open Web Interface
  - [ ] Uninstall
- [ ] Desktop icon created (if selected)

### Test 3: Docker Check
- [ ] Docker Desktop is installed (or prompted to install)
- [ ] Docker Desktop is running
- [ ] WSL2 is installed and enabled

### Test 4: Start Application
- [ ] Click "Start Medical RAG" shortcut
- [ ] Models download prompt appears (first time)
- [ ] Download models (takes 10-30 minutes, ~5GB)
- [ ] Containers start successfully
- [ ] Browser opens to http://localhost:8000

### Test 5: Web Interface
- [ ] Web UI loads correctly
- [ ] Ingest tab visible
- [ ] Query tab visible
- [ ] Metrics tab visible
- [ ] No console errors

### Test 6: PDF Ingestion
- [ ] PDFs are in `pdfs/` folder
- [ ] Ingest tab shows progress
- [ ] Ingestion completes successfully
- [ ] Metrics show ingested documents

### Test 7: Query Functionality
- [ ] Enter test query: "What are the risk factors for stroke?"
- [ ] Answer appears with sources
- [ ] Citations show page numbers
- [ ] Response is relevant

### Test 8: Backup/Restore
- [ ] Navigate to `scripts/` folder
- [ ] Run `backup.bat`
- [ ] Backup created in `backups/` folder
- [ ] Backup contains: vector_db, data, pdfs, logs
- [ ] Metadata file created

### Test 9: Stop Application
- [ ] Click "Stop Medical RAG" shortcut
- [ ] Containers stop gracefully
- [ ] Web interface becomes unavailable
- [ ] No hanging processes

### Test 10: Uninstall
- [ ] Control Panel → Programs and Features
- [ ] Find "Medical Research RAG Pipeline"
- [ ] Click Uninstall
- [ ] Uninstaller runs successfully
- [ ] Installation directory removed
- [ ] Start Menu shortcuts removed
- [ ] Desktop icon removed (if created)

**Testing Completed By:** ___________________________________

**Testing Date:** ___________________________________

**All Tests Passed:** [ ] YES  [ ] NO

**Issues Found:** ___________________________________

---

## ☑️ Distribution

### GitHub Releases
- [ ] Create git tag: `git tag v1.0.0`
- [ ] Push tag: `git push origin v1.0.0`
- [ ] Go to GitHub Releases page
- [ ] Click "Draft a new release"
- [ ] Select tag: v1.0.0
- [ ] Add release title: "Medical Research RAG Pipeline v1.0.0"
- [ ] Add release description (see WINDOWS_DEPLOYMENT_GUIDE.md)
- [ ] Attach `MedicalResearchRAG_Setup.exe`
- [ ] Publish release

### Alternative Distribution
- [ ] Upload to Google Drive/Dropbox/OneDrive
- [ ] Get shareable link
- [ ] Test download link
- [ ] Share with users

**Distribution URL:** ___________________________________

**Release Date:** ___________________________________

---

## ☑️ User Communication

### Provide Users With:
- [ ] Download link to installer
- [ ] Link to WINDOWS_INSTALLER_README.txt
- [ ] System requirements:
  - Windows 10/11 64-bit
  - 8GB RAM minimum (16GB recommended)
  - 20GB free disk space
  - Docker Desktop (will be prompted)
- [ ] Support contact information

### Documentation Shared:
- [ ] Quick start guide
- [ ] Troubleshooting guide
- [ ] FAQ (if created)

---

## ☑️ Post-Release

### Monitor
- [ ] User feedback collected
- [ ] Issues tracked on GitHub
- [ ] Common problems documented

### Future Updates
- [ ] Version number incremented in installer.iss
- [ ] Changelog maintained
- [ ] Users notified of updates

---

## 📝 Notes

**Build Notes:**
___________________________________
___________________________________
___________________________________

**Testing Issues:**
___________________________________
___________________________________
___________________________________

**User Feedback:**
___________________________________
___________________________________
___________________________________

---

## ✅ Summary

**Current Status:**
- Pre-build: ✅ COMPLETE (all requirements met on Mac)
- Transfer to Windows: ⏳ PENDING
- Build installer: ⏳ PENDING
- Test installation: ⏳ PENDING
- Distribute: ⏳ PENDING

**Next Step:** Transfer project to Windows machine and build installer

**Estimated Time Remaining:** ~2 hours (build: 15min, test: 1hr, distribute: 15min)

---

## Quick Command Reference

### Build Installer (Command Line)
```powershell
cd "C:\Projects\medical-research-rag"
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

### Test Docker
```powershell
docker --version
docker compose --version
docker ps
```

### View Application Logs
```powershell
cd "C:\Program Files\MedicalResearchRAG"
docker compose logs -f
```

### Manual Container Start
```powershell
cd "C:\Program Files\MedicalResearchRAG"
docker compose up -d
```

### Check Container Status
```powershell
docker ps
docker compose ps
```

---

**Good luck with your Windows deployment! 🚀**

Print this checklist and check off items as you complete them.
