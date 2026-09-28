from medical_rag.config import Settings


def test_settings_accept_legacy_docker_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PDF_FOLDER", "/app/pdfs")
    monkeypatch.setenv("VECTOR_DB_PATH", "/app/vector_db")
    monkeypatch.setenv("CHUNK_SIZE", "900")
    monkeypatch.setenv("CHUNK_OVERLAP", "120")
    monkeypatch.setenv("TOP_K", "8")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("RAG_API_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("RAG_API_KEY", "test-key")
    monkeypatch.setenv("RAG_API_GENERATION_MODEL", "api-chat")
    monkeypatch.setenv("RAG_API_EMBEDDING_MODEL", "api-embed")
    monkeypatch.setenv("RAG_API_MAX_OUTPUT_TOKENS", "500")
    monkeypatch.setenv("RAG_API_REASONING_EFFORT", "LOW")
    monkeypatch.setenv("RAG_API_MAX_RETRIES", "4")
    monkeypatch.setenv("RAG_ANSWER_MODE", "clinician")
    monkeypatch.setenv("RAG_REQUEST_TIMEOUT_SECONDS", "75")

    settings = Settings.from_env(tmp_path)

    assert settings.corpus_dir.as_posix().endswith("/app/pdfs")
    assert settings.index_path.as_posix().endswith("/app/vector_db/index.json")
    assert settings.chunk_size_chars == 900
    assert settings.chunk_overlap_chars == 120
    assert settings.top_k == 8
    assert settings.ollama_base_url == "http://ollama:11434"
    assert settings.ollama_generation_model == "llama3.1"
    assert settings.ollama_embedding_model == "nomic-embed-text"
    assert settings.api_base_url == "https://api.example.test/v1"
    assert settings.api_key == "test-key"
    assert settings.api_generation_model == "api-chat"
    assert settings.api_embedding_model == "api-embed"
    assert settings.api_max_output_tokens == 500
    assert settings.api_reasoning_effort == "low"
    assert settings.api_max_retries == 4
    assert settings.answer_mode == "clinician"
    assert settings.request_timeout_seconds == 75


def test_with_ingestion_options_preserves_answer_mode(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path,
        index_path=tmp_path / "index.json",
        answer_mode="clinician",
        api_max_output_tokens=600,
        api_reasoning_effort="low",
        api_max_retries=3,
    )

    updated = settings.with_ingestion_options(pdf_workers=4)

    assert updated.pdf_workers == 4
    assert updated.answer_mode == "clinician"
    assert updated.api_max_output_tokens == 600
    assert updated.api_reasoning_effort == "low"
    assert updated.api_max_retries == 3
