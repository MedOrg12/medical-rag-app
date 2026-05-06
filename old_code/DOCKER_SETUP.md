# Docker Setup Guide for Medical Research RAG Pipeline

Complete guide for deploying the Medical Research RAG system using Docker on Windows, Mac, or Linux.

---

## Table of Contents

- [Windows Users - Quick Start](#windows-users---quick-start)
- [Prerequisites](#prerequisites)
- [Installation Steps](#installation-steps)
- [Using the Application](#using-the-application)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)
- [Maintenance and Updates](#maintenance-and-updates)

---

## Windows Users - Quick Start

### What You'll Get

A complete AI-powered medical research system that:
- Ingests medical research PDFs automatically
- Uses local AI models (no cloud, no API keys needed)
- Provides a web interface accessible at http://localhost:8000
- Keeps all your data private and local

### Time Required
- **First Time**: 30-45 minutes (includes downloading 6GB of AI models)
- **Subsequent Runs**: < 1 minute

---

## Prerequisites

### Hardware Requirements

**Minimum:**
- Windows 10 64-bit (Build 19041+) or Windows 11
- 8GB RAM
- 20GB free disk space
- Intel or AMD 64-bit processor

**Recommended:**
- 16GB RAM
- SSD with 30GB free space
- Multi-core processor (4+ cores)
- NVIDIA GPU (optional, for faster AI processing)

### Software Requirements

1. **Docker Desktop for Windows**
   - Download: https://www.docker.com/products/docker-desktop/
   - Version: 4.0.0 or later
   - Requires WSL 2 (Windows Subsystem for Linux)

2. **Internet Connection**
   - Required for initial setup (downloading ~6GB of AI models)
   - Not required after setup (runs completely offline)

---

## Installation Steps

### Step 1: Install Docker Desktop

1. **Download Docker Desktop**
   - Visit: https://www.docker.com/products/docker-desktop/
   - Click "Download for Windows"
   - Save the installer file

2. **Run the Installer**
   - Double-click the downloaded `.exe` file
   - You may need administrator privileges (right-click → "Run as administrator")
   - During installation, ensure these options are checked:
     - ✅ "Use WSL 2 instead of Hyper-V" (recommended)
     - ✅ "Add shortcut to desktop"

3. **Complete Installation**
   - Click "Install"
   - Wait for installation to complete (5-10 minutes)
   - Click "Close and restart" when prompted
   - **Important:** Your computer will restart

4. **First Launch**
   - After restart, Docker Desktop should launch automatically
   - If not, find "Docker Desktop" in Start Menu and launch it
   - Accept the service agreement
   - Wait for Docker to start (look for green "Docker Desktop is running" in system tray)

5. **Verify Installation**
   - Open Command Prompt or PowerShell:
     - Press `Win + R`
     - Type `cmd` or `powershell`
     - Press Enter
   - Run: `docker --version`
   - You should see: `Docker version 24.x.x, build ...`
   - Run: `docker compose version`
   - You should see: `Docker Compose version v2.x.x`

**If you see errors:**
- Restart Docker Desktop from the system tray icon
- Ensure virtualization is enabled in BIOS (consult your PC manual)
- Check Docker Desktop troubleshooting: https://docs.docker.com/desktop/troubleshoot/overview/

---

### Step 2: Get the Project

#### Option A: Download as ZIP (Easiest)

1. Download the project as a ZIP file (from GitHub, email, etc.)
2. Extract the ZIP to a location you'll remember, e.g., `C:\Projects\healthcare-project`
3. Open Command Prompt or PowerShell
4. Navigate to the project folder:
   ```cmd
   cd C:\Projects\healthcare-project
   ```

#### Option B: Clone with Git (If you have Git installed)

1. Open Command Prompt or PowerShell
2. Navigate to where you want the project:
   ```cmd
   cd C:\Projects
   ```
3. Clone the repository:
   ```cmd
   git clone <repository-url>
   cd healthcare-project
   ```

---

### Step 3: Start the Application

1. **Ensure Docker Desktop is Running**
   - Check the system tray for the Docker icon
   - It should show "Docker Desktop is running"
   - If not, start Docker Desktop from the Start Menu

2. **Open Command Prompt in Project Folder**
   - Navigate to the project folder:
     ```cmd
     cd C:\Projects\healthcare-project
     ```
   - Or, in File Explorer:
     - Right-click in the project folder (not on a file)
     - Select "Open in Terminal" or "Open PowerShell window here"

3. **Start the Services**
   ```cmd
   docker compose up -d
   ```

   **What happens during first run:**
   - Downloads Ollama container (~2GB) - 5-10 minutes
   - Builds the RAG application (~500MB) - 3-5 minutes
   - Starts both containers
   - **Total first-run time: 10-15 minutes**

4. **Monitor Startup Progress**
   ```cmd
   docker compose logs -f rag-app
   ```
   - Look for: `Starting server...` and `Uvicorn running on http://0.0.0.0:8000`
   - Press `Ctrl+C` to exit logs (containers keep running in background)

---

### Step 4: Download AI Models (One-Time Setup)

The AI models need to be downloaded once. They're large (~5GB) but only need to be downloaded one time.

1. **Download the Embedding Model** (for understanding document content)
   ```cmd
   docker compose exec ollama ollama pull nomic-embed-text
   ```
   - Size: ~274MB
   - Time: 2-5 minutes

2. **Download the LLM Model** (for answering questions)
   ```cmd
   docker compose exec ollama ollama pull deepseek-r1:7b
   ```
   - Size: ~4.7GB
   - Time: 10-30 minutes (depending on internet speed)

3. **Verify Models are Installed**
   ```cmd
   docker compose exec ollama ollama list
   ```
   - You should see both `nomic-embed-text` and `deepseek-r1:7b` listed

**Alternative Models** (if you want smaller/faster or larger/better):
- Smaller LLM: `ollama pull qwen:0.5b` (500MB, very fast)
- Larger LLM: `ollama pull deepseek-r1:70b` (40GB, very good, requires 32GB+ RAM)

---

### Step 5: Verify Everything is Running

1. **Check Container Status**
   ```cmd
   docker compose ps
   ```
   - You should see two containers: `medical-rag-ollama` and `medical-rag-app`
   - Both should show "Up" status and "healthy"

2. **Check Logs for Errors**
   ```cmd
   docker compose logs --tail=50
   ```
   - Look for any red error messages
   - Normal startup includes "Auto-ingestion" messages (this is expected)

3. **Test the Web UI**
   - Open your web browser (Chrome, Firefox, Edge)
   - Navigate to: **http://localhost:8000**
   - You should see the Medical Research RAG interface with three tabs:
     - 📄 Ingest
     - 💬 Query
     - 📊 Metrics

---

## Using the Application

### Adding Medical Research PDFs

#### Method 1: Auto-Ingestion (Recommended)

1. **Find the `pdfs` Folder**
   - In your project directory: `C:\Projects\healthcare-project\pdfs`
   - If it doesn't exist, create it

2. **Add PDF Files**
   - Copy or move your medical research PDFs into this folder
   - Supported: Any number of PDFs, each up to 50MB

3. **Restart the Application**
   ```cmd
   docker compose restart rag-app
   ```

4. **Monitor Auto-Ingestion**
   - Watch the terminal:
     ```cmd
     docker compose logs -f rag-app
     ```
   - Or check the blue banner at the top of the web UI
   - Ingestion happens in the background
   - UI is immediately accessible

#### Method 2: Manual Upload via Web UI

1. Open http://localhost:8000
2. Go to the **Ingest** tab (📄)
3. Drag and drop PDF files into the upload zone
4. Click **Start Ingestion**
5. Watch real-time progress in the terminal-style logs

### Querying Documents

1. Open http://localhost:8000
2. Go to the **Query** tab (💬)
3. (Optional) Configure settings:
   - **Model**: Choose AI model (default is fine)
   - **Top-K**: Number of document chunks to retrieve (5 is good)
   - **Temperature**: Creativity (0.7 is balanced)
4. Type your question in the input box
5. Press Enter or click **Send**
6. Wait for the AI to respond (5-30 seconds depending on query)
7. View:
   - Markdown-formatted answer
   - Source citations with page numbers
   - Similarity scores
   - Query time

**Example Questions:**
- "What are the main findings about treatment X?"
- "Summarize the methodology used in this study"
- "What are the reported side effects?"

### Viewing System Metrics

1. Go to the **Metrics** tab (📊)
2. View:
   - Total chunks in database
   - Cache hit rate (higher is better)
   - Files processed
   - Failed files
   - Cache performance chart
3. Metrics auto-refresh every 5 seconds

---

## Stopping and Restarting

### Stop the Application

**Option 1: Stop (Preserves Everything)**
```cmd
docker compose stop
```
- Containers are stopped but not removed
- All data is preserved
- Quick to restart

**Option 2: Down (Clean Stop)**
```cmd
docker compose down
```
- Containers are stopped and removed
- Volumes are preserved (your data is safe)
- Use this for clean shutdowns

**Option 3: Complete Cleanup (⚠️ DELETES ALL DATA)**
```cmd
docker compose down -v
```
- ⚠️ **WARNING**: This deletes all ingested PDFs and embeddings
- Only use if you want to start completely fresh

### Restart the Application

```cmd
docker compose up -d
```
- Starts containers in detached mode (background)
- Very fast after first run (~10 seconds)
- Automatically restarts if your PC restarts (unless you used `stop`)

---

## Troubleshooting

### Docker Desktop Won't Start

**Symptoms**: Docker icon in system tray shows error

**Solutions**:
1. Restart Docker Desktop:
   - Right-click Docker icon in system tray
   - Click "Restart Docker Desktop"
2. Check if WSL 2 is enabled:
   - Open PowerShell as Administrator
   - Run: `wsl --status`
   - If not installed: `wsl --install`
3. Ensure virtualization is enabled in BIOS:
   - Restart PC and enter BIOS (usually F2, F10, or Del during boot)
   - Find "Virtualization Technology" and enable it
   - Save and exit

### "Cannot connect to Ollama"

**Symptoms**: Web UI shows "Could not connect to Ollama" error

**Solutions**:
1. Verify Ollama container is running:
   ```cmd
   docker compose ps
   ```
   - `medical-rag-ollama` should show "Up" and "healthy"
2. Restart Ollama:
   ```cmd
   docker compose restart ollama
   ```
3. Check Ollama logs:
   ```cmd
   docker compose logs ollama
   ```
4. Ensure models are downloaded (see Step 4 above)

### "Port 8000 already in use"

**Symptoms**: Error when starting: `Bind for 0.0.0.0:8000 failed: port is already allocated`

**Solutions**:
1. Find what's using port 8000:
   ```cmd
   netstat -ano | findstr :8000
   ```
2. Stop the conflicting service, or
3. Change the port in `docker-compose.yml`:
   ```yaml
   ports:
     - "8080:8000"  # Use port 8080 instead
   ```
   - Then access UI at http://localhost:8080

### "Vector database is empty"

**Symptoms**: Queries return "No documents found" or empty results

**Solutions**:
1. Check if PDFs have been ingested:
   - Go to Metrics tab
   - Check "Total Chunks" - should be > 0
2. Add PDFs and ingest:
   - Copy PDFs to `pdfs/` folder
   - Restart: `docker compose restart rag-app`
   - Or use Ingest tab to upload manually
3. Check auto-ingestion status:
   ```cmd
   docker compose logs rag-app | findstr "Auto-ingestion"
   ```

### Slow Performance

**Symptoms**: Queries take > 60 seconds, UI is sluggish

**Solutions**:
1. Allocate more resources to Docker:
   - Open Docker Desktop
   - Go to Settings (gear icon)
   - Resources → Advanced
   - Increase CPUs to 4+ and RAM to 8GB+
   - Click "Apply & Restart"
2. Use a smaller AI model:
   ```cmd
   docker compose exec ollama ollama pull qwen:0.5b
   ```
   - Update `OLLAMA_MODEL` in docker-compose.yml
3. Reduce Top-K in Query tab (try 3 instead of 5)

### Permission Errors on `pdfs/` or `logs/` Folders

**Symptoms**: "Permission denied" when accessing folders

**Solutions**:
```cmd
icacls pdfs /grant Everyone:F /T
icacls logs /grant Everyone:F /T
```

### Container Won't Start / Health Check Failing

**Symptoms**: Container shows "unhealthy" status

**Solutions**:
1. Check logs:
   ```cmd
   docker compose logs rag-app
   ```
2. Verify all dependencies are running:
   ```cmd
   docker compose ps
   ```
3. Restart all services:
   ```cmd
   docker compose restart
   ```
4. If still failing, rebuild:
   ```cmd
   docker compose down
   docker compose build --no-cache
   docker compose up -d
   ```

---

## Advanced Configuration

### Environment Variables

Edit `docker-compose.yml` to customize behavior:

```yaml
environment:
  # Change AI models
  - OLLAMA_MODEL=qwen:7b  # Different LLM
  - OLLAMA_EMBEDDING_MODEL=nomic-embed-text

  # Adjust chunking
  - CHUNK_SIZE=512  # Smaller chunks (default: 512)
  - CHUNK_OVERLAP=50  # Overlap between chunks

  # Query behavior
  - TOP_K_RESULTS=5  # Number of chunks to retrieve
  - TEMPERATURE=0.7  # AI creativity (0-2)
```

After editing, restart:
```cmd
docker compose down
docker compose up -d
```

### Using External Ollama (Advanced)

If you already have Ollama running on your host machine:

1. Edit `docker-compose.yml`:
   ```yaml
   environment:
     - OLLAMA_BASE_URL=http://host.docker.internal:11434
   ```
2. Comment out or remove the `ollama` service section
3. Remove `depends_on: ollama` from `rag-app`

### GPU Support (NVIDIA Only)

If you have an NVIDIA GPU and nvidia-docker installed:

1. Uncomment the GPU section in `docker-compose.yml`:
   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: 1
             capabilities: [gpu]
   ```
2. Restart: `docker compose down && docker compose up -d`

---

## Maintenance and Updates

### Viewing Logs

**All services:**
```cmd
docker compose logs
```

**Specific service:**
```cmd
docker compose logs rag-app
docker compose logs ollama
```

**Follow logs (real-time):**
```cmd
docker compose logs -f
```

**Last N lines:**
```cmd
docker compose logs --tail=100
```

### Updating the Application

When a new version is released:

```cmd
# Pull latest code
git pull  # or download new ZIP

# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Backing Up Data

**Important directories to backup:**

1. **Vector Database** (most important):
   ```cmd
   docker compose cp rag-app:/app/vector_db ./backup/vector_db
   ```

2. **PDFs** (already on host):
   - Copy `./pdfs/` folder

3. **Data Cache** (optional):
   ```cmd
   docker compose cp rag-app:/app/data ./backup/data
   ```

### Restoring from Backup

```cmd
# Stop services
docker compose down -v

# Restore data
docker compose cp ./backup/vector_db rag-app:/app/vector_db
docker compose cp ./backup/data rag-app:/app/data

# Restart
docker compose up -d
```

### Disk Space Management

**Check space used by Docker:**
```cmd
docker system df
```

**Clean up unused resources:**
```cmd
# Remove stopped containers
docker container prune

# Remove unused images
docker image prune

# Remove unused volumes (⚠️ be careful)
docker volume prune
```

---

## Getting Help

### Log Files Location

- **Application logs**: `./logs/rag_pipeline.log` (on host)
- **Docker logs**: View with `docker compose logs`

### Common Commands Reference

```cmd
# Start
docker compose up -d

# Stop (preserves data)
docker compose stop

# Stop and remove containers (preserves volumes)
docker compose down

# View status
docker compose ps

# View logs
docker compose logs -f

# Restart a service
docker compose restart rag-app

# Rebuild after code changes
docker compose build
docker compose up -d

# Execute command in container
docker compose exec rag-app python ingest.py --help
```

### Additional Resources

- Docker Desktop Docs: https://docs.docker.com/desktop/
- Ollama Models: https://ollama.com/library
- Project README: See `README.md` in project folder

---

## Frequently Asked Questions

**Q: Do I need an internet connection after setup?**
A: No, the system runs completely offline after initial setup.

**Q: Where is my data stored?**
A: Data is stored in Docker volumes and the `pdfs/` folder in your project directory. It persists between restarts.

**Q: Can I use this on multiple PDFs simultaneously?**
A: Yes, the system can handle any number of PDFs. Just add them to the `pdfs/` folder.

**Q: How do I change which AI model is used?**
A: Edit the `OLLAMA_MODEL` environment variable in `docker-compose.yml` and restart.

**Q: Can I access this from another computer on my network?**
A: Yes, but you need to change the port binding in `docker-compose.yml` to `0.0.0.0:8000:8000` and configure your firewall.

**Q: Is my data sent to the cloud?**
A: No, everything runs locally. No data leaves your machine.

**Q: Can I run this on macOS or Linux?**
A: Yes! The same Docker setup works on all platforms. Just follow the appropriate Docker installation for your OS.

---

**Need More Help?**

Check the main `README.md` file in the project folder, or review the logs for detailed error messages.

**Ready to start? Go back to [Step 1: Install Docker Desktop](#step-1-install-docker-desktop)!** 🚀
