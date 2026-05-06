from medical_rag.embeddings import HashingEmbeddingModel
from medical_rag.types import Chunk
from medical_rag.vector_store import VectorStore


def test_vector_store_round_trips_and_searches(tmp_path) -> None:
    chunks = [
        Chunk(
            id="stroke",
            text="FAST stroke symptoms include face drooping, arm weakness, and speech difficulty.",
            metadata={"source_id": "stroke.txt", "page": 1, "title": "Stroke"},
        ),
        Chunk(
            id="unrelated",
            text="Hypertension is a chronic cardiovascular risk factor.",
            metadata={"source_id": "risk.txt", "page": 1, "title": "Risk"},
        ),
    ]
    model = HashingEmbeddingModel(dimensions=128)
    path = tmp_path / "index.json"

    store = VectorStore.build(path=path, chunks=chunks, embedding_model=model)
    store.save()
    loaded = VectorStore.load(path)
    results = loaded.search("stroke face arm speech symptoms", model, top_k=1)

    assert results[0].chunk.id == "stroke"
    assert loaded.source_summaries()[0]["chunks"] == 1
