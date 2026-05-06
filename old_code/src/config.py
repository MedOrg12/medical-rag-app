"""
Configuration management for the Medical RAG Pipeline.
Loads environment variables and provides typed configuration objects.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Ollama Configuration
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="deepseek-llm:7b-chat", env="OLLAMA_MODEL")
    ollama_embedding_model: str = Field(default="nomic-embed-text", env="OLLAMA_EMBEDDING_MODEL")

    # Vector Database Configuration
    vector_db_path: str = Field(default="./vector_db", env="VECTOR_DB_PATH")
    vector_db_type: Literal["chroma", "qdrant"] = Field(default="chroma", env="VECTOR_DB_TYPE")

    # Chunking Configuration
    chunk_size: int = Field(default=512, env="CHUNK_SIZE", ge=100, le=2048)
    chunk_overlap: int = Field(default=50, env="CHUNK_OVERLAP", ge=0)
    min_chunk_size: int = Field(default=100, env="MIN_CHUNK_SIZE", ge=50)

    # RAG Configuration
    top_k_results: int = Field(default=5, env="TOP_K_RESULTS", ge=1, le=20)
    temperature: float = Field(default=0.1, env="TEMPERATURE", ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, env="MAX_TOKENS", ge=256, le=8192)

    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="./logs/rag_pipeline.log", env="LOG_FILE")

    # Paths
    pdf_folder: Path = Field(default=Path("./pdfs"), env="PDF_FOLDER")
    data_folder: Path = Field(default=Path("./data"), env="DATA_FOLDER")

    # Enhanced PDF Parsing Limits
    max_figures_per_page: int = Field(default=20, env="MAX_FIGURES_PER_PAGE", ge=1, le=100)
    max_content_for_references: int = Field(
        default=100000, env="MAX_CONTENT_FOR_REFERENCES", ge=10000
    )
    max_references_to_extract: int = Field(
        default=200, env="MAX_REFERENCES_TO_EXTRACT", ge=1, le=1000
    )
    figure_caption_search_distance: int = Field(
        default=50, env="FIGURE_CAPTION_SEARCH_DISTANCE", ge=10, le=200
    )

    # Re-ranking Settings
    rerank_chunk_truncation: int = Field(
        default=500, env="RERANK_CHUNK_TRUNCATION", ge=100, le=2000
    )
    default_relevance_score: float = Field(
        default=0.5, env="DEFAULT_RELEVANCE_SCORE", ge=0.0, le=1.0
    )

    # Embedding Settings
    nomic_embed_dimensions: int = Field(default=768, env="NOMIC_EMBED_DIMENSIONS")
    connection_timeout: float = Field(default=5.0, env="CONNECTION_TIMEOUT", ge=1.0, le=60.0)

    # Metadata Extraction
    metadata_check_chars: int = Field(default=1000, env="METADATA_CHECK_CHARS", ge=100, le=10000)

    # LLM Timeouts (in seconds)
    llm_timeout_generation: float = Field(
        default=120.0, env="LLM_TIMEOUT_GENERATION", ge=10.0, le=600.0
    )
    llm_timeout_reranking: float = Field(
        default=60.0, env="LLM_TIMEOUT_RERANKING", ge=5.0, le=300.0
    )
    llm_timeout_expansion: float = Field(
        default=60.0, env="LLM_TIMEOUT_EXPANSION", ge=5.0, le=300.0
    )
    llm_timeout_classification: float = Field(
        default=30.0, env="LLM_TIMEOUT_CLASSIFICATION", ge=5.0, le=120.0
    )

    # API Configuration
    max_upload_file_size_mb: int = Field(default=50, env="MAX_UPLOAD_FILE_SIZE_MB", ge=1, le=500)
    allowed_file_extensions: list[str] = Field(
        default=[".pdf"], env="ALLOWED_FILE_EXTENSIONS"
    )
    api_request_timeout: float = Field(default=5.0, env="API_REQUEST_TIMEOUT", ge=1.0, le=60.0)
    max_query_length: int = Field(default=2000, env="MAX_QUERY_LENGTH", ge=100, le=10000)

    # Batch Processing Configuration
    embedding_batch_size: int = Field(default=10, env="EMBEDDING_BATCH_SIZE", ge=1, le=100)
    vector_db_batch_size: int = Field(default=100, env="VECTOR_DB_BATCH_SIZE", ge=10, le=1000)

    # Rate Limiting Configuration
    rate_limit_enabled: bool = Field(default=True, env="RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(default=60, env="RATE_LIMIT_PER_MINUTE", ge=1, le=1000)
    rate_limit_upload_per_hour: int = Field(default=20, env="RATE_LIMIT_UPLOAD_PER_HOUR", ge=1, le=100)

    @field_validator("chunk_overlap")
    @classmethod
    def validate_chunk_overlap(cls, v: int, info: ValidationInfo) -> int:
        """Ensure chunk overlap is less than chunk size."""
        chunk_size = info.data.get("chunk_size", 512)
        if v >= chunk_size:
            raise ValueError(f"Chunk overlap ({v}) must be less than chunk size ({chunk_size})")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance (for backward compatibility)
# New code should use get_settings() or dependency injection
settings = Settings()


def get_settings() -> Settings:
    """
    Get settings instance.

    For testing, you can create a new Settings() instance.
    For production, this returns the default global instance.
    """
    return settings
