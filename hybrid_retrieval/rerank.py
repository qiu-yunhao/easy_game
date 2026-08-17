from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from datatypes import ScoredDoc

"""三因子可配置重排：relevance（RRF 分）/ recency（时间新近）/ importance（重要度）。

权重由调用方传入，默认给一套均衡策略，业务可覆盖。三个因子量纲不一致
（relevance 是 RRF 分 ~0.016、recency 是原始 turn、importance 是 0-5 评分），
若直接加权相加会让量纲大的因子淹没语义相关性。故先在候选集内对每个因子做
min-max 归一化到 0-1 再加权。重排只重算总分并排序，分项因子（归一化前的原值）
保留在 ScoredDoc.factors 里，便于调试与透明化。
"""


@dataclass(slots=True)
class RerankWeights:
    relevance: float = 0.6
    recency: float = 0.2
    importance: float = 0.2


def _minmax(values: Sequence[float]) -> list[float]:
    """候选集内 min-max 归一化到 [0,1]；max==min（含单候选）时统一给 1.0。

    退化处理：某因子在候选集里全相等时无法区分优劣，归一化为常数 1.0，
    让该因子对排序不产生倾向（各候选该项贡献相同），而非除零。
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        return [1.0] * len(values)
    return [(v - lo) / span for v in values]


def rerank(docs: Sequence[ScoredDoc], *, weights: RerankWeights | None = None) -> list[ScoredDoc]:
    w = weights or RerankWeights()
    items = list(docs)
    if not items:
        return []
    # 先各因子在候选集内归一化，消除量纲差异，再加权求总分。
    norm_rel = _minmax([d.factors.get("relevance", 0.0) for d in items])
    norm_rec = _minmax([d.factors.get("recency", 0.0) for d in items])
    norm_imp = _minmax([d.factors.get("importance", 0.0) for d in items])
    rescored: list[ScoredDoc] = []
    for d, r, rec, imp in zip(items, norm_rel, norm_rec, norm_imp):
        total = w.relevance * r + w.recency * rec + w.importance * imp
        rescored.append(ScoredDoc(doc=d.doc, score=total, factors=dict(d.factors)))
    return sorted(rescored, key=lambda d: d.score, reverse=True)
