import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.llm import ApiGenerator, ExtractiveGenerator, FallbackGenerator
from medical_rag.server import create_app
from medical_rag.types import Chunk, SearchResult


def result():
    return SearchResult(chunk=Chunk(id="one", text="Stroke rehabilitation evidence", metadata={}), score=1, rank=1)


def test_provider_yields_chunks_before_reading_completion():
    response = io.BytesIO(
        b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    generator = ApiGenerator("https://example.test/v1", "secret", "model")
    with patch("urllib.request.urlopen", return_value=response) as send:
        chunks = generator.stream("question", [result()])
        assert next(chunks) == "Hello "
        assert not response.closed
        assert list(chunks) == ["world"]
        payload = json.loads(send.call_args.args[0].data)
        assert payload["stream"] is True


def test_partial_stream_is_not_completed_with_fallback():
    primary = ApiGenerator("https://example.test/v1", "secret", "model")
    response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n')
    with patch("urllib.request.urlopen", return_value=response):
        stream = FallbackGenerator(primary, ExtractiveGenerator()).stream("question", [result()])
        assert next(stream) == "Partial"
        with pytest.raises(RuntimeError, match="interrupted"):
            next(stream)


def test_failure_before_first_token_returns_excerpts():
    primary = ApiGenerator("https://example.test/v1", "secret", "model")
    with patch("urllib.request.urlopen", side_effect=TimeoutError()):
        text = "".join(FallbackGenerator(primary, ExtractiveGenerator()).stream("question", [result()]))
        assert "Stroke rehabilitation evidence" in text
        assert "excerpts" in text


def test_token_limit_is_reported_as_incomplete():
    generator = ApiGenerator("https://example.test/v1", "secret", "model")
    response = io.BytesIO(
        b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
        b'data: [DONE]\n\n'
    )
    with patch("urllib.request.urlopen", return_value=response):
        stream = generator.stream("question", [result()])
        assert next(stream) == "Partial"
        with pytest.raises(RuntimeError, match="did not finish"):
            list(stream)


def test_stream_endpoint_returns_delta_then_final_payload(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash")
    client = TestClient(create_app(settings))
    class Answer:
        def to_dict(self):
            return {"answer": "Hello", "citations": []}
    events = [{"type": "delta", "text": "Hello"}, {"type": "done", "answer": Answer()}]
    with patch("medical_rag.pipeline.StrokeRAG.ask_stream", return_value=iter(events)):
        response = client.post("/ask/stream", json={"question": "test"})
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert rows[0] == {"type": "delta", "text": "Hello"}
    assert rows[1]["payload"]["answer"] == "Hello"
    assert response.headers["content-type"].startswith("application/x-ndjson")


def test_stream_endpoint_reports_errors_without_done(tmp_path):
    client = TestClient(create_app(Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash")))
    with patch("medical_rag.pipeline.StrokeRAG.ask_stream", side_effect=ValueError("bad index")):
        response = client.post("/ask/stream", json={"question": "test"})
    assert [json.loads(line)["type"] for line in response.text.splitlines()] == ["error"]
