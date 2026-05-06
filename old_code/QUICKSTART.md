# Quick Start Guide

Get your Medical Research RAG pipeline running in 5 minutes.

## Prerequisites Check

Before starting, ensure you have:
- ✅ Python 3.10 or higher
- ✅ Ollama installed and running
- ✅ At least 8GB of free disk space
- ✅ Medical research PDFs to process

## Step-by-Step Setup

### 1. Install Ollama (if not already installed)

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download from https://ollama.ai

### 2. Start Ollama Server

Open a terminal and run:
```bash
ollama serve
```

Keep this terminal open. Ollama must run in the background.

### 3. Run Setup Script

In a **new terminal**, navigate to the project and run:

```bash
cd "healthcare project"
./setup.sh
```

This script will:
- ✅ Check Python installation
- ✅ Verify Ollama is running
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Pull required models (nomic-embed-text)
- ✅ Create necessary directories

**Manual setup (if you prefer):**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Pull models
ollama pull nomic-embed-text
ollama pull deepseek-r1:7b  # or your preferred model
```

### 4. Add Your PDFs

Copy medical research papers to the `pdf` folder:

```bash
cp /path/to/your/papers/*.pdf ./pdf/
```

**Example:**
```bash
# If your PDFs are in Downloads
cp ~/Downloads/medical_papers/*.pdf ./pdf/

# Or move individual files
cp ~/Downloads/diabetes_study.pdf ./pdf/
cp ~/Downloads/cancer_research.pdf ./pdf/
```

Verify PDFs are in place:
```bash
ls -lh pdf/
```

### 5. Ingest Documents

Process and index your PDFs:

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Run ingestion
python ingest.py
```

You'll see progress output:
```
Parsing PDFs from ./pdf folder
Found 5 PDF files
  - diabetes_study.pdf
  - cancer_research.pdf
  ...

Successfully parsed 5 documents
Created 234 chunks from 5 documents
Adding chunks to vector database...

Ingestion Pipeline Complete!
```

This takes 1-5 minutes depending on PDF count and size.

### 6. Start Querying!

**Interactive mode (recommended for first use):**

```bash
python query.py --interactive
```

Try asking:
```
Your question: What are the main findings?
Your question: Describe the study methodology
Your question: What are the limitations of the research?
```

**Single query:**

```bash
python query.py "What is the sample size and demographics?"
```

**Batch queries:**

```bash
# Uses the included queries.txt file
python query.py --batch queries.txt
```

## Example Session

```bash
$ python query.py --interactive

================================================================================
Medical Research RAG Assistant - Interactive Session
================================================================================
Model: deepseek-r1:7b
Database: medical_research (234 chunks)

Type 'quit' or 'exit' to end the session.
Type 'stats' to see database statistics.
================================================================================

Your question: What were the primary outcomes?

--------------------------------------------------------------------------------
Retrieving context and generating answer...
--------------------------------------------------------------------------------

ANSWER:
The primary outcome measure was the change in HbA1c levels from baseline to
12 weeks. Secondary outcomes included fasting plasma glucose, body weight
changes, and incidence of hypoglycemic events. The study found a statistically
significant reduction in HbA1c of -1.2% (95% CI: -1.4 to -1.0, p<0.001) in
the intervention group compared to control.

[Source: diabetes_rct_2024.pdf, Page: 8]
[Source: diabetes_rct_2024.pdf, Page: 12]

SOURCES:
1. diabetes_rct_2024.pdf - Results (Page(s): 8, 12, Similarity: 0.891)
2. diabetes_rct_2024.pdf - Methods (Page(s): 5, Similarity: 0.856)
3. diabetes_protocol.pdf - Outcomes (Page(s): 15, Similarity: 0.834)

--------------------------------------------------------------------------------

Your question: quit

Goodbye!
```

## Troubleshooting Quick Fixes

### "Cannot connect to Ollama"
```bash
# In a separate terminal, start Ollama:
ollama serve
```

### "Embedding model not found"
```bash
ollama pull nomic-embed-text
```

### "Vector database is empty"
```bash
# You need to run ingestion first:
python ingest.py
```

### "No PDF files found"
```bash
# Check the pdf folder:
ls pdf/

# If empty, add PDFs:
cp /path/to/papers/*.pdf ./pdf/
```

### PDF parsing fails
- Ensure PDFs are not password-protected
- Check if PDFs are corrupted (try opening them manually)
- The system will skip failed PDFs and process the rest

## What's Next?

### Create a Custom Medical Model

```bash
# Build specialized medical assistant
ollama create medical-assistant -f Modelfile

# Use it for queries
python query.py --model medical-assistant --interactive
```

### Generate Fine-Tuning Dataset

```bash
# Create training data from your PDFs
python ingest.py --generate-finetune

# Follow instructions in data/FINETUNING_INSTRUCTIONS.md
```

### Adjust Configuration

Edit [.env](.env) to customize:
- `CHUNK_SIZE`: Larger (1024) for more context, smaller (512) for precision
- `TOP_K_RESULTS`: More chunks (10) for comprehensive answers
- `TEMPERATURE`: Lower (0.1) for factual, higher (0.7) for creative
- `OLLAMA_MODEL`: Switch to different models

### Use Different Models

```bash
# List available models
ollama list

# Pull a different model
ollama pull llama3.2

# Use it
python query.py --model llama3.2 --interactive
```

### Advanced Usage

```bash
# Get verbose output with context chunks
python query.py --verbose "What is the methodology?"

# Retrieve more context
python query.py --top-k 10 "Summarize all findings"

# Save batch results to JSON
python query.py --batch queries.txt --output results.json
```

## Performance Tips

**For faster queries:**
- Use smaller models: `gemma3:4b` or `llama3.2`
- Reduce `TOP_K_RESULTS` to 3
- Use smaller `CHUNK_SIZE` (256-512)

**For better quality:**
- Use larger models: `deepseek-r1:7b` or larger
- Increase `TOP_K_RESULTS` to 7-10
- Use larger `CHUNK_SIZE` (1024)
- Set `TEMPERATURE` to 0.1 for factual answers

## Getting Help

1. **Check logs:** `cat logs/rag_pipeline.log`
2. **Read README:** Full documentation in [README.md](README.md)
3. **Database stats:** Run `python query.py --interactive` then type `stats`

## Summary Commands

```bash
# Setup (one time)
./setup.sh

# Add PDFs
cp /path/to/papers/*.pdf ./pdf/

# Ingest
python ingest.py

# Query - Interactive
python query.py --interactive

# Query - Single
python query.py "Your question here"

# Query - Batch
python query.py --batch queries.txt
```

---

**You're all set! Happy researching! 🔬📚**
