from medical_rag.embeddings import HashingEmbeddingModel


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def test_hashing_embedding_scores_related_text_higher() -> None:
    model = HashingEmbeddingModel(dimensions=128)
    query, related, unrelated = model.embed(
        [
            "stroke symptoms face arm speech time",
            "face drooping arm weakness and speech difficulty are stroke symptoms",
            "weather patterns and crop yields",
        ]
    )

    assert _dot(query, related) > _dot(query, unrelated)
