from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from GameState import GameState
from PlayerControl.PlayerConsole import PlayerInterface

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


class BufferedPlayerInterface(PlayerInterface):
    def __init__(self) -> None:
        self._pending_actions: deque[str] = deque()

    def push_action(self, raw_input: str) -> None:
        self._pending_actions.append(raw_input)

    def clear(self) -> None:
        self._pending_actions.clear()

    def has_pending_action(self) -> bool:
        return bool(self._pending_actions)

    def collect_action(
        self,
        state: GameState,
        actor_id: str,
        character_profiles: dict[str, "CharacterProfile"],
    ) -> str:
        del state, actor_id, character_profiles
        if not self._pending_actions:
            raise RuntimeError("No buffered player action is available for the current turn.")
        return self._pending_actions.popleft()
