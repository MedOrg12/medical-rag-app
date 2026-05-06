#!/bin/bash
# Setup script for Medical Research RAG Pipeline

set -e

echo "=========================================="
echo "Medical Research RAG - Setup Script"
echo "=========================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi

# Check Ollama installation
echo ""
echo "Checking Ollama installation..."
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed."
    echo ""
    echo "Please install Ollama:"
    echo "  macOS: brew install ollama"
    echo "  Linux: curl -fsSL https://ollama.ai/install.sh | sh"
    echo "  Windows: Download from https://ollama.ai"
    exit 1
fi

echo "✓ Ollama is installed: $(ollama --version)"

# Check if Ollama is running
echo ""
echo "Checking if Ollama server is running..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "❌ Ollama server is not running."
    echo ""
    echo "Please start Ollama in a separate terminal:"
    echo "  ollama serve"
    echo ""
    echo "Then run this setup script again."
    exit 1
fi

echo "✓ Ollama server is running"

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
if [ -d "venv" ]; then
    echo "✓ Virtual environment already exists"
else
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✓ Dependencies installed"

# Pull required Ollama models
echo ""
echo "Pulling required Ollama models..."

# Check if nomic-embed-text exists
if ollama list | grep -q "nomic-embed-text"; then
    echo "✓ nomic-embed-text already installed"
else
    echo "Pulling nomic-embed-text (embedding model)..."
    ollama pull nomic-embed-text
fi

# Check if deepseek-r1:7b exists
if ollama list | grep -q "deepseek-r1:7b"; then
    echo "✓ deepseek-r1:7b already installed"
else
    echo ""
    echo "Note: deepseek-r1:7b model is configured but not installed."
    echo "You can either:"
    echo "  1. Pull it now: ollama pull deepseek-r1:7b (recommended if you have it)"
    echo "  2. Use an alternative model by editing .env"
    echo ""
    read -p "Do you want to check for alternative models? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Available models on your system:"
        ollama list
        echo ""
        echo "You can use any of these models by updating OLLAMA_MODEL in .env"
    fi
fi

# Create directories
echo ""
echo "Creating project directories..."
mkdir -p pdfs vector_db data logs

echo "✓ Directories created"

# Summary
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Activate the virtual environment (if not already active):"
echo "   source venv/bin/activate"
echo ""
echo "2. Add your PDF files to the ./pdfs folder:"
echo "   cp /path/to/your/papers/*.pdf ./pdfs/"
echo ""
echo "3. Run the ingestion pipeline:"
echo "   python ingest.py"
echo ""
echo "4. Query your documents:"
echo "   python query.py --interactive"
echo ""
echo "For more information, see README.md"
echo "=========================================="
