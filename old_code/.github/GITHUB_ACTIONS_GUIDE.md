# GitHub Actions Build Guide

This project uses GitHub Actions to automatically build Windows and macOS executables in the cloud.

## Quick Start

### 1. Push Your Code to GitHub

If you haven't already:

```bash
# Initialize git (if not already done)
git init

# Add remote (replace with your repository URL)
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Add all files
git add .

# Commit
git commit -m "Add GitHub Actions build workflows"

# Push to GitHub
git push -u origin main
```

### 2. Trigger a Build

**Option A: Automatic Build**
- Builds automatically run every time you push to the `main` branch

**Option B: Manual Build**
1. Go to your GitHub repository
2. Click the "Actions" tab
3. Select "Build Windows Executable" or "Build macOS Application"
4. Click "Run workflow" → "Run workflow"

### 3. Download Built Executables

1. Go to the "Actions" tab in your repository
2. Click on the completed workflow run
3. Scroll down to "Artifacts"
4. Download:
   - `MedicalRAG-Windows.zip` - Contains the Windows `.exe`
   - `MedicalRAG-macOS.zip` - Contains the macOS `.app`

The artifacts are kept for 90 days.

## Creating Releases

To create a versioned release:

```bash
# Create and push a tag
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

This will:
1. Build both Windows and macOS versions
2. Create a GitHub Release
3. Attach the executables to the release

Users can then download from the "Releases" section of your repository.

## What Gets Built

### Windows Build
- **Output**: `MedicalRAG-Windows.zip`
- **Contains**: `MedicalRAG.exe` and all dependencies
- **Size**: ~150-200 MB (includes Python runtime)
- **Runs on**: Windows 10/11 (64-bit)

### macOS Build
- **Output**: `MedicalRAG-macOS.zip`
- **Contains**: `MedicalRAG.app` bundle
- **Size**: ~150-200 MB (includes Python runtime)
- **Runs on**: macOS 11+ (Intel and Apple Silicon)

## Distribution Instructions

After downloading the built executables:

### For Windows Users

1. Extract `MedicalRAG-Windows.zip`
2. Install prerequisites:
   - [Ollama for Windows](https://ollama.com/download/windows)
   - Run: `ollama pull deepseek-r1:1.5b`
   - Run: `ollama pull nomic-embed-text`
3. Create PDF folder: `%APPDATA%\MedicalRAG\pdfs\`
4. Copy medical PDFs to that folder
5. Run `MedicalRAG.exe`

### For macOS Users

1. Extract `MedicalRAG-macOS.zip`
2. Install prerequisites:
   - `brew install ollama`
   - `ollama pull deepseek-r1:1.5b`
   - `ollama pull nomic-embed-text`
3. Copy PDFs to: `~/Library/Application Support/MedicalRAG/pdfs/`
4. Right-click `MedicalRAG.app` → Open (first time only, due to unsigned app)

## Troubleshooting

### Build Fails

Check the Actions tab for error logs. Common issues:
- Missing dependencies in `requirements-prod.txt`
- Syntax errors in workflow files
- PyInstaller spec file issues

### Can't Download Artifacts

- Artifacts expire after 90 days
- You must be logged into GitHub
- Create a Release (using tags) for permanent downloads

### macOS Security Warning

The app is unsigned. Users need to:
1. Right-click → Open (don't double-click)
2. Click "Open" in the security dialog
3. Or: System Settings → Privacy & Security → "Open Anyway"

### Windows Security Warning

Windows Defender SmartScreen may show a warning:
1. Click "More info"
2. Click "Run anyway"

This is normal for unsigned applications.

## Workflow Configuration

The workflows are located in:
- `.github/workflows/build-windows.yml`
- `.github/workflows/build-macos.yml`

They automatically:
- ✅ Install Python 3.12
- ✅ Install all dependencies
- ✅ Run PyInstaller
- ✅ Package the executables
- ✅ Upload as artifacts
- ✅ Create releases for tagged versions

## Cost

GitHub Actions is **free** for public repositories with generous limits:
- 2,000 minutes/month for private repos
- Unlimited for public repos

Each build takes ~5-10 minutes, so you can run hundreds of builds per month for free.

## Local vs GitHub Builds

| Aspect | Local Build | GitHub Actions |
|--------|-------------|----------------|
| **Speed** | Instant | 5-10 min queue + build |
| **Testing** | Can test immediately | Must download to test |
| **Platform** | Mac or Windows only | Both platforms |
| **Requirements** | Need target OS | Works from any OS |
| **Cost** | Free (your machine) | Free (GitHub's servers) |

## Next Steps

1. **Test the workflow**: Push to main or run manually
2. **Download artifacts**: Verify the builds work
3. **Create a release**: Tag with `v1.0.0` when ready
4. **Share with users**: They download from Releases page

## Support

If builds fail, check:
1. Actions tab → Click failed workflow → View logs
2. Verify `requirements-prod.txt` is complete
3. Check `build_windows.spec` and `build_macos.spec` syntax
4. Open a GitHub Issue if needed
