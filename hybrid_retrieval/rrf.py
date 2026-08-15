from __future__ import annotations

from typing import Sequence

"""Reciprocal Rank Fusion：把多路排名合并为一个统一排名。

每个文档在某一路的贡献为 1/(k+rank)，k 越大越平滑（默认 60，业界常用）。
只依赖排名不依赖各路原始分，天然消除稠密/稀疏两路分数量纲不一致的问题。
"""


def rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
