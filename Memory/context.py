from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from CharacterProfile import CharacterProfile
from History.GameMemory import HistoryItem


@dataclass(frozen=True)
class ActorMemoryContext:
    """喂给 agent 的收窄只读视图。

    - persona:沿用现有 CharacterProfile(人设 + memory_profile 配置)。
    - short_term:在场过滤后的最近数轮 history 明细。
    - retrieved:长期 RAG 召回(仅 L1;Step 3 接实,此前恒空)。
    """
    actor_id: str
    persona: CharacterProfile
    short_term: list[HistoryItem]
    retrieved: list[Any]
