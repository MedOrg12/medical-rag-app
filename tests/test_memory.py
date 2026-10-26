from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.memory import ConversationStore, prompt_history
from medical_rag.server import create_app


def test_memory_survives_restart_is_isolated_and_clearable(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = ConversationStore(path)
    store.append("alice", {"question": "My name is Alice", "answer": "Hello Alice"})
    restarted = ConversationStore(path)
    assert restarted.history("alice")[0]["question"] == "My name is Alice"
    assert restarted.history("bob") == []
    restarted.clear("alice")
    assert store.history("alice") == []


def test_context_keeps_opening_and_recent_turns_within_budget():
    turns = [{"question": f"question {i}", "answer": "a" * 3000} for i in range(100)]
    history = prompt_history(turns)
    assert history[0]["content"] == "question 0"
    assert history[-2]["content"] == "question 99"
    assert sum(len(m["content"]) for m in history) <= 24000


def test_api_passes_saved_history_and_restores_after_restart(tmp_path, monkeypatch):
    seen = []

    class FakeAnswer:
        def __init__(self, question):
            self.question = question

        def to_dict(self):
            return {"question": self.question, "answer": "Remembered", "citations": []}

    def fake_ask(self, **kwargs):
        seen.append(kwargs)
        return FakeAnswer(kwargs["question"])

    monkeypatch.setattr("medical_rag.server.StrokeRAG.ask", fake_ask)
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / ".rag/index.json", embedding_backend="hash")
    client = TestClient(create_app(settings))
    assert client.post("/ask", json={"question": "My name is Alice", "conversation_id": "alice"}).status_code == 200
    restarted = TestClient(create_app(settings))
    assert restarted.get("/conversations/alice").json()["turns"][0]["question"] == "My name is Alice"
    restarted.post("/ask", json={"question": "What is my name?", "conversation_id": "alice"})
    assert seen[-1]["history"][0] == {"role": "user", "content": "My name is Alice"}
    restarted.post("/ask", json={"question": "Hello", "conversation_id": "bob"})
    assert seen[-1]["history"] == []
    assert restarted.delete("/conversations/alice").status_code == 200
    restarted.post("/ask", json={"question": "Hello", "conversation_id": "alice"})
    assert seen[-1]["history"] == []


def test_generator_sends_history_before_current_evidence(monkeypatch):
    import json

    from medical_rag.llm import ApiGenerator
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"choices":[{"message":{"content":"Alice"}}]}'

    def urlopen(request, **kwargs):
        seen.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr("medical_rag.llm.urllib.request.urlopen", urlopen)
    generator = ApiGenerator(base_url="https://example.test", api_key="test", model="test")
    history = [{"role": "user", "content": "My name is Alice"},
               {"role": "assistant", "content": "Hello Alice"}]
    assert generator.generate("What is my name?", [], history=history) == "Alice"
    assert seen[0]["messages"][1:3] == history
    assert "What is my name?" in seen[0]["messages"][-1]["content"]


def test_follow_up_retrieves_prior_topic_and_preserves_current_question(tmp_path):
    from medical_rag.llm import ExtractiveGenerator
    from medical_rag.pipeline import StrokeRAG

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "diet.txt").write_text(
        "After stroke, eat fruits and vegetables and reduce salt and saturated fat."
    )
    settings = Settings(root_dir=tmp_path, corpus_dir=corpus,
                        index_path=tmp_path / ".rag/index.json", embedding_backend="hash")
    rag = StrokeRAG(settings, generator=ExtractiveGenerator())
    rag.ingest()
    answer = rag.ask("Can you explain that?", history=[
        {"role": "user", "content": "What should I eat after stroke?"},
        {"role": "assistant", "content": "Consider fruits and vegetables."},
    ])
    assert answer.question == "Can you explain that?"
    assert answer.citations[0].source == "diet.txt"
