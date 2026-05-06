# Windows Ingestion Troubleshooting Guide

This guide helps diagnose and fix ingestion issues on Windows.

---

## Quick Diagnosis

Run the debug script first:
```cmd
DEBUG_INGESTION.bat
```

This will check:
- Docker status
- Container health
- Ollama connection
- AI models
- PDF folder contents
- Recent logs

---

## Common Issues and Solutions

### Issue 1: "No PDFs found in pdfs/ folder"

**Symptoms:**
- Web UI shows "Database is empty"
- Auto-ingestion status says "No PDFs found"

**Causes:**
1. PDFs are in the wrong location
2. PDFs are in a subfolder
3. File permissions issue

**Solutions:**

**A. Check PDF location:**
```cmd
dir pdfs\*.pdf
```
Should show your PDF files. If not found:
- Ensure PDFs are directly in `pdfs\` folder (not `pdfs\subfolder\`)
- PDFs must have `.pdf` extension (case-sensitive in Docker)

**B. Check from Docker container:**
```cmd
docker compose exec rag-app ls -la /app/pdfs
```
Should show your PDFs. If empty, there's a volume mount issue.

**C. Fix volume mount (if needed):**
Edit `docker-compose.yml`, ensure this line exists:
```yaml
volumes:
  - ./pdfs:/app/pdfs
```

Then restart:
```cmd
docker compose down
docker compose up -d
```

---

### Issue 2: "Cannot connect to Ollama" / "Failed to pull model"

**Symptoms:**
- Error: "Failed to connect to Ollama"
- Ingestion starts but fails immediately
- Models show as not downloaded

**Solutions:**

**A. Check Ollama container:**
```cmd
docker compose ps
```
Look for `medical-rag-ollama` - should show "Up" and "healthy"

**B. Restart Ollama:**
```cmd
docker compose restart ollama
```

**C. Check Ollama is accessible:**
```cmd
curl http://localhost:11434/api/tags
```
Should return JSON with model list. If error, Ollama isn't running.

**D. Download models:**
```cmd
DOWNLOAD_MODELS.bat
```
Or manually:
```cmd
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull deepseek-r1:7b
```

**E. Verify models installed:**
```cmd
docker compose exec ollama ollama list
```
Should show both `nomic-embed-text` and `deepseek-r1:7b`

---

### Issue 3: Ingestion Starts But Hangs/Freezes

**Symptoms:**
- Blue banner shows "Auto-ingestion in progress"
- Gets stuck on one file
- Never completes

**Causes:**
- Large PDF file
- Corrupted PDF
- Insufficient memory
- Ollama timeout

**Solutions:**

**A. Check logs in real-time:**
```cmd
docker compose logs -f rag-app
```
Look for:
- "Processing [filename]..." - shows which PDF is being processed
- Any error messages
- Timeout errors

**B. Increase Docker resources:**
1. Open Docker Desktop
2. Settings → Resources
3. Increase:
   - CPUs: 4+
   - Memory: 8GB+
4. Apply & Restart

**C. Try individual PDFs:**
Remove all but one PDF from `pdfs\` folder, restart, see if it works.
If successful, add PDFs back one at a time to find problematic file.

**D. Check for corrupted PDFs:**
Try opening each PDF in Adobe Reader. If one won't open, it's corrupted.

---

### Issue 4: "Path too long" or "Access Denied"

**Symptoms:**
- Error mentions path length
- Permission denied errors
- Files not accessible

**Causes:**
- Windows path length limit (260 characters)
- File permissions
- Antivirus blocking Docker

**Solutions:**

**A. Shorten installation path:**
Don't install to:
```
C:\Users\YourName\Documents\Projects\MedicalResearch\medical-research-rag\
```

Instead use:
```
C:\rag\
```

**B. Enable long paths (Windows 10+):**
1. Open Registry Editor (regedit)
2. Navigate to: `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`
3. Set `LongPathsEnabled` to `1`
4. Restart computer

**C. Check antivirus:**
Add Docker to exclusion list in Windows Defender or your antivirus.

**D. Run Docker as Administrator:**
Right-click Docker Desktop icon → Run as Administrator

---

### Issue 5: Manual Upload Not Working (Web UI)

**Symptoms:**
- Drag-and-drop doesn't work
- Upload button does nothing
- "Failed to upload" error

**Solutions:**

**A. Check file size:**
PDFs over 50MB may fail. Split large PDFs or adjust server settings.

**B. Check browser console:**
1. Press F12 in browser
2. Go to Console tab
3. Try uploading, look for errors
4. Share error messages for specific diagnosis

**C. Verify web server is running:**
```cmd
curl http://localhost:8000/health
```
Should return: `{"status":"healthy","service":"Medical Research RAG"}`

**D. Check WebSocket connection:**
In browser console, look for WebSocket errors. If found, restart containers:
```cmd
docker compose restart
```

---

### Issue 6: "All PDFs already ingested" But Database Empty

**Symptoms:**
- Message: "All 20 PDFs already ingested"
- But Metrics tab shows 0 chunks
- Can't query anything

**Cause:**
Progress tracking file says files are processed, but vector database is empty.

**Solutions:**

**A. Reset ingestion progress:**
```cmd
docker compose exec rag-app rm -f /app/data/ingestion_progress.json
docker compose restart rag-app
```

**B. Or reset entire database:**
```cmd
docker compose down -v
docker compose up -d
```
⚠️ This deletes all data! PDFs will be re-ingested from scratch.

---

### Issue 7: Windows Path Separators (\ vs /)

**Symptoms:**
- Errors mentioning paths with backslashes
- "File not found" but file exists

**Cause:**
Windows uses `\`, Docker/Linux uses `/`

**Solution:**
This should be handled automatically. If you see errors:

**In batch scripts**, use:
```batch
cd /d "%~dp0"
```

**In docker-compose.yml**, paths should use forward slashes:
```yaml
volumes:
  - ./pdfs:/app/pdfs  # Correct
  - .\pdfs:/app/pdfs  # Wrong on Windows with Docker
```

---

## Verification Steps

After fixing, verify ingestion is working:

### 1. Check Auto-Ingestion Status:
```cmd
curl http://localhost:8000/api/auto-ingest/status
```

### 2. Check Database Has Chunks:
Open http://localhost:8000 → Metrics tab
- "Total Chunks" should be > 0
- "Files Processed" should show your PDF count

### 3. Test Query:
Open http://localhost:8000 → Query tab
- Type: "What are the main topics?"
- Should return results with citations

---

## Live Monitoring

Watch ingestion in real-time:

```cmd
docker compose logs -f rag-app
```

You should see:
```
Auto-ingestion: Starting ingestion of 20 new PDF(s)
Auto-ingestion: Processing filename.pdf (1/20)...
Successfully processed filename.pdf (45 chunks)
Auto-ingestion: Processing filename2.pdf (2/20)...
```

Press `Ctrl+C` to stop watching (containers keep running).

---

## Advanced Debugging

### Get Inside the Container:
```cmd
docker compose exec rag-app bash
```

Then inside container:
```bash
ls -la /app/pdfs          # List PDFs
cat /app/logs/rag_pipeline.log  # View logs
python -c "from pathlib import Path; print(list(Path('pdfs').glob('*.pdf')))"  # Test PDF detection
exit  # Exit container
```

### Check Environment Variables:
```cmd
docker compose exec rag-app env | findstr OLLAMA
```
Should show:
```
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=deepseek-r1:7b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

### Test Ollama Directly:
```cmd
curl -X POST http://localhost:11434/api/embeddings -d "{\"model\":\"nomic-embed-text\",\"prompt\":\"test\"}"
```
Should return embedding vector.

---

## Still Not Working?

1. **Collect diagnostic info:**
   ```cmd
   DEBUG_INGESTION.bat > debug_output.txt
   ```

2. **Check these log files:**
   - `logs\rag_pipeline.log` (on host)
   - Docker container logs: `docker compose logs rag-app > rag_logs.txt`
   - Docker Desktop logs: Docker Desktop → Troubleshoot → Get support

3. **Share details:**
   - What error messages appear?
   - Output of `DEBUG_INGESTION.bat`
   - Screenshot of web UI showing error
   - Which Windows version? (run `winver`)
   - Docker Desktop version?

4. **Try minimal test:**
   - Stop containers: `STOP_APP.bat`
   - Remove all but ONE small PDF from pdfs folder
   - Start: `START_APP.bat`
   - Watch logs: `docker compose logs -f rag-app`
   - Does single PDF work?

---

## Quick Fixes Summary

| Problem | Quick Fix |
|---------|-----------|
| No PDFs found | Put PDFs directly in `pdfs\` folder |
| Can't connect to Ollama | `docker compose restart ollama` |
| Models missing | Run `DOWNLOAD_MODELS.bat` |
| Hanging on one PDF | Check logs, increase Docker RAM |
| Database empty after ingestion | Delete `data\ingestion_progress.json`, restart |
| Permission errors | Run Docker as Administrator |
| Path too long | Install closer to C:\ drive root |

---

## Prevention

To avoid issues in the future:

1. ✅ Always use `START_APP.bat` (not direct docker commands)
2. ✅ Keep Docker Desktop updated
3. ✅ Ensure Docker has enough resources (4+ CPUs, 8GB+ RAM)
4. ✅ Put PDFs directly in pdfs\ folder (not subfolders)
5. ✅ Download models before ingesting: `DOWNLOAD_MODELS.bat`
6. ✅ Check status regularly: `CHECK_STATUS.bat`

---

**Need more help?** Check:
- [DOCKER_SETUP.md](DOCKER_SETUP.md) - Detailed setup guide
- [README.md](README.md) - Full documentation
- GitHub Issues: https://github.com/MoCode98/medical-research-rag/issues
