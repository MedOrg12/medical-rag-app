from __future__ import annotations

import math
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from medical_rag.types import Chunk

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*|\d+(?:\.\d+)?")


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


class BM25Index:
    """Okapi BM25 index backed by stdlib only (math + collections)."""

    k1: float = 1.5
    b: float = 0.75

    def __init__(self) -> None:
        self._chunk_ids: list[str] = []
        self._tf: list[Counter[str, int]] = []
        self._df: Counter[str, int] = Counter()
        self._avgdl: float = 0.0
        self._n: int = 0

    @classmethod
    def build(cls, chunks: list[Chunk]) -> "BM25Index":
        idx = cls()
        total_tokens = 0
        for chunk in chunks:
            tokens = _tokenize(chunk.text)
            tf: Counter[str, int] = Counter(tokens)
            idx._chunk_ids.append(chunk.id)
            idx._tf.append(tf)
            for term in tf:
                idx._df[term] += 1
            total_tokens += len(tokens)
        idx._n = len(chunks)
        idx._avgdl = total_tokens / idx._n if idx._n else 0.0
        return idx

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._n == 0:
            return []
        q_terms = _tokenize(query)
        scores: list[tuple[str, float]] = []
        for i, (chunk_id, tf) in enumerate(zip(self._chunk_ids, self._tf)):
            dl = sum(tf.values())
            score = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                df = self._df.get(term, 0)
                idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1)
                tf_val = tf[term]
                tf_norm = tf_val * (self.k1 + 1) / (
                    tf_val + self.k1 * (1 - self.b + self.b * dl / max(self._avgdl, 1))
                )
                score += idf * tf_norm
            if score > 0:
                scores.append((chunk_id, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def to_dict(self) -> dict:
        return {
            "chunk_ids": self._chunk_ids,
            "tf": [dict(c) for c in self._tf],
            "df": dict(self._df),
            "avgdl": self._avgdl,
            "n": self._n,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BM25Index":
        idx = cls()
        idx._chunk_ids = data["chunk_ids"]
        idx._tf = [Counter(c) for c in data["tf"]]
        idx._df = Counter(data["df"])
        idx._avgdl = float(data["avgdl"])
        idx._n = int(data["n"])
        return idx
