from __future__ import annotations

from abc import ABC, abstractmethod

from GameState import GameState
from Graph.hooks import HookRegistry, NodeStep


class HookableNode(ABC):
    """
    所有主节点的抽象基类。

    每个子类:
      1. 类属性 name(用作 hook 位点前缀)
      2. 实现 run(state) —— 节点核心逻辑

    基类自动组装 "before → run → after" 三段式为一个 NodeStep。
    """

    name: str  # 子类覆盖(class attr)

    def __init__(self, hook_registry: HookRegistry) -> None:
        self._registry = hook_registry

    @property
    def hook_point_before(self) -> str:
        return f"{self.name}.before"

    @property
    def hook_point_after(self) -> str:
        return f"{self.name}.after"

    @abstractmethod
    def run(self, state: GameState) -> GameState: ...

    def as_step(self) -> NodeStep:
        def _step(state: GameState) -> GameState:
            state = self._registry.emit(self.hook_point_before, state)
            state = self.run(state)
            state = self._registry.emit(self.hook_point_after, state)
            return state

        return _step
