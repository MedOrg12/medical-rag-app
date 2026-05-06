# Quick Reference Card

## 🚀 Getting Started (3 Commands)

```bash
./setup.sh                    # 1. Setup (one time)
python ingest.py              # 2. Process PDFs
python query.py --interactive # 3. Start querying
```

## 📝 Common Commands

### Ingestion
```bash
python ingest.py                    # Process all PDFs
python ingest.py --reset            # Reset database and re-ingest
python ingest.py --generate-finetune # Generate training data
```

### Querying
```bash
# Interactive mode
python query.py --interactive

# Single query
python query.py "What is the methodology?"

# Batch queries
python query.py --batch queries.txt

# With options
python query.py --top-k 10 --verbose "Question here"
python query.py --model llama3.2 --interactive
```

## 🔧 Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Main configuration |
| `requirements.txt` | Python dependencies |
| `Modelfile` | Custom Ollama model |
| `queries.txt` | Sample queries |

## 📂 Important Directories

| Directory | Contents |
|-----------|----------|
| `pdfs/` | Your PDF files (20 stroke papers) |
| `vector_db/` | Vector database (auto-created) |
| `data/` | Processed documents, datasets |
| `logs/` | Application logs |
| `src/` | Source code |

## 🎯 Key Configuration Options (.env)

```bash
# Change model
OLLAMA_MODEL=llama3.2

# Adjust chunk size
CHUNK_SIZE=1024

# More retrieval results
TOP_K_RESULTS=10

# More creative responses
TEMPERATURE=0.7

# Change PDF folder
PDF_FOLDER=./my_pdfs
```

## 🛠️ Ollama Commands

```bash
# Check if running
curl http://localhost:11434

# Start server
ollama serve

# List models
ollama list

# Pull models
ollama pull nomic-embed-text
ollama pull deepseek-r1:7b

# Create custom model
ollama create medical-assistant -f Modelfile

# Test model
ollama run medical-assistant
```

## 📊 Project Status

| Component | Status | Location |
|-----------|--------|----------|
| PDFs | ✅ 20 files | `./pdfs/` |
| Source Code | ✅ Complete | `./src/` |
| Documentation | ✅ Complete | `*.md` files |
| Configuration | ✅ Ready | `.env` |
| Scripts | ✅ Ready | `*.py`, `*.sh` |

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect to Ollama" | Run `ollama serve` |
| "Model not found" | Run `ollama pull nomic-embed-text` |
| "Empty database" | Run `python ingest.py` |
| "No PDFs found" | Check `ls pdfs/*.pdf` (should show 20 files) |
| PDF parsing fails | Check if PDF is corrupted/password-protected |

## 📖 Documentation

| File | Purpose |
|------|---------|
| `README.md` | Comprehensive guide |
| `QUICKSTART.md` | 5-minute setup |
| `ARCHITECTURE.md` | System diagrams |
| `PROJECT_SUMMARY.md` | Project overview |
| `STATUS.md` | Current status |
| This file | Quick reference |

## 💡 Example Queries

```bash
# General
"What are the main findings?"
"Describe the methodology used"
"What are the limitations?"

# Specific to stroke research
"What are the risk factors for stroke?"
"What rehabilitation approaches are discussed?"
"What are the sex differences in stroke outcomes?"
"What is the role of hypertension in stroke?"
```

## 🎓 Usage Patterns

### One-Time Setup
```bash
cd "/Users/User/healthcare project"
./setup.sh
python ingest.py
```

### Daily Usage
```bash
# Activate environment
source venv/bin/activate

# Query your research
python query.py --interactive

# Or single query
python query.py "Your question"
```

### Re-ingestion (when adding PDFs)
```bash
# Add new PDFs to ./pdfs/
cp new_paper.pdf ./pdfs/

# Re-ingest with reset
python ingest.py --reset
```

## 🔍 Query Options

| Option | Short | Description |
|--------|-------|-------------|
| `--interactive` | `-i` | Interactive session |
| `--batch FILE` | `-b` | Batch queries from file |
| `--output FILE` | `-o` | Save results to JSON |
| `--model MODEL` | `-m` | Use specific model |
| `--top-k N` | `-k` | Retrieve N chunks |
| `--temperature T` | `-t` | Set temperature |
| `--verbose` | `-v` | Show context chunks |

## 📈 Performance Tips

### Faster Queries
- Use smaller models: `gemma3:4b`
- Reduce `TOP_K_RESULTS` to 3
- Lower `CHUNK_SIZE` to 256

### Better Quality
- Use larger models: `deepseek-r1:7b` or bigger
- Increase `TOP_K_RESULTS` to 10
- Raise `CHUNK_SIZE` to 1024
- Set `TEMPERATURE` to 0.1

## 🔐 Privacy Notes

✅ **100% Local Processing**
- No data sent to external servers
- No API keys required
- No internet connection needed (after models downloaded)
- Complete data privacy

## 📞 Getting Help

1. Check logs: `cat logs/rag_pipeline.log`
2. Read README: `less README.md`
3. Check status: `cat STATUS.md`
4. Test connection: `curl http://localhost:11434`

## 🎯 File Locations

```bash
# Logs
./logs/rag_pipeline.log

# Configuration
./.env

# Database
./vector_db/

# Processed data
./data/parsed_documents.json
./data/finetune_alpaca.jsonl

# Your PDFs
./pdfs/*.pdf  # 20 stroke research papers
```

## ⚡ Quick Commands

```bash
# Check everything is ready
ls pdfs/*.pdf              # Should show 20 PDFs
ollama list                # Should show models
python -c "import src"     # Should have no errors

# Full pipeline
python ingest.py && python query.py --interactive

# Stats only (in interactive mode)
python query.py --interactive
> stats
```

## 🎨 Custom Model

```bash
# Build custom medical model
ollama create medical-assistant -f Modelfile

# Update .env to use it
echo "OLLAMA_MODEL=medical-assistant" >> .env

# Use it
python query.py --model medical-assistant --interactive
```

## 📦 Dependencies

**Required:**
- Python 3.10+
- Ollama
- ~8GB disk space

**Installed by setup.sh:**
- All Python packages from requirements.txt
- Virtual environment

## 🌟 Key Features

✅ Structure-preserving PDF parsing
✅ Section-aware chunking
✅ Local embeddings (nomic-embed-text)
✅ Vector search (ChromaDB)
✅ Source citations with page numbers
✅ Interactive/batch/single query modes
✅ Fine-tuning dataset generation
✅ Custom medical assistant model
✅ Comprehensive error handling
✅ Structured logging

---

**Keep this file handy for quick reference!** 🚀
