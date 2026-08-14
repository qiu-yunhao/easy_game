from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from CharacterMemory import (
    ConsolidatedMemoryBlock,
    LongTermMemoryEvent,
)
from CharacterProfile import CharacterProfile
from History.GameMemory import HistoryItem


@dataclass(frozen=True)
class LongTermView:
    """角色长期记忆的只读概览:直接引用 state 里已压缩的字段。"""
    consolidated: list[ConsolidatedMemoryBlock]
    long_term: list[LongTermMemoryEvent]
    pinned: list[LongTermMemoryEvent]


@dataclass(frozen=True)
class ActorMemoryContext:
    """喂给 agent 的收窄只读视图,取代直接传整个 GameState。

    构建时按需抽取引用(不深拷贝大对象)。
    - persona:沿用现有 CharacterProfile(人设 + memory_profile 配置)。
    - short_term:在场过滤后的最近数轮 history 明细。
    - long_term:角色自我状态概览(读现有压缩字段)。
    - retrieved:检索命中(本轮恒为空,Recall 检索层做好后填实)。
    """
    actor_id: str
    persona: CharacterProfile
    short_term: list[HistoryItem]
    long_term: LongTermView
    retrieved: list[Any]
