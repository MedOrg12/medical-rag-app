from __future__ import annotations

import math
import re
from collections import Counter
from heapq import nlargest
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
        self._lengths: list[int] = []
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
            idx._lengths.append(len(tokens))
            for term in tf:
                idx._df[term] += 1
            total_tokens += len(tokens)
        idx._n = len(chunks)
        idx._avgdl = total_tokens / idx._n if idx._n else 0.0
        return idx

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._n == 0:
            return []
        terms = [
            (term, math.log((self._n - self._df[term] + 0.5) / (self._df[term] + 0.5) + 1))
            for term in _tokenize(query)
            if self._df.get(term, 0)
        ]
        if not terms:
            return []

        def scored_documents():
            for chunk_id, tf, dl in zip(self._chunk_ids, self._tf, self._lengths, strict=False):
                score = 0.0
                normalization = self.k1 * (1 - self.b + self.b * dl / max(self._avgdl, 1))
                for term, idf in terms:
                    tf_val = tf.get(term, 0)
                    if tf_val:
                        score += idf * (tf_val * (self.k1 + 1) / (tf_val + normalization))
                if score > 0:
                    yield chunk_id, score

        return nlargest(top_k, scored_documents(), key=lambda item: item[1])

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
        idx._lengths = [sum(tf.values()) for tf in idx._tf]
        idx._df = Counter(data["df"])
        idx._avgdl = float(data["avgdl"])
        idx._n = int(data["n"])
        return idx
