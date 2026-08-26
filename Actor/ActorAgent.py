from __future__ import annotations

from typing import Any

from Actor.ActorDedup import DEDUP_CORRECTION, is_duplicate_act
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
10. Use `recent_history` to stay coherent with the current chapter and scene.
11. If `actor_profile.agent_type` is `L1`, let `l1_profile` and `recalled_memories` carry the deeper dramatic continuity.
12. `recalled_memories` are relevant past events you associate with the current situation; weave them naturally into your reaction, but never fabricate events that did not happen.
13. Never restate, paraphrase, or re-narrate an action, line, or beat that already appears in `recent_history`. Do not re-describe the same movement, decision, or inner monologue a second time.
14. Every turn MUST introduce a new, concrete development that moves the scene forward: act on a pending decision, change location or posture in a new way, trigger an event, or engage another on-stage character. If the previous turn ended on deliberation, this turn commits to an action and shows its consequence, driving toward `scene_plan.exit_condition`.
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
        instruction = build_actor_instruction(state=state, memory_ctx=memory_ctx)

        def _resolve(extra: str = "") -> ResolvedAct:
            return normalize_resolved_act(
                raw_result=self.command(
                    instruction=instruction if not extra else f"{instruction}\n\n{extra}",
                    response_format=ACTOR_TURN_RESPONSE_SCHEMA,
                ),
                planned_act=state["runtime"].get("next_act"),
                scene_plan=state["scene_plan"],
                on_stage=state["scene"].get("on_stage", []),
            )

        resolved = _resolve()
        if is_duplicate_act(resolved.get("content", ""), memory_ctx.short_term):
            resolved = _resolve(DEDUP_CORRECTION)
        return resolved
