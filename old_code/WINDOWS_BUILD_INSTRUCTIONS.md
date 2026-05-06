# Windows Installer Build Instructions

## IMPORTANT: File Transfer First!

The installer MUST be built on Windows after transferring ALL files from Mac.

---

## Step-by-Step Process

### 1. On Mac - Prepare Files

```bash
# Navigate to parent directory
cd /Users/User/

# Create zip with ALL files
zip -r healthcare-project.zip "healthcare project/"

# Verify all critical files are included
unzip -l healthcare-project.zip | grep -E "docker-entrypoint.sh|wait_for_ingestion.ps1|Dockerfile"
```

**Expected output:**
```
docker-entrypoint.sh
wait_for_ingestion.ps1
Dockerfile
```

### 2. Transfer to Windows

- Copy `healthcare-project.zip` to Windows via:
  - USB drive
  - Network share
  - Cloud storage (OneDrive, Dropbox, etc.)

### 3. On Windows - Extract Files

```powershell
# Extract to program files directory
Expand-Archive -Path healthcare-project.zip -DestinationPath "C:\Program Files\MedicalResearchRAG"

# OR extract to temporary location first, then move
Expand-Archive -Path healthcare-project.zip -DestinationPath "C:\Temp\healthcare"
Move-Item "C:\Temp\healthcare\healthcare project\*" "C:\Program Files\MedicalResearchRAG\" -Force
```

### 4. Verify Critical Files Exist

```powershell
cd "C:\Program Files\MedicalResearchRAG"

# Check all required files
Get-Item docker-entrypoint.sh
Get-Item wait_for_ingestion.ps1
Get-Item Dockerfile
Get-Item installer.iss

# If any file is missing, re-extract the zip
```

### 5. Rebuild Docker (REQUIRED)

```powershell
# Stop existing containers
docker compose down

# Rebuild with new Dockerfile and entrypoint
docker compose build --no-cache

# Start containers
docker compose up -d

# Verify entrypoint script ran
docker compose logs rag-app | Select-String "pdfs folder write test passed"
```

**Expected output:**
```
✓ /app/pdfs is writable
✓ pdfs folder write test passed
```

### 6. Build the Installer

**Only after Docker rebuild succeeds:**

```powershell
# Build installer with Inno Setup
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

**Expected output:**
```
Compiling...
Successful compile (X min Y.Z sec)
Output: C:\Program Files\MedicalResearchRAG\installer_output\MedicalResearchRAG_Setup.exe
```

### 7. Test the Installer

```powershell
# Run the installer
.\installer_output\MedicalResearchRAG_Setup.exe
```

**During installation:**
- Check "Complete setup now"
- Watch for Steps 5-7 (ingestion)
- Verify "✓ Ingestion complete!"

---

## Troubleshooting

### Error: "docker-entrypoint.sh not found" during installer build

**Cause:** File wasn't transferred to Windows or is in wrong location

**Solution:**
```powershell
# Check file exists
Get-Item "C:\Program Files\MedicalResearchRAG\docker-entrypoint.sh"

# If missing, re-extract the zip or copy the file manually
```

### Error: "wait_for_ingestion.ps1 not found" during installer build

**Cause:** Same as above

**Solution:**
```powershell
# Check file exists
Get-Item "C:\Program Files\MedicalResearchRAG\wait_for_ingestion.ps1"
```

### Docker build fails with "docker-entrypoint.sh not found"

**Cause:** File has Windows line endings (CRLF) instead of Unix (LF)

**Solution:**
The file should have Unix line endings. If you manually created it on Windows, convert:
```powershell
# Using PowerShell to fix line endings
(Get-Content docker-entrypoint.sh -Raw) -replace "`r`n", "`n" | Set-Content docker-entrypoint.sh -NoNewline
```

### Installer builds but ingestion doesn't run during installation

**Cause:** wait_for_ingestion.ps1 wasn't packaged

**Solution:**
```powershell
# Verify installer.iss includes the file (line 75)
Get-Content installer.iss | Select-String "wait_for_ingestion.ps1"

# Should show:
# Source: "wait_for_ingestion.ps1"; DestDir: "{app}"; Flags: ignoreversion

# If missing, check you have the latest installer.iss
```

---

## Quick Verification Before Building Installer

Run this PowerShell script to verify everything is ready:

```powershell
cd "C:\Program Files\MedicalResearchRAG"

Write-Host "Checking required files..." -ForegroundColor Yellow
$files = @(
    "docker-entrypoint.sh",
    "wait_for_ingestion.ps1",
    "Dockerfile",
    "installer.iss",
    "POST_INSTALL_SETUP.bat"
)

$allPresent = $true
foreach ($file in $files) {
    if (Test-Path $file) {
        Write-Host "✓ $file" -ForegroundColor Green
    } else {
        Write-Host "✗ $file - MISSING!" -ForegroundColor Red
        $allPresent = $false
    }
}

if ($allPresent) {
    Write-Host "`n✓ All files present - ready to build installer!" -ForegroundColor Green
} else {
    Write-Host "`n✗ Some files missing - re-extract zip or transfer files" -ForegroundColor Red
}
```

---

## Summary

**The installer build REQUIRES all files to be present on Windows first!**

Correct order:
1. ✅ Zip project on Mac
2. ✅ Transfer zip to Windows
3. ✅ Extract all files on Windows
4. ✅ Rebuild Docker containers
5. ✅ Build installer with Inno Setup
6. ✅ Test installer

Wrong order:
1. ❌ Build installer before transferring files
2. ❌ Result: "File not found" errors

---

## File Checklist

Before building installer, verify these files exist on Windows:

**Core application:**
- [ ] docker-compose.yml
- [ ] Dockerfile
- [ ] docker-entrypoint.sh ← CRITICAL
- [ ] requirements.txt
- [ ] app.py, ingest.py, query.py
- [ ] src/ folder
- [ ] api/ folder
- [ ] static/ folder

**Installation scripts:**
- [ ] POST_INSTALL_SETUP.bat
- [ ] wait_for_ingestion.ps1 ← CRITICAL
- [ ] START_APP.bat, STOP_APP.bat
- [ ] CHECK_STATUS.bat

**Installer files:**
- [ ] installer.iss
- [ ] app_icon.ico

**Sample data:**
- [ ] pdfs/ folder (with 18 sample PDFs)

If ANY file is missing, the installer build will fail!
