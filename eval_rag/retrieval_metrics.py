from __future__ import annotations

from typing import Sequence

"""检索质量指标:context precision / recall,纯集合计算不调 LLM。

precision = 召回中命中 gold 的比例(召回的 chunk 有多少有用);
recall    = gold 中被召回覆盖的比例(必需信息是否都找到)。
按 doc_id 集合语义去重,同一 chunk 多次召回只算一次命中。

滑动窗口重叠索引下,同一条答案常被相邻两个窗口(近重复)同时承载。此时该答案的
gold 应视为「一组等价候选」,召回命中组内任一即算覆盖(any-hit),不能按逐 id 比例
把「两个近重复邻窗只命中一个」记成 0.5——那会把召回换精度的重叠优化误判成退化。
context_recall_grouped 即按分组 any-hit 口径计算。
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


def context_recall_grouped(
    retrieved_ids: Sequence[str], gold_groups: Sequence[Sequence[str]]
) -> float:
    """分组 any-hit 召回:每组代表一条必需信息的若干等价 gold 候选(重叠邻窗)。

    组内召回命中任一候选即算该组被覆盖。recall = 被覆盖组数 / 总组数。
    组数为 0(无必需信息)时返回 1.0,避免除零。空组不计入分母。
    """
    groups = [set(g) for g in gold_groups if g]
    if not groups:
        return 1.0
    retrieved = set(retrieved_ids)
    covered = sum(1 for g in groups if retrieved & g)
    return covered / len(groups)
