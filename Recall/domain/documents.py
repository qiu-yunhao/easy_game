from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocType = Literal["scene_summary", "act_chunk"]


@dataclass(frozen=True)
class RecallDoc:
    """一条可检索的回忆文档，已准备好用于向量化与入库。

    这是回忆子系统内部流转的统一数据模型：索引层产出它，向量化层读取它的
    ``text`` 生成 embedding，存储层把它写入 Redis，检索层再把它取回并重排。

    字段说明：
        doc_id: 稳定且可复现的唯一 id，便于幂等 upsert（重复索引同一场景不会产生重复文档）。
        doc_type: 文档粒度，``scene_summary``（整幕摘要）或 ``act_chunk``（若干行动合成的片段）。
        user_id / player_id: 多租户隔离键，检索时用于过滤，保证只召回当前玩家的记忆。
        scene_id / chapter_id: 归属的场景与章节，用于粗召回定位后再细召回。
        turn_start / turn_end: 文档覆盖的回合区间，供检索层按时间新近度（recency）打分。
        importance: 复用历史记录已有的重要度分数，供检索层重排时作为权重之一。
        text: 文档正文，同时供稠密（embedding）与稀疏（关键词）两条检索轨使用。
    """

    doc_id: str
    doc_type: DocType
    user_id: int
    player_id: int
    scene_id: str
    chapter_id: str
    turn_start: int
    turn_end: int
    importance: float
    text: str
