# Building the Windows Installer

This guide explains how to build a Windows installer (.exe) for the Medical Research RAG Pipeline.

## Overview

The installer is created using **Inno Setup**, a free installer for Windows programs. It packages all application files, documentation, and scripts into a single executable that users can download and run.

---

## Prerequisites

You need a **Windows machine** to build the installer. You cannot build Windows installers on macOS or Linux.

### Required Software:

1. **Inno Setup** (free)
   - Download: https://jrsoftware.org/isdl.php
   - Install the latest version (6.2.2 or newer)
   - Choose "Full installation" option

2. **Git** (to clone the repository)
   - Download: https://git-scm.com/download/win
   - Or use the code you already have

---

## Step 1: Prepare the Project Files

### On Your Mac (Current Machine):

The project is already ready! All necessary files are committed to GitHub.

**What's included:**
- ✅ Batch scripts (`START_APP.bat`, `STOP_APP.bat`, etc.)
- ✅ Inno Setup script (`installer.iss`)
- ✅ Documentation (`WINDOWS_INSTALLER_README.txt`, etc.)
- ✅ Docker files (`docker-compose.yml`, `Dockerfile`)
- ✅ Application code (all Python files and folders)
- ✅ Sample PDFs (20 medical research papers in `pdfs/`)

**Push to GitHub:**
```bash
git add .
git commit -m "Add Windows installer configuration and batch scripts"
git push
```

---

## Step 2: On a Windows Machine

### Clone the Repository

```cmd
git clone https://github.com/MoCode98/medical-research-rag.git
cd medical-research-rag
```

Or download as ZIP from GitHub and extract.

---

## Step 3: Create a LICENSE File (Required)

The installer script expects a `LICENSE` file. Create one:

**Option A: MIT License** (recommended for open source)

Create `LICENSE` file with this content:
```
MIT License

Copyright (c) 2024 MoCode98

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Option B: Proprietary License**

Or remove the `LicenseFile` line from `installer.iss` if you don't want to show a license during installation.

---

## Step 4: Build the Installer

1. **Open Inno Setup Compiler**
   - Find "Inno Setup Compiler" in Start Menu
   - Launch it

2. **Open the Script**
   - File → Open
   - Navigate to: `medical-research-rag\installer.iss`
   - Click Open

3. **Review the Configuration**
   The script includes:
   - Application name, version, publisher
   - Files to include
   - Start Menu shortcuts
   - Desktop icon (optional)
   - Docker Desktop check on installation

4. **Compile the Installer**
   - Click **Build** → **Compile** (or press F9)
   - Or click the blue "Compile" button in toolbar

5. **Wait for Compilation**
   - Should take 10-30 seconds
   - You'll see output in the bottom pane
   - Look for "Successful compile"

6. **Installer Created!**
   - Output location: `installer_output\MedicalResearchRAG_Setup.exe`
   - Size: ~25-30MB (includes all files + PDFs)

---

## Step 5: Test the Installer

**IMPORTANT:** Test on a clean Windows machine if possible.

1. **Copy the installer** to a test location
   ```
   installer_output\MedicalResearchRAG_Setup.exe
   ```

2. **Run the installer**
   - Double-click `MedicalResearchRAG_Setup.exe`
   - Follow the installation wizard
   - It will check for Docker Desktop

3. **Test the application**
   - Install Docker Desktop if not already installed
   - Run "Start Medical RAG" from Start Menu
   - Wait for startup
   - Browser should open to http://localhost:8000
   - Test uploading a PDF
   - Test querying

4. **Test uninstallation**
   - Settings → Apps → Medical Research RAG Pipeline → Uninstall
   - Verify files are removed
   - Check Start Menu shortcuts are gone

---

## Step 6: Distribute the Installer

Once tested, you can distribute the installer:

### Option 1: GitHub Releases (Recommended)

1. Go to: https://github.com/MoCode98/medical-research-rag/releases
2. Click "Create a new release"
3. Tag version: `v1.0.0`
4. Release title: "Medical Research RAG Pipeline v1.0.0"
5. Upload `MedicalResearchRAG_Setup.exe`
6. Add release notes describing features
7. Click "Publish release"

Users can then download from:
```
https://github.com/MoCode98/medical-research-rag/releases/latest
```

### Option 2: Direct Download

Upload to:
- Google Drive
- Dropbox
- OneDrive
- Your own website

Share the download link with your friend.

---

## Installer Features

The installer provides:

✅ **Professional Installation Wizard**
- Welcome screen
- License agreement (optional)
- Installation directory selection
- Progress bar
- Completion screen

✅ **Start Menu Integration**
- Start Medical RAG shortcut
- Stop Medical RAG shortcut
- Check Status shortcut
- Download AI Models shortcut
- Open Web Interface shortcut
- Uninstall shortcut

✅ **Desktop Icon** (optional during install)
- Quick access to start the application

✅ **Docker Desktop Check**
- Detects if Docker is installed
- Offers to open download page if missing
- Warns user to install before running

✅ **Automatic Directory Creation**
- Creates `vector_db/`, `data/`, `logs/` folders
- Ensures proper structure on first run

✅ **Clean Uninstallation**
- Removes all files and shortcuts
- Option to preserve Docker volumes (data)

---

## Customization

Edit `installer.iss` to customize:

### Change Version Number
```ini
#define MyAppVersion "1.0.0"
```

### Change Installation Directory
```ini
DefaultDirName={autopf}\MedicalResearchRAG
```
Change to `{userdocs}\MedicalRAG` for user's Documents folder.

### Add Application Icon
1. Create a `.ico` file (icon)
2. Save as `app_icon.ico` in project root
3. Edit `installer.iss`:
   ```ini
   SetupIconFile=app_icon.ico
   ```

### Remove Desktop Icon Option
Remove this line:
```ini
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; ...
```

---

## Troubleshooting Build Issues

### "File not found: LICENSE"
Create a LICENSE file or remove `LicenseFile=LICENSE` from `installer.iss`

### "File not found: [filename]"
Ensure all files listed in `[Files]` section exist in the project

### "Access denied" during compile
Run Inno Setup Compiler as Administrator

### Installer is too large (>50MB)
Consider excluding large files from `pdfs/` folder or compress them

---

## Building Without Inno Setup (Alternative)

If you don't want to build an installer, you can create a **portable ZIP package**:

```cmd
# On Windows, in project directory
powershell Compress-Archive -Path * -DestinationPath MedicalResearchRAG_Portable.zip
```

Users would:
1. Extract ZIP
2. Install Docker Desktop
3. Double-click `START_APP.bat`

This is simpler but less professional than an installer.

---

## Next Steps

After building the installer:

1. ✅ Test thoroughly on clean Windows machine
2. ✅ Upload to GitHub Releases
3. ✅ Share download link with your friend
4. ✅ Send them `WINDOWS_INSTALLER_README.txt` for instructions

Your friend will have a professional one-click installation experience! 🎉

---

## File Size Estimates

- **Installer**: ~25-30MB
  - Application code: ~5MB
  - Sample PDFs: ~21MB
  - Scripts and docs: ~1MB
  - Compression: ~20% size reduction

- **Installed size**: ~30-40MB on disk

- **After first run** (with models): ~5.5GB
  - Application: ~30MB
  - Ollama models: ~5GB
  - Vector database: ~500MB (varies with PDFs)

---

## Support

If you encounter issues building the installer:

1. Check Inno Setup documentation: https://jrsoftware.org/ishelp/
2. Verify all files exist in project directory
3. Try compiling with verbose output (View → Compiler Output)
4. Check for file path issues (spaces, special characters)

For application issues, see `DOCKER_SETUP.md` for troubleshooting.
