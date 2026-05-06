# Development Notes

This document consolidates key technical notes, troubleshooting tips, and implementation details from the development process.

---

## Table of Contents

1. [Docker Permissions Fix (Windows)](#docker-permissions-fix-windows)
2. [GUI Bug Fixes](#gui-bug-fixes)
3. [Upload Troubleshooting](#upload-troubleshooting)
4. [Automatic Installation Ingestion](#automatic-installation-ingestion)
5. [Icon Implementation](#icon-implementation)

---

## Docker Permissions Fix (Windows)

### Problem
Windows + Docker volume mount permission issues caused `PermissionError: [Errno 13] Permission denied: 'pdfs/test.pdf'` when uploading PDFs via GUI.

### Root Cause
Docker Desktop on Windows doesn't automatically grant write permissions to mounted volumes for the container user.

### Solution Implemented
**Dockerfile changes:**
```dockerfile
# Set 777 permissions on mounted directories
RUN mkdir -p pdfs vector_db data logs && \
    chmod 777 pdfs vector_db data logs

# Ensure mount points are writable
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chmod 777 /app/pdfs /app/vector_db /app/data /app/logs
```

**docker-entrypoint.sh (NEW):**
```bash
#!/bin/bash
# Verifies permissions before app starts
set -e

echo "Checking volume permissions..."

for dir in /app/pdfs /app/vector_db /app/data /app/logs; do
    if [ -d "$dir" ]; then
        if [ ! -w "$dir" ]; then
            echo "WARNING: $dir is not writable, attempting to fix..."
            chmod 777 "$dir" 2>/dev/null || echo "Could not change permissions for $dir"
        else
            echo "✓ $dir is writable"
        fi
    else
        echo "Creating $dir..."
        mkdir -p "$dir"
        chmod 777 "$dir"
    fi
done

# Test write access
if touch /app/pdfs/.write_test 2>/dev/null; then
    rm /app/pdfs/.write_test
    echo "✓ pdfs folder write test passed"
else
    echo "ERROR: Cannot write to /app/pdfs folder"
fi

echo "Starting application..."
exec "$@"
```

**Files Modified:**
- `Dockerfile`: Lines 33-35, 40-41, 47-48, 62
- `docker-entrypoint.sh`: NEW file (1.2 KB)

### Verification
After rebuild, logs should show:
```
Checking volume permissions...
✓ /app/pdfs is writable
✓ /app/vector_db is writable
✓ /app/data is writable
✓ /app/logs is writable
✓ pdfs folder write test passed
Starting application...
```

---

## GUI Bug Fixes

### 1. Query Spinner Stuck Visible

**Problem:** Loading spinner remained visible after query response was displayed.

**Cause:** JavaScript tried to remove element without null check.

**Fix (static/index.html, lines 1165-1168):**
```javascript
// Before
document.getElementById(loadingId).remove();

// After
const loadingElement = document.getElementById(loadingId);
if (loadingElement) {
    loadingElement.remove();
}
```

### 2. Auto-Ingest Banner Reappearing

**Problem:** Banner reappeared every 5 seconds after dismissal due to status polling.

**Cause:** Dismissed state wasn't persisted.

**Fix (static/index.html, lines 448-460, 503-511):**
```javascript
let bannerDismissed = false;

function dismissAutoIngestBanner() {
    const banner = document.getElementById('auto-ingest-banner');
    banner.classList.add('hidden');
    bannerDismissed = true;
    localStorage.setItem('autoIngestBannerDismissed', 'true');
}

// Check before showing banner
if (bannerDismissed || localStorage.getItem('autoIngestBannerDismissed') === 'true') {
    if (!data.running) {
        return; // Stay hidden
    }
}
```

### 3. No Query Context Displayed

**Problem:** Sources section didn't show context chunks after queries.

**Cause:** `return_context: false` hardcoded in query request.

**Fix (static/index.html, line 1152):**
```javascript
return_context: true  // Changed from false
```

---

## Upload Troubleshooting

### Common Issues

#### 1. 500 Internal Server Error on Upload

**Symptoms:**
- Browser shows: "Failed to load resources: the server responded with a status of 500"
- No files appear in pdfs/ folder

**Causes & Solutions:**

**A. Rate Limiter Conflict (Fixed)**
- **Cause:** Conflicting slowapi rate limiter instances in `api/ingest.py`
- **Solution:** Removed local limiter, simplified endpoint signature
- **Fix:** Lines 29-92 in api/ingest.py

**B. Permission Errors (Fixed)**
- **Cause:** Docker volume permissions on Windows
- **Solution:** See "Docker Permissions Fix" section above
- **Verification:** Check logs for "✓ pdfs folder write test passed"

#### 2. Upload Succeeds but Files Not Processed

**Check:**
```bash
# Verify files copied to container
docker compose exec rag-app ls -la /app/pdfs

# Check ingestion status
curl http://localhost:8000/api/ingest/status
```

**Common causes:**
- Ingestion not started (need to POST to /api/ingest)
- Ollama service not ready (check with `docker compose ps`)
- Embedding model not downloaded

---

## Automatic Installation Ingestion

### Feature Overview

PDFs are now automatically ingested during the installation process, so the system is immediately ready for queries when the browser opens.

### Implementation

**POST_INSTALL_SETUP.bat (Steps 5-7 added):**

```batch
echo [Step 5/7] Waiting for application to be ready...
# Polls /health endpoint until app is running (2-minute timeout)

echo [Step 6/7] Starting ingestion of sample PDFs...
# Triggers ingestion via API: curl -X POST http://localhost:8000/api/ingest

echo [Step 7/7] Waiting for ingestion to complete...
# Calls wait_for_ingestion.ps1 for progress monitoring
```

**wait_for_ingestion.ps1 (NEW - PowerShell monitoring script):**
- Polls `/api/ingest/status` every 10 seconds
- Shows real-time progress: elapsed time + files processed
- 30-minute timeout with graceful error handling
- Returns exit code 0 on success

**API Endpoints Used:**

Start Ingestion:
```bash
POST http://localhost:8000/api/ingest
```

Check Status:
```bash
GET http://localhost:8000/api/ingest/status
```

Response format:
```json
{
  "is_running": false,
  "complete": true,
  "files_processed": 18,
  "progress": 100,
  "message": "Ingestion complete"
}
```

### User Experience

**Before:**
1. Install app → Open browser → **Manually upload PDFs** → **Click "Start Ingestion"** → Wait → Query
2. Total: 4-5 manual steps

**After:**
1. Install app → Check "Complete setup now" → Everything automatic → Browser opens → Query immediately!
2. Total: 1 click

### Installation Flow

```
[Step 1/4] Check Docker
[Step 2/4] Build containers
[Step 3/4] Download AI models
[Step 4/4] Models downloaded
[Step 5/7] Wait for app ready          ← NEW
[Step 6/7] Trigger ingestion           ← NEW
[Step 7/7] Monitor progress            ← NEW
[SUCCESS] Browser opens → Ready!
```

### Error Handling

**If app doesn't start (Step 5):**
```
[WARNING] Application did not start in expected time.
Opening browser anyway - you may need to refresh the page.
```

**If ingestion API fails (Step 6):**
```
[WARNING] Could not trigger ingestion automatically.
You can start ingestion manually from the web interface.
```

**If ingestion times out (Step 7, >30 min):**
```
⚠ Ingestion is taking longer than expected (>30 minutes)
  You can monitor progress in the web interface.
```

### Files Modified
- `POST_INSTALL_SETUP.bat`: Lines 105-176 (Steps 5-7 added)
- `wait_for_ingestion.ps1`: NEW (1.6 KB)
- `installer.iss`: Lines 50, 75 (new scripts added)

---

## Icon Implementation

### Custom Application Icon

Created custom medical-themed icon for professional branding.

**Files:**
- `app_icon.ico` (19 KB, multi-resolution: 16x16 to 256x256)
- Design: Medical blue circle (#2563EB) with white cross and document symbol

### Installer Integration

**installer.iss changes:**
```ini
[Setup]
SetupIconFile=app_icon.ico

[Files]
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}\Start Medical RAG";
  Filename: "{app}\START_APP.bat";
  IconFilename: "{app}\app_icon.ico"

Name: "{autodesktop}\Medical Research RAG";
  Filename: "{app}\START_APP.bat";
  IconFilename: "{app}\app_icon.ico";
  Tasks: desktopicon
```

**Updated locations:**
- Installer EXE icon (line 33)
- Desktop shortcut (lines 97-99)
- All Start Menu shortcuts (lines 89-96)

---

## Windows Deployment Checklist

### Critical Files for Windows Transfer

When transferring project to Windows for installer build, ensure these files exist:

**Docker:**
- `Dockerfile` (with 777 permissions fix)
- `docker-entrypoint.sh` (NEW - permission verification)
- `docker-compose.yml`

**Installation Scripts:**
- `POST_INSTALL_SETUP.bat` (with automatic ingestion)
- `wait_for_ingestion.ps1` (NEW - ingestion monitoring)
- All other .bat files

**Installer:**
- `installer.iss` (references all above files)
- `app_icon.ico`

### Build Order

**Correct:**
1. Zip project on Mac
2. Transfer to Windows
3. Extract all files
4. Rebuild Docker: `docker compose build --no-cache`
5. Build installer: `ISCC.exe installer.iss`

**Wrong (will fail):**
1. Build installer before transferring files
2. Result: "File not found" errors

### Verification Before Building Installer

```powershell
cd "C:\Program Files\MedicalResearchRAG"

# Check critical files exist
Get-Item docker-entrypoint.sh
Get-Item wait_for_ingestion.ps1
Get-Item Dockerfile
Get-Item installer.iss

# Test Docker build
docker compose build --no-cache
docker compose up -d

# Verify permissions fix
docker compose logs rag-app | Select-String "pdfs folder write test passed"

# Test upload works
# Open http://localhost:8000, try uploading PDF

# THEN build installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

---

## Summary of All Fixes

| Bug/Feature | Status | Files Modified | Impact |
|-------------|--------|----------------|--------|
| Query spinner stuck | ✅ Fixed | static/index.html | Better UX |
| Banner reappearing | ✅ Fixed | static/index.html | Better UX |
| No query context | ✅ Fixed | static/index.html | Full RAG functionality |
| Upload 500 error | ✅ Fixed | api/ingest.py | Upload works |
| Permission denied | ✅ Fixed | Dockerfile, docker-entrypoint.sh | Windows compatibility |
| No custom icon | ✅ Fixed | installer.iss, app_icon.ico | Professional branding |
| Manual ingestion | ✅ Fixed | POST_INSTALL_SETUP.bat, wait_for_ingestion.ps1 | Zero-config setup |

**Result:** Production-ready Windows installer with automated setup and zero manual configuration required.

---

## Development Tools Used

- **FastAPI** - Web framework
- **Docker + Docker Compose** - Container orchestration
- **Ollama** - Local LLM service (nomic-embed-text, deepseek-r1:1.5b)
- **ChromaDB** - Vector database
- **Inno Setup** - Windows installer creation
- **PowerShell** - Windows automation
- **Batch scripting** - Windows integration

---

## Future Improvements

Potential enhancements:

1. **Progress Bar** - Visual progress in installer window
2. **Parallel Tasks** - Download models while ingesting
3. **Smart Skip** - Skip ingestion if already complete
4. **Custom PDFs** - Allow user PDF selection during install
5. **Background Mode** - Continue ingestion after browser opens
6. **Auto-Update** - Check for new versions on startup
7. **Backup/Restore** - Built-in backup functionality via GUI

---

*Last Updated: 2026-03-20*
*Project: Medical Research RAG Pipeline v1.0.0*
