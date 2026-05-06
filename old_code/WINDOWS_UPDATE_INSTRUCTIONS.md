# Windows Update Instructions
## Critical Bug Fixes for Medical Research RAG

**Last Updated:** 2026-03-16

This document lists all files that need to be updated on your Windows machine to fix the bugs discovered during testing.

---

## Summary of Issues Fixed

1. ✅ **Slowapi rate limiting** - Fixed parameter naming
2. ✅ **Ollama client connection (embeddings)** - Fixed Docker hostname configuration
3. ✅ **Auto-ingestion bugs** - Fixed Path object handling and method names
4. ✅ **Ollama client connection (RAG queries)** - Fixed Docker hostname for answer generation
5. ✅ **Progress tracking persistence** - Fixed so PDFs aren't re-ingested on restart
6. ✅ **DOWNLOAD_MODELS.bat** - Fixed container name check
7. ✅ **Installer configuration** - Added missing files

---

## Files to Update on Windows

### Critical Files (Must Update)

These 5 files **must** be updated for the application to work:

#### 1. `src/embeddings.py`
**Location:** `C:\Program Files\MedicalResearchRAG\src\embeddings.py`

**Changes:**
- Line 29-30: Fixed type hints for optional parameters
- Line 48: Added `self.ollama_client = ollama.Client(host=self.base_url)`
- Line 101: Changed `ollama.pull()` to `self.ollama_client.pull()`
- Line 140: Changed `ollama.embeddings()` to `self.ollama_client.embeddings()`

**Why:** Fixes Ollama connection to use Docker container hostname instead of localhost.

#### 2. `app.py`
**Location:** `C:\Program Files\MedicalResearchRAG\app.py`

**Changes:**
- Line 185: Changed `str(pdf_path)` to `pdf_path` (pass Path object)
- Line 197: Changed `progress.mark_file_processed()` to `progress.mark_processed()`
- Line 205: Changed `progress.mark_file_failed()` to `progress.mark_failed()`

**Why:** Fixes auto-ingestion bugs that prevented PDFs from being processed.

#### 3. `src/rag_pipeline.py`
**Location:** `C:\Program Files\MedicalResearchRAG\src\rag_pipeline.py`

**Changes:**
- Line 38: Added `base_url: str | None = None` parameter
- Line 56: Added `self.base_url = base_url or settings.ollama_base_url`
- Line 61: Added `self.ollama_client = ollama.Client(host=self.base_url)`
- Line 94: Changed `ollama.list()` to `self.ollama_client.list()`
- Line 185: Changed `ollama.chat()` to `self.ollama_client.chat()`

**Why:** Fixes Ollama connection for query/answer generation to use Docker container hostname.

#### 4. `src/ingestion_progress.py`
**Location:** `C:\Program Files\MedicalResearchRAG\src\ingestion_progress.py`

**Changes:**
- Line 136: Added `"processed_files": list(self.processed_files),` to get_status() return dict

**Why:** Fixes progress tracking so PDFs don't get re-ingested on every container restart. Without this, the system can't remember which files were already processed.

#### 5. `api/query.py` (Additional Fix)
**Location:** `C:\Program Files\MedicalResearchRAG\api\query.py`

**Changes:**
- Line 121: Changed `request.return_context` to `query_request.return_context`

**Why:** Fixes query response error after renaming parameter. Without this, queries succeed but return 500 error to user.

---

### Optional Files (For Future Installer)

These files improve the installer but aren't needed for current operation:

#### 3. `DOWNLOAD_MODELS.bat`
**Location:** `C:\Program Files\MedicalResearchRAG\DOWNLOAD_MODELS.bat`

**Changes:**
- Line 23: Changed `findstr "medical-rag-ollama"` to `findstr "ollama"`

**Why:** Fixes container name detection.

#### 4. `installer.iss`
**Location:** `C:\Program Files\MedicalResearchRAG\installer.iss`

**Changes:**
- Added `DEBUG_INGESTION.bat` to batch scripts section
- Added `scripts\*` folder with backup/restore/metadata tools
- Added missing documentation files
- Added "Debug Ingestion" shortcut to Start Menu

**Why:** Improves installer completeness for distribution.

---

## Quick Update Method

### Option 1: Update Just the Critical Files (5 minutes)

1. **Transfer from Mac to Windows:**
   - Copy these files: `src/embeddings.py`, `src/rag_pipeline.py`, `src/ingestion_progress.py`, `api/query.py`, and `app.py`
   - Use USB drive, email, or OneDrive

2. **Replace on Windows:**
   ```powershell
   # Replace these files:
   C:\Program Files\MedicalResearchRAG\src\embeddings.py
   C:\Program Files\MedicalResearchRAG\src\rag_pipeline.py
   C:\Program Files\MedicalResearchRAG\src\ingestion_progress.py
   C:\Program Files\MedicalResearchRAG\api\query.py
   C:\Program Files\MedicalResearchRAG\app.py
   ```

3. **Rebuild Docker:**
   ```powershell
   cd "C:\Program Files\MedicalResearchRAG"
   docker compose down
   docker compose build --no-cache
   docker compose up -d
   docker compose logs -f rag-app
   ```

### Option 2: Transfer Entire Project (15 minutes)

If you want all updates including optional files:

1. **Transfer entire project** from Mac to Windows via USB
2. **Copy to:** `C:\Program Files\MedicalResearchRAG`
3. **Rebuild Docker** (same commands as Option 1)

---

## Expected Result After Update

After rebuilding Docker, you should see in the logs:

```
✓ Successfully connected to Ollama at http://ollama:11434
✓ Embedding model 'nomic-embed-text' is available
✓ Auto-ingestion: Processing 1-s2.0-S000293432100512X-main.pdf (1/18)
✓ Auto-ingestion: Successfully processed ... (X chunks)
...
✓ Auto-ingestion complete! Processed 18 PDFs
```

Then the web UI at http://localhost:8000 will be fully functional:
- **Ingest Tab:** Shows 18 PDFs ingested (862 total chunks)
- **Query Tab:** Can ask questions and get AI-generated answers with citations
- **Metrics Tab:** Shows database statistics (862 documents)

---

## Troubleshooting

### If Docker build fails:
```powershell
# Clear Docker cache
docker system prune -a

# Rebuild
docker compose build --no-cache
docker compose up -d
```

### If containers won't start:
```powershell
# Check logs
docker compose logs ollama
docker compose logs rag-app

# Restart Docker Desktop
# Then try again
docker compose up -d
```

### If models aren't found:
```powershell
# Check models exist
docker compose exec ollama ollama list

# Should show:
# nomic-embed-text:latest
# deepseek-r1:7b:latest
```

---

## File Sizes for Reference

To verify you have the correct updated files:

| File | Approximate Size |
|------|-----------------|
| src/embeddings.py | ~12 KB |
| src/rag_pipeline.py | ~11 KB |
| src/ingestion_progress.py | ~6 KB |
| api/query.py | ~5 KB |
| app.py | ~9 KB |
| DOWNLOAD_MODELS.bat | ~2 KB |
| installer.iss | ~5 KB |

---

## Next Steps After Update

1. **Test auto-ingestion:** Check logs show PDFs being processed
2. **Test web UI:** Open http://localhost:8000
3. **Test queries:** Ask "What are the risk factors for stroke?"
4. **Test manual upload:** Upload a new PDF via the Ingest tab
5. **Rebuild installer:** (Optional) For distribution to others

---

## Rebuilding Installer (Optional)

After verifying everything works, rebuild the installer for distribution:

```powershell
cd "C:\path\to\project"

# Open Inno Setup Compiler
# File -> Open -> installer.iss
# Build -> Compile

# Output: installer_output\MedicalResearchRAG_Setup.exe
```

---

## Summary Checklist

- [ ] Transfer `src/embeddings.py` to Windows
- [ ] Transfer `src/rag_pipeline.py` to Windows
- [ ] Transfer `src/ingestion_progress.py` to Windows
- [ ] Transfer `api/query.py` to Windows
- [ ] Transfer `app.py` to Windows
- [ ] Replace files at `C:\Program Files\MedicalResearchRAG`
- [ ] Stop Docker containers (`docker compose down`)
- [ ] Rebuild Docker (`docker compose build --no-cache`)
- [ ] Start Docker (`docker compose up -d`)
- [ ] Check logs (`docker compose logs -f rag-app`)
- [ ] Verify auto-ingestion completes successfully
- [ ] Test web UI at http://localhost:8000
- [ ] Test query functionality
- [ ] (Optional) Rebuild installer for distribution

---

## Questions?

If you encounter any issues:

1. Check Docker Desktop is running
2. Check containers are up: `docker ps`
3. Check logs: `docker compose logs rag-app`
4. Verify models exist: `docker compose exec ollama ollama list`

**Everything should work after updating these 5 critical files and rebuilding Docker!** 🚀

---

## What This Fix Does

With the `ingestion_progress.py` fix, your system will now:

1. **First startup:** Ingest all 18 PDFs (takes 5-10 minutes)
2. **Save progress** to `/app/data/ingestion_progress.json` (persisted in Docker volume)
3. **Container restart:** Skip already-processed PDFs, show "All 18 PDFs already ingested. Ready to query."
4. **Add new PDFs:** Only ingest the NEW ones, skip the 18 already processed

**Before fix:** Re-ingests all PDFs every time (wastes 5-10 minutes on each restart)
**After fix:** Instant startup - just loads existing data from vector database
