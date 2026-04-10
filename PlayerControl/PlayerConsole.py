from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from GameState import GameState

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


class PlayerInterface(Protocol):
    def collect_action(
        self,
        state: GameState,
        actor_id: str,
        character_profiles: dict[str, "CharacterProfile"],
    ) -> str:
        ...


class ConsolePlayerInterface:
    def __init__(self, recent_history_limit: int = 4) -> None:
        self.recent_history_limit = recent_history_limit

    def collect_action(
        self,
        state: GameState,
        actor_id: str,
        character_profiles: dict[str, "CharacterProfile"],
    ) -> str:
        profile = character_profiles.get(actor_id, {})
        display_name = profile.get("name", actor_id)
        planned_act = state["runtime"].get("next_act") or {}
        recent_history = state["history"][-self.recent_history_limit :]

        print("\n--- Player Panel ---")
        print(f"Role            : {display_name} ({actor_id})")
        print(f"Scene goal      : {state['scene_plan'].get('scene_goal', '')}")
        print(f"Beat goal       : {state['director_brief'].get('beat_goal', '')}")
        print(f"Suggested mode  : {planned_act.get('mode', 'speak')}")
        print(f"Suggested target: {planned_act.get('target') or 'none'}")

        if recent_history:
            print("Recent history  :")
            for item in recent_history:
                print(f"  - [{item['actor']}] {item['content']}")

        print("Input hint      : type dialogue or describe an action; empty input means silence.")
        try:
            return input("Player action > ").strip()
        except EOFError:
            return ""
