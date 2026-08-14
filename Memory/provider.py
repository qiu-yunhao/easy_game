from __future__ import annotations

from typing import Protocol, runtime_checkable

from GameState import GameState
from Memory.context import ActorMemoryContext


@runtime_checkable
class ActorMemoryProvider(Protocol):
    """记忆工厂协议:把三层记忆组装成 ActorMemoryContext。

    可注入、可替换、可 mock(像 history_manager 一样挂到 GraphDependencies)。
    实现必须只读:不得修改 state,不落任何存储。
    """

    def build(self, actor_id: str, state: GameState) -> ActorMemoryContext:
        ...
