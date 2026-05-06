# Medical RAG - Docker Setup Guide for Windows

This guide covers setting up and running the Medical RAG application using Docker on Windows with WSL 2.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Application](#running-the-application)
5. [Troubleshooting](#troubleshooting)
6. [Maintenance](#maintenance)

---

## Prerequisites

### Required Software

1. **Windows 10/11** (64-bit, version 1903 or higher)
   - Home, Pro, or Enterprise editions

2. **WSL 2 (Windows Subsystem for Linux 2)**
   - Required for Docker Desktop on Windows
   - Provides Linux kernel for Docker containers

3. **Docker Desktop for Windows**
   - Version 4.0.0 or higher recommended
   - Includes Docker Engine and Docker Compose

### System Requirements

- **CPU**: 4+ cores recommended (2 minimum)
- **RAM**: 16 GB recommended (8 GB minimum)
- **Disk**: 20 GB free space minimum
  - ~5 GB for Docker images
  - ~4-5 GB per AI model
  - ~2 GB for vector database (grows with more PDFs)
  - ~5 GB for PDFs and logs

---

## Installation

### Step 1: Install WSL 2

1. **Open PowerShell as Administrator** and run:

   ```powershell
   wsl --install
   ```

2. **Restart your computer** when prompted

3. **Verify installation**:

   ```powershell
   wsl --list --verbose
   ```

   You should see Ubuntu or another Linux distribution listed with VERSION 2.

### Step 2: Install Docker Desktop

1. **Download Docker Desktop**:
   - Visit: https://www.docker.com/products/docker-desktop/
   - Download Docker Desktop for Windows

2. **Run the installer**:
   - Double-click `Docker Desktop Installer.exe`
   - Follow the installation wizard
   - Enable "Use WSL 2 instead of Hyper-V" option

3. **Start Docker Desktop**:
   - Launch Docker Desktop from Start Menu
   - Wait for Docker to start (whale icon in system tray)

4. **Verify installation**:

   ```powershell
   docker --version
   docker compose version
   ```

### Step 3: Clone the Repository

```powershell
# Navigate to your projects directory
cd C:\Users\YourUsername\Projects

# Clone the repository
git clone https://github.com/YourUsername/medical-rag-app.git
cd medical-rag-app
```

---

## Configuration

### Environment Variables (Optional)

The application uses sensible defaults, but you can customize settings by creating a `.env` file:

```bash
# Copy example configuration
copy .env.example .env

# Edit with your preferred text editor
notepad .env
```

**Available Configuration Options**:

```env
# Ollama Configuration
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=deepseek-llm:7b-chat
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Vector Database
VECTOR_DB_PATH=/app/vector_db
VECTOR_DB_TYPE=chroma

# Paths
PDF_FOLDER=/app/pdfs
DATA_FOLDER=/app/data

# Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=200

# Retrieval
TOP_K=5
SIMILARITY_THRESHOLD=0.7
```

### GPU Support (Optional)

If you have an NVIDIA GPU and want to use it for faster AI inference:

1. **Install NVIDIA Container Toolkit**:
   - Follow guide: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

2. **Uncomment GPU section in docker-compose.yml**:

   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: 1
             capabilities: [gpu]
   ```

---

## Running the Application

### Quick Start

1. **Navigate to project directory**:

   ```powershell
   cd C:\Users\YourUsername\Projects\medical-rag-app
   ```

2. **Start the application**:

   ```powershell
   docker compose up -d
   ```

   This will:
   - Download required Docker images (~2 GB)
   - Start Ollama service
   - Start Medical RAG application
   - Download AI models (~4-5 GB, first run only)
   - Ingest bundled PDFs (~2-5 minutes, first run only)

3. **Wait for initialization**:

   Monitor the logs to see progress:

   ```powershell
   docker compose logs -f medical-rag
   ```

   Look for: `"Web interface will be available at: http://localhost:8000"`

4. **Access the application**:

   Open your browser to: **http://localhost:8000**

### First Run

The first time you run the application:

1. **Model download** (~5-10 minutes):
   - Downloads `deepseek-llm:7b-chat` (~4 GB)
   - Downloads `nomic-embed-text` (~300 MB)

2. **PDF ingestion** (~2-5 minutes):
   - Processes bundled medical research PDFs
   - Creates vector embeddings
   - Stores in ChromaDB

**Total first run time**: 10-15 minutes

### Subsequent Runs

After the first run, the application starts in ~10-30 seconds because:
- Models are already downloaded
- PDFs are already ingested (unless you add new ones)

### Stopping the Application

```powershell
# Stop containers (keeps data)
docker compose stop

# Stop and remove containers (keeps data volumes)
docker compose down

# Stop and remove everything including data
docker compose down -v
```

---

## Adding Your Own PDFs

### Option 1: Add PDFs Before Starting

1. **Place PDFs in the pdfs folder**:

   ```powershell
   copy "C:\path\to\your\research.pdf" ".\pdfs\"
   ```

2. **Start the application**:

   ```powershell
   docker compose up -d
   ```

   New PDFs will be automatically ingested on startup.

### Option 2: Add PDFs While Running

1. **Upload via web interface**:
   - Go to http://localhost:8000
   - Click "Upload PDF" button
   - Select your PDF file
   - Wait for processing

2. **Or copy to folder and restart**:

   ```powershell
   # Copy new PDFs
   copy "C:\path\to\your\research.pdf" ".\pdfs\"

   # Restart to trigger ingestion
   docker compose restart medical-rag
   ```

---

## Viewing Logs

### All Services

```powershell
docker compose logs -f
```

### Specific Service

```powershell
# Medical RAG application
docker compose logs -f medical-rag

# Ollama service
docker compose logs -f ollama
```

### Log Files

Application logs are also saved to `./logs/` folder:

```powershell
# View latest logs
type .\logs\medical_rag.log

# Monitor logs in real-time (PowerShell)
Get-Content .\logs\medical_rag.log -Wait -Tail 50
```

---

## Troubleshooting

### Issue: Docker Desktop won't start

**Symptoms**: Docker Desktop stuck on "Starting..." or shows error

**Solutions**:

1. **Restart Docker Desktop**:
   - Right-click Docker icon → Quit Docker Desktop
   - Start Docker Desktop again

2. **Restart WSL**:

   ```powershell
   wsl --shutdown
   # Wait 10 seconds
   wsl
   ```

3. **Check WSL 2**:

   ```powershell
   wsl --set-default-version 2
   ```

### Issue: "Connection refused" to Ollama

**Symptoms**: Application logs show "Failed to connect to Ollama"

**Solutions**:

1. **Check if Ollama is running**:

   ```powershell
   docker compose ps
   ```

   Ollama should show "healthy" status.

2. **Check Ollama logs**:

   ```powershell
   docker compose logs ollama
   ```

3. **Restart services**:

   ```powershell
   docker compose restart ollama
   docker compose restart medical-rag
   ```

### Issue: Model download fails

**Symptoms**: "Failed to pull model" in logs

**Solutions**:

1. **Check internet connection**

2. **Try manual model download**:

   ```powershell
   docker compose exec ollama ollama pull deepseek-llm:7b-chat
   docker compose exec ollama ollama pull nomic-embed-text
   ```

3. **Increase timeout**:

   If download is slow, wait longer. Large models can take 10-15 minutes on slower connections.

### Issue: PDFs not ingesting

**Symptoms**: "0 PDFs found" or ingestion errors

**Solutions**:

1. **Check PDF folder**:

   ```powershell
   dir .\pdfs\*.pdf
   ```

2. **Check file permissions**:

   ```powershell
   # The entrypoint script sets permissions, but you can verify:
   docker compose exec medical-rag ls -la /app/pdfs
   ```

3. **Check logs for errors**:

   ```powershell
   docker compose logs medical-rag | findstr "ERROR"
   ```

### Issue: High CPU/Memory usage

**Symptoms**: Computer runs slowly, Docker uses too many resources

**Solutions**:

1. **Limit Docker resources**:
   - Docker Desktop → Settings → Resources
   - Reduce CPUs to 2-4
   - Reduce Memory to 4-8 GB

2. **Limit in docker-compose.yml**:

   Uncomment and adjust the resources section:

   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 4G
   ```

3. **Use a smaller model**:

   Change model in `.env`:

   ```env
   OLLAMA_MODEL=deepseek-llm:1.5b
   ```

### Issue: Port 8000 already in use

**Symptoms**: "Address already in use" error

**Solutions**:

1. **Find process using port 8000**:

   ```powershell
   netstat -ano | findstr :8000
   ```

2. **Kill the process**:

   ```powershell
   taskkill /PID <PID_NUMBER> /F
   ```

3. **Or change the port** in `docker-compose.yml`:

   ```yaml
   ports:
     - "8080:8000"  # Use port 8080 instead
   ```

---

## Maintenance

### Updating the Application

```powershell
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Clearing Cache and Starting Fresh

```powershell
# Remove all data (models, vector DB, everything)
docker compose down -v

# Restart
docker compose up -d
```

**Warning**: This will delete all ingested PDFs and require re-downloading models (~4-5 GB).

### Backup Your Data

```powershell
# Backup vector database
docker run --rm -v medical-rag-app_vector_db:/data -v C:\Backups:/backup ubuntu tar czf /backup/vector_db_backup.tar.gz /data

# Backup PDFs and logs (already on host)
xcopy /E /I .\pdfs C:\Backups\pdfs
xcopy /E /I .\logs C:\Backups\logs
```

### Viewing Resource Usage

```powershell
docker stats
```

Press `Ctrl+C` to exit.

---

## Performance Notes

### Expected Performance (Windows with WSL 2)

- **First query**: 5-15 seconds (model warm-up)
- **Subsequent queries**: 2-5 seconds
- **PDF ingestion**: ~30-60 seconds per PDF

### Comparison to Native Windows .exe

| Metric | Docker | Native .exe |
|--------|--------|-------------|
| Startup time | 10-30s | 5-10s |
| Query speed | Same | Same |
| Resource usage | Higher | Lower |
| Setup complexity | Medium | Low |
| Multi-user | ✅ Yes | ❌ No |
| Cloud hosting | ✅ Yes | ❌ No |

**Recommendation**:
- Use **Docker** for servers, cloud hosting, or multi-user deployments
- Use **native .exe** for single-user Windows desktops

---

## Advanced Configuration

### Custom Ollama Models

To use different models:

1. **Edit .env**:

   ```env
   OLLAMA_MODEL=llama2:13b
   ```

2. **Restart**:

   ```powershell
   docker compose down
   docker compose up -d
   ```

### Scaling for Multiple Users

If deploying for multiple users:

1. **Increase resource limits** in docker-compose.yml:

   ```yaml
   deploy:
     resources:
       limits:
         cpus: '8'
         memory: 16G
   ```

2. **Enable rate limiting**: Already configured in application

3. **Monitor performance**:

   ```powershell
   docker stats
   ```

---

## Getting Help

- **GitHub Issues**: https://github.com/YourUsername/medical-rag-app/issues
- **Docker Documentation**: https://docs.docker.com/desktop/windows/
- **WSL 2 Documentation**: https://learn.microsoft.com/en-us/windows/wsl/

---

## License

This application is provided as-is for medical research purposes.
