# Medical Research RAG - Installation Guide

Complete guide for installing and deploying the Medical Research RAG system on any computer.

---

## 📋 Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation Methods](#installation-methods)
3. [Method 1: Standard Installation](#method-1-standard-installation-recommended)
4. [Method 2: Development Installation](#method-2-development-installation)
5. [Method 3: Portable Package](#method-3-portable-package)
6. [Post-Installation Setup](#post-installation-setup)
7. [Verification](#verification)
8. [Troubleshooting](#troubleshooting)

---

## System Requirements

### Minimum Requirements
- **OS**: Linux, macOS, or Windows 10/11
- **Python**: 3.10 or higher
- **RAM**: 8GB (16GB recommended)
- **Disk Space**: 10GB free space
- **CPU**: Multi-core processor (4+ cores recommended)

### Required Software
- **Ollama**: For local LLM and embeddings
- **Git**: For cloning repository (optional)

### Recommended for Best Performance
- **RAM**: 16GB+
- **GPU**: NVIDIA GPU with CUDA support (optional, speeds up embeddings)
- **SSD**: For faster database operations

---

## Installation Methods

Choose the method that best fits your needs:

| Method | Best For | Pros | Cons |
|--------|----------|------|------|
| **Standard** | Most users | Simple, full control | Requires Python setup |
| **Development** | Contributors | Editable install | More complex |
| **Portable** | Quick sharing | Pre-configured | Larger file size |

---

## Method 1: Standard Installation (Recommended)

### Step 1: Install Ollama

**macOS/Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:**
Download from [ollama.com/download](https://ollama.com/download)

**Verify installation:**
```bash
ollama --version
```

### Step 2: Pull Required Models

```bash
# Embedding model (required)
ollama pull nomic-embed-text

# LLM models (choose one or more)
ollama pull llama3.2:3b       # Fastest (3B params)
ollama pull llama3.2:1b       # Ultra-fast (1B params)
ollama pull mistral:7b        # Balanced (7B params)
ollama pull llama3.1:8b       # High quality (8B params)
```

### Step 3: Clone or Download the Project

**Option A: Using Git**
```bash
git clone https://github.com/yourusername/medical-research-rag.git
cd medical-research-rag
```

**Option B: Download ZIP**
1. Download project ZIP file
2. Extract to desired location
3. Open terminal in extracted folder

### Step 4: Set Up Python Environment

**Create virtual environment:**
```bash
# Create venv
python3 -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate
```

### Step 5: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt
```

### Step 6: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Use your preferred text editor
nano .env  # or vim, code, etc.
```

**Minimal .env configuration:**
```env
# Folders
PDF_FOLDER=./pdfs
DATA_FOLDER=./data
CHROMA_DB_PATH=./chroma_db

# Ollama settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Chunk settings
CHUNK_SIZE=768
CHUNK_OVERLAP=100

# Retrieval
TOP_K_RESULTS=5
TEMPERATURE=0.2
```

### Step 7: Add Your PDFs

```bash
# Create PDF folder
mkdir -p pdfs

# Copy your PDF files
cp /path/to/your/pdfs/*.pdf pdfs/
```

### Step 8: Run Initial Ingestion

```bash
# Ingest PDFs into vector database
python ingest.py
```

This will:
- Parse all PDFs in `./pdfs`
- Extract text, tables, figures, references
- Chunk intelligently
- Generate embeddings
- Store in ChromaDB

**Expected output:**
```
Parsed 5 PDFs
Created 347 chunks
Stored in vector database
```

### Step 9: Start Querying

```bash
# Interactive mode with all features
python query_enhanced.py --all-features --interactive

# Or single query
python query_enhanced.py --hybrid --rerank "What is stroke prevention?"
```

---

## Method 2: Development Installation

For contributors or those wanting to modify the code.

### Steps 1-4: Same as Method 1

Follow Steps 1-4 from Standard Installation.

### Step 5: Install in Editable Mode

```bash
# Install package in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

### Step 6: Install Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install
```

### Step 7: Run Tests

```bash
# Install pytest if not already
pip install pytest pytest-cov

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

### Step 8: Continue with Standard Installation

Follow Steps 6-9 from Method 1.

---

## Method 3: Portable Package

Create a self-contained package for easy sharing.

### For Package Creator:

```bash
# Run the packaging script
python create_portable_package.py

# This creates:
# medical-rag-portable-v2.1.0.zip
```

### For Package Recipient:

**Step 1: Extract Package**
```bash
# Extract ZIP
unzip medical-rag-portable-v2.1.0.zip
cd medical-rag-portable
```

**Step 2: Run Setup Script**

**macOS/Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows:**
```cmd
setup.bat
```

The setup script will:
- Check Python version
- Install Ollama if needed
- Create virtual environment
- Install dependencies
- Pull required models
- Configure environment

**Step 3: Add PDFs and Run**
```bash
# Copy PDFs
cp /path/to/pdfs/*.pdf pdfs/

# Activate environment
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Ingest
python ingest.py

# Query
python query_enhanced.py --interactive --all-features
```

---

## Post-Installation Setup

### Create Custom Ollama Modelfile (Optional)

```bash
# Create Modelfile
cat > Modelfile <<EOF
FROM llama3.2:3b

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER top_k 40

SYSTEM """You are a medical research assistant. Provide accurate, evidence-based answers.
When citing sources, always reference the specific studies mentioned in the context.
Be precise with statistics and medical terminology."""
EOF

# Create custom model
ollama create medical-research-assistant -f Modelfile

# Update .env to use custom model
# OLLAMA_MODEL=medical-research-assistant
```

### Configure Logging

```bash
# Create logs directory
mkdir -p logs

# Log configuration is in src/logger.py
# Logs are automatically written to logs/rag_pipeline.log
```

### Optimize ChromaDB

```bash
# For large document collections, adjust settings in .env:
# CHROMA_DB_PATH=./chroma_db
# TOP_K_RESULTS=10  # Increase for more comprehensive results
```

---

## Verification

### Quick Health Check

```bash
# Run verification script
python -c "
from src import ConversationalRAG
print('✓ All imports working')

import ollama
print('✓ Ollama accessible')
ollama.list()
print('✓ Ollama models loaded')
"
```

### Full System Test

```bash
# Test all modules
python -m src.enhanced_pdf_parser
python -m src.question_classifier
python -m src.reranker
python -m src.conversation

# Test query with sample
python query_enhanced.py --hybrid "What is hypertension?"
```

### Expected Results

All tests should pass without errors. If you see:
```
✓ All imports working
✓ Ollama accessible
✓ Ollama models loaded
```

Your installation is successful!

---

## Troubleshooting

### Issue: Ollama Connection Error

**Error:**
```
Error connecting to Ollama: Connection refused
```

**Solution:**
```bash
# Check if Ollama is running
ollama list

# Start Ollama service
ollama serve

# Check URL in .env matches
# OLLAMA_BASE_URL=http://localhost:11434
```

### Issue: Module Import Errors

**Error:**
```
ModuleNotFoundError: No module named 'src'
```

**Solution:**
```bash
# Ensure you're in project root
pwd  # Should show .../medical-research-rag

# Activate virtual environment
source venv/bin/activate

# Reinstall if needed
pip install -r requirements.txt
```

### Issue: ChromaDB Permission Error

**Error:**
```
PermissionError: [Errno 13] Permission denied: 'chroma_db'
```

**Solution:**
```bash
# Fix permissions
chmod -R 755 chroma_db/

# Or delete and recreate
rm -rf chroma_db/
python ingest.py
```

### Issue: Out of Memory

**Error:**
```
RuntimeError: Out of memory
```

**Solution:**
1. Use smaller model: `ollama pull llama3.2:1b`
2. Reduce batch size in config
3. Process fewer PDFs at once
4. Close other applications

### Issue: Slow Performance

**Solutions:**
1. **Use faster model:** Switch to `llama3.2:1b` or `llama3.2:3b`
2. **Disable features:** Use `--hybrid` only instead of `--all-features`
3. **Reduce top_k:** Set `TOP_K_RESULTS=3` in .env
4. **GPU acceleration:** Install CUDA if using NVIDIA GPU

### Issue: Models Not Found

**Error:**
```
Model 'nomic-embed-text' not found
```

**Solution:**
```bash
# Pull models again
ollama pull nomic-embed-text
ollama pull llama3.2:3b

# List available models
ollama list

# Update .env with correct model name
```

---

## System-Specific Notes

### macOS

- Ollama runs as a background service automatically
- May need to allow Ollama in Security & Privacy settings
- Use `python3` instead of `python` if needed

### Linux

- May need to start Ollama manually: `systemctl start ollama`
- Check firewall settings if running on server

### Windows

- Use PowerShell or Command Prompt (not Git Bash for some commands)
- Path separators are `\` instead of `/`
- Activate venv with `venv\Scripts\activate`
- Ollama runs in system tray

---

## Next Steps

After successful installation:

1. **Read QUICKSTART.md** for usage examples
2. **Read IMPROVEMENTS.md** for feature details
3. **Test with sample queries** to verify functionality
4. **Customize .env settings** for your use case
5. **Build your document collection** by adding more PDFs

---

## Support Resources

- **Documentation:** README.md, QUICKSTART.md, IMPROVEMENTS.md
- **Testing:** See testing guide in COMPLETE_IMPLEMENTATION_SUMMARY.md
- **Logs:** Check `logs/rag_pipeline.log` for detailed error information
- **Ollama Docs:** [ollama.com/docs](https://ollama.com/docs)
- **ChromaDB Docs:** [docs.trychroma.com](https://docs.trychroma.com)

---

## Uninstallation

### Standard Installation

```bash
# Deactivate virtual environment
deactivate

# Remove project folder
cd ..
rm -rf medical-research-rag/

# Optionally remove Ollama
# macOS: Drag Ollama from Applications to Trash
# Linux: systemctl stop ollama && apt remove ollama
```


---

**Installation complete! Your Medical Research RAG system is ready to use.**

**Version:** 2.1.0
**Last Updated:** February 27, 2026
