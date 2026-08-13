from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from GameState import GameState


NodeStep = Callable[[GameState], GameState]


class HookFn(Protocol):
    """Hook 函数签名 —— 与 NodeStep 完全一致,保证可互换。"""

    def __call__(self, state: GameState) -> GameState: ...


@dataclass(slots=True)
class HookRegistry:
    """按位点名存 hook 列表。emit 时按注册顺序依次调用。"""

    _hooks: dict[str, list[HookFn]] = field(default_factory=dict)

    def register(self, hook_point: str, fn: HookFn) -> None:
        self._hooks.setdefault(hook_point, []).append(fn)

    def clear(self, hook_point: str | None = None) -> None:
        if hook_point is None:
            self._hooks.clear()
        else:
            self._hooks.pop(hook_point, None)

    def emit(self, hook_point: str, state: GameState) -> GameState:
        hooks = self._hooks.get(hook_point)
        if not hooks:
            return state
        for hook in hooks:
            state = hook(state)
        return state

    def registered_points(self) -> list[str]:
        return sorted(self._hooks.keys())
