from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.server import create_app


def client_for(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>MedicalRAG</html>")
    return TestClient(create_app(Settings(
        root_dir=tmp_path, corpus_dir=tmp_path, index_path=tmp_path / "index.json",
        embedding_backend="hash",
    )))


def test_interface_revalidates_and_downloads_changes(tmp_path):
    client = client_for(tmp_path)
    response = client.get("/")
    assert response.headers["cache-control"] == "private, no-cache"
    cached = client.get("/", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""
    (tmp_path / "static/index.html").write_text("<html>Updated MedicalRAG interface</html>")
    updated = client.get("/", headers={"If-None-Match": response.headers["etag"]})
    assert updated.status_code == 200
    assert "Updated" in updated.text


def test_sources_revalidate_after_corpus_changes(tmp_path, monkeypatch):
    sources = [{"source": "first.pdf"}]
    monkeypatch.setattr("medical_rag.server.StrokeRAG.sources", lambda self: sources)
    client = client_for(tmp_path)
    response = client.get("/sources")
    etag = response.headers["etag"]
    assert response.headers["cache-control"] == "private, no-cache"
    assert client.get("/sources", headers={"If-None-Match": "W/" + etag}).status_code == 304
    sources.append({"source": "second.pdf"})
    updated = client.get("/sources", headers={"If-None-Match": etag})
    assert updated.status_code == 200
    assert len(updated.json()) == 2


def test_only_read_only_reference_data_is_cached(tmp_path):
    client = client_for(tmp_path)
    response = client.get("/eval/questions")
    assert response.headers["cache-control"] == "private, max-age=300, must-revalidate"
    assert client.get("/eval/questions", headers={"If-None-Match": response.headers["etag"]}).status_code == 304
    assert client.get("/conversations/test").headers["cache-control"] == "no-store"
    assert client.post("/ask", json={}).headers["cache-control"] == "no-store"
    assert client.get("/static/index.html").headers["cache-control"] == "private, no-cache"
