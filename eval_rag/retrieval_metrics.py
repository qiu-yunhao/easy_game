from __future__ import annotations

from typing import Sequence

"""检索质量指标:context precision / recall,纯集合计算不调 LLM。

precision = 召回中命中 gold 的比例(召回的 chunk 有多少有用);
recall    = gold 中被召回覆盖的比例(必需信息是否都找到)。
按 doc_id 集合语义去重,同一 chunk 多次召回只算一次命中。
"""


def context_precision(retrieved_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
    retrieved = set(retrieved_ids)
    if not retrieved:
        return 0.0
    return len(retrieved & set(gold_ids)) / len(retrieved)


def context_recall(retrieved_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
    gold = set(gold_ids)
    if not gold:
        return 1.0  # 无必需信息 → 视为满召回,避免除零
    return len(set(retrieved_ids) & gold) / len(gold)
