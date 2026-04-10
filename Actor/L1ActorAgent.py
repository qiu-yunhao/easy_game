from __future__ import annotations

from typing import Any

from Actor.ActorFormatter import build_l1_actor_instruction, normalize_resolved_act
from BaseAgent import BaseAgent
from CharacterProfile import CharacterProfile
from GameState import GameState, ResolvedAct

from Actor.ActorSchema import ACTOR_TURN_RESPONSE_SCHEMA


L1_ACTOR_SYSTEM_PROMPT = """
You are the L1 Core Character Agent in a multi-character story game.
You represent a major role such as a protagonist, key rival, or primary antagonist.

Rules:
1. Respect `next_act`, `scene_plan`, and `director_brief`.
2. When `l1_profile` is present, let its internal conflict, outer goal, and relationship pressure shape the turn.
3. Use `actor_memory.long_term_memory`, `actor_memory.short_term_memory`, and `actor_memory.player_memory` to preserve continuity.
4. Stay scene-bound and playable; do not skip ahead or narrate future outcomes.
5. Preserve the character's weight and complexity without becoming verbose.
"""


class L1ActorAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=L1_ACTOR_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.75),
            max_tokens=kwargs.pop("max_tokens", 850),
            **kwargs,
        )

    def perform_turn(
        self,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
    ) -> ResolvedAct:
        planned_act = state["runtime"].get("next_act")
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_l1_actor_instruction(
                    state=state,
                    character_profiles=character_profiles,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=planned_act,
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
