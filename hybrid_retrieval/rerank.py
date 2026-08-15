from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from datatypes import ScoredDoc

"""三因子可配置重排：relevance（RRF 分）/ recency（时间新近）/ importance（重要度）。

权重由调用方传入，默认给一套均衡策略，业务可覆盖。重排只重算总分并排序，
分项因子保留在 ScoredDoc.factors 里，便于调试与透明化。
"""


@dataclass(slots=True)
class RerankWeights:
    relevance: float = 0.6
    recency: float = 0.2
    importance: float = 0.2


def rerank(docs: Sequence[ScoredDoc], *, weights: RerankWeights | None = None) -> list[ScoredDoc]:
    w = weights or RerankWeights()
    rescored: list[ScoredDoc] = []
    for d in docs:
        f = d.factors
        total = (
            w.relevance * f.get("relevance", 0.0)
            + w.recency * f.get("recency", 0.0)
            + w.importance * f.get("importance", 0.0)
        )
        rescored.append(ScoredDoc(doc=d.doc, score=total, factors=dict(f)))
    return sorted(rescored, key=lambda d: d.score, reverse=True)
