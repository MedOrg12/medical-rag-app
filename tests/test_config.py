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
    monkeypatch.setenv("RAG_ANSWER_MODE", "clinician")

    settings = Settings.from_env(tmp_path)

    assert str(settings.corpus_dir) == "/app/pdfs"
    assert str(settings.index_path) == "/app/vector_db/index.json"
    assert settings.chunk_size_chars == 900
    assert settings.chunk_overlap_chars == 120
    assert settings.top_k == 8
    assert settings.ollama_base_url == "http://ollama:11434"
    assert settings.ollama_generation_model == "llama3.1"
    assert settings.ollama_embedding_model == "nomic-embed-text"
    assert settings.answer_mode == "clinician"
