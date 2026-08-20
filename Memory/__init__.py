"""角色三层记忆注入包(与 Recall/ 平级)。

只读记忆工厂:把角色三层记忆(短期=在场过滤 / 长期=复用压缩产物 / 检索=占位)
组装成收窄的只读 DTO ActorMemoryContext,取代直接向 agent 传整个 GameState。
工厂只读,不落任何存储。
"""

from __future__ import annotations

from Memory.context import ActorMemoryContext
from Memory.default_provider import DefaultActorMemoryProvider
from Memory.provider import ActorMemoryProvider
from Memory.scene_filter import (
    PresenceGranularity,
    filter_history_by_presence,
)

__all__ = [
    "ActorMemoryContext",
    "ActorMemoryProvider",
    "DefaultActorMemoryProvider",
    "PresenceGranularity",
    "filter_history_by_presence",
]
