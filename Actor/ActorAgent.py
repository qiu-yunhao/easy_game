from __future__ import annotations

from typing import Any

from Actor.ActorFormatter import build_actor_instruction, normalize_resolved_act
from BaseAgent import BaseAgent
from GameState import GameState, ResolvedAct
from Memory.context import ActorMemoryContext

from Actor.ActorSchema import ACTOR_TURN_RESPONSE_SCHEMA


ACTOR_SYSTEM_PROMPT = """
You are the Character Actor Agent in a multi-character story game.
Stay inside the assigned role, follow the current scene plan and director brief,
and produce one concrete turn as JSON.

Rules:
1. Respect `next_act`, the actor's runtime intent, the scene plan, and the director brief.
2. Keep the turn playable in the current moment. Avoid narration that skips the scene ahead.
3. Do not violate `scene_plan.must_not_happen`.
4. Only set `triggered_plot_flags` for items that are actually in `scene_plan.must_happen`.
5. `relationship_update` represents how the acting character's stance changes toward others.
6. Separate dialogue from movement:
   - `spoken_text` is direct speech only, without speaker tags.
   - `nonverbal_action` is the physical, atmospheric, or nonverbal part only.
7. Keep `nonverbal_action` concrete and scene-bound. Avoid generic AI-sounding filler.
8. `should_end_scene` means this specific scene can close after the turn.
9. `should_end_chapter` means the broader chapter arc is ready to roll into the next chapter.
10. If `actor_profile.agent_type` is `L2`, prioritize the compact support-role logic in `l2_profile`:
    - follow the single `core_drive`
    - stay within `judgement_preference` and `behavior_rule`
    - let `speech_style` shape wording
    - support the scene without trying to dominate it
11. Use `recent_short_term_memory` to stay coherent with the current chapter and scene.
12. Use `player_memory` when the player is involved in the interaction.
13. If `actor_profile.agent_type` is `L1`, let `l1_profile`, `actor_memory.pinned_long_term_memory`, `actor_memory.consolidated_memory`, and `actor_memory.long_term_memory` carry the deeper dramatic continuity.
14. `recalled_memories` are relevant past events you associate with the current situation; weave them naturally into your reaction, but never fabricate events that did not happen.
"""

class ActorAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=ACTOR_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.8),
            max_tokens=kwargs.pop("max_tokens", 900),
            **kwargs,
        )

    def perform_turn(
        self,
        state: GameState,
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_actor_instruction(
                    state=state,
                    memory_ctx=memory_ctx,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=state["runtime"].get("next_act"),
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
