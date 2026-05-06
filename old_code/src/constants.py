"""
Constants used throughout the Medical Research RAG Pipeline.
"""

# Collection Names
DEFAULT_COLLECTION_NAME = "medical-research-chunks"

# Model Names
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_LLM_MODEL = "deepseek-llm:7b-chat"

# Chunking
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_MIN_CHUNK_SIZE = 100

# Retrieval
DEFAULT_TOP_K_RESULTS = 5

# Generation
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 2048

# Ollama
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT = 120.0

# Embedding Dimensions
NOMIC_EMBED_DIMENSIONS = 768

# File Extensions
PDF_EXTENSION = ".pdf"
JSON_EXTENSION = ".json"
JSONL_EXTENSION = ".jsonl"
MARKDOWN_EXTENSION = ".md"

# Directory Names
PDF_FOLDER = "pdfs"
DATA_FOLDER = "data"
LOGS_FOLDER = "logs"
VECTOR_DB_FOLDER = "vector_db"

# Progress Files
INGESTION_PROGRESS_FILE = "ingestion_progress.json"
EMBEDDING_CACHE_FOLDER = "embedding_cache"

# Validation Limits
MAX_QUERY_LENGTH = 2000
MAX_TOP_K = 100
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0

# Batch Sizes
EMBEDDING_BATCH_SIZE = 10
DEFAULT_BATCH_SIZE = 100

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 2
RETRY_MAX_WAIT = 10
