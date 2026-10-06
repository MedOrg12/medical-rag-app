import io
import json
import urllib.error

from medical_rag.config import Settings
from medical_rag.llm import ApiGenerator, ExtractiveGenerator, FallbackGenerator, Generator, make_generator
from medical_rag.types import Chunk, SearchResult


class BrokenGenerator(Generator):
    model_name = "broken"

    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        raise RuntimeError("Could not generate with Ollama at http://localhost:11434")


def test_fallback_generator_includes_backend_error() -> None:
    generator = FallbackGenerator(primary=BrokenGenerator(), fallback=ExtractiveGenerator())

    answer = generator.generate("What should I eat after stroke?", [])

    assert "Generation backend was unavailable" in answer
    assert "Could not generate with Ollama" in answer


def test_extractive_diet_answer_has_patient_and_clinician_modes() -> None:
    result = SearchResult(
        chunk=Chunk(
            id="diet",
            text=(
                "Dysphagia is common after stroke. Tube feeds via nasogastric route are "
                "reasonable for the first 2 to 3 weeks after stroke. Fruits and vegetables "
                "and lower salt and saturated fat intake can support secondary prevention."
            ),
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ExtractiveGenerator()

    patient_answer = generator.generate(
        "What should I eat after a stroke?", [result], answer_mode="patient"
    )
    clinician_answer = generator.generate(
        "What should I eat after a stroke?", [result], answer_mode="clinician"
    )

    assert "Dysphagia means difficulty swallowing" in patient_answer
    assert "aspiration risk" in clinician_answer
    assert patient_answer != clinician_answer


def test_api_generator_posts_openai_compatible_chat_request(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"Dysphagia means trouble swallowing [1]."}}]}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("medical_rag.llm.urllib.request.urlopen", fake_urlopen)
    result = SearchResult(
        chunk=Chunk(
            id="dysphagia",
            text="Dysphagia after stroke can involve difficulty swallowing.",
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ApiGenerator(
        base_url="https://api.example.test/v1",
        api_key="secret",
        model="chat-model",
        timeout_seconds=9,
    )

    answer = generator.generate("What is dysphagia?", [result], answer_mode="patient")

    assert answer == "Dysphagia means trouble swallowing [1]."
    assert generator.model_name == "api:chat-model"
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["timeout"] == 9
    assert seen["auth"] == "Bearer secret"
    assert '"model": "chat-model"' in seen["body"]
    assert "Dysphagia after stroke" in seen["body"]


def test_api_generator_adds_gemini_latency_controls(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"Trouble swallowing after stroke [1]."}}]}'

    def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("medical_rag.llm.urllib.request.urlopen", fake_urlopen)
    result = SearchResult(
        chunk=Chunk(
            id="dysphagia",
            text="Dysphagia after stroke can involve difficulty swallowing.",
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ApiGenerator(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="secret",
        model="gemini-3.8-flash",
        max_output_tokens=450,
    )

    generator.generate("What is dysphagia?", [result])

    assert seen["body"]["max_tokens"] == 450
    assert seen["body"]["reasoning_effort"] == "low"


def test_api_generator_retries_transient_http_errors(monkeypatch) -> None:
    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"Recovered [1]."}}]}'

    def fake_urlopen(_request, timeout=None):  # noqa: ANN001, ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://api.example.test/v1/chat/completions",
                code=503,
                msg="Service Unavailable",
                hdrs={},
                fp=io.BytesIO(b'{"error":{"message":"overloaded"}}'),
            )
        return FakeResponse()

    monkeypatch.setattr("medical_rag.llm.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("medical_rag.llm.time.sleep", lambda _seconds: None)
    result = SearchResult(
        chunk=Chunk(
            id="dysphagia",
            text="Dysphagia after stroke can involve difficulty swallowing.",
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ApiGenerator(
        base_url="https://api.example.test/v1",
        api_key="secret",
        model="chat-model",
        max_retries=1,
    )

    assert generator.generate("What is dysphagia?", [result]) == "Recovered [1]."
    assert calls["count"] == 2


def test_api_generator_network_error_includes_reason(monkeypatch) -> None:
    def fake_urlopen(_request, timeout=None):  # noqa: ANN001, ARG001
        raise urllib.error.URLError("temporary DNS failure")

    monkeypatch.setattr("medical_rag.llm.urllib.request.urlopen", fake_urlopen)
    result = SearchResult(
        chunk=Chunk(
            id="dysphagia",
            text="Dysphagia after stroke can involve difficulty swallowing.",
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ApiGenerator(
        base_url="https://api.example.test/v1",
        api_key="secret",
        model="chat-model",
    )

    try:
        generator.generate("What is dysphagia?", [result])
    except RuntimeError as exc:
        assert "temporary DNS failure" in str(exc)
    else:
        raise AssertionError("Expected API generation network error")


def test_api_generation_requires_api_key(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path,
        index_path=tmp_path / "index.json",
        generation_backend="api",
        api_key="",
    )

    try:
        make_generator(settings)
    except ValueError as exc:
        assert "RAG_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected API generation without an API key to fail")
