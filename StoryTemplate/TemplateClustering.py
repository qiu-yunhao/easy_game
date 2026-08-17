from __future__ import annotations

import math
from typing import Sequence

from embedding import EmbeddingModel

"""纯向量算法层：不调 LLM，只用注入的 embedding 做相似度聚类。

- dedup_beats：桥段片段两两余弦，≥ dedup_threshold 并查集归簇（去重）。
- merge_characters：同名或向量 ≥ merge_threshold 归并（避免同角色跨章割裂）。
bge 已归一化，余弦相似度 = 点积。
"""


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self) -> list[list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            groups.setdefault(self.find(i), []).append(i)
        return list(groups.values())


class TemplateClustering:
    def __init__(
        self,
        embedding: EmbeddingModel,
        *,
        dedup_threshold: float = 0.6,
        merge_threshold: float = 0.82,
    ) -> None:
        self._embedding = embedding
        self._dedup_threshold = dedup_threshold
        self._merge_threshold = merge_threshold

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embedding.encode(texts)

    def _cluster_by_vectors(self, vectors, threshold, extra_same=None) -> list[list[int]]:
        n = len(vectors)
        uf = _UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                same = _cosine(vectors[i], vectors[j]) >= threshold
                if extra_same is not None and extra_same(i, j):
                    same = True
                if same:
                    uf.union(i, j)
        return uf.clusters()

    def dedup_beats(self, beat_texts: list[str]) -> list[list[int]]:
        if not beat_texts:
            return []
        vectors = self.embed(beat_texts)
        return self._cluster_by_vectors(vectors, self._dedup_threshold)

    def merge_characters(self, names: list[str], vectors: list[list[float]]) -> list[list[int]]:
        if not names:
            return []
        return self._cluster_by_vectors(
            vectors, self._merge_threshold,
            extra_same=lambda i, j: names[i].strip() == names[j].strip() and bool(names[i].strip()),
        )
