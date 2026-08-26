from __future__ import annotations

from typing import Any

from Actor.ActorDedup import DEDUP_CORRECTION, is_duplicate_act
from Actor.ActorFormatter import build_l1_actor_instruction, normalize_resolved_act
from BaseAgent import BaseAgent
from GameState import GameState, ResolvedAct
from Memory.context import ActorMemoryContext

from Actor.ActorSchema import ACTOR_TURN_RESPONSE_SCHEMA


L1_ACTOR_SYSTEM_PROMPT = """
You are the L1 Core Character Agent in a multi-character story game.
You represent a major role such as a protagonist, key rival, or primary antagonist.

Rules:
1. Respect `next_act`, `scene_plan`, and `director_brief`.
2. When `l1_profile` is present, let its internal conflict, outer goal, and relationship pressure shape the turn.
3. Use `recent_history`, `recalled_memories`, and `player_memory` to preserve continuity.
4. Stay scene-bound and playable; do not skip ahead or narrate future outcomes.
5. Preserve the character's weight and complexity without becoming verbose.
6. `recalled_memories` are relevant past events you associate with the current situation; weave them naturally into your reaction, but never fabricate events that did not happen.
7. Never restate, paraphrase, or re-narrate an action, line, or beat that already appears in `recent_history`. Do not re-describe the same movement, decision, or inner monologue a second time.
8. Every turn MUST introduce a new, concrete development that moves the scene forward: act on a pending decision, change location or posture in a new way, trigger an event, or engage another on-stage character. If the previous turn ended on deliberation, this turn commits to an action and shows its consequence, driving toward `scene_plan.exit_condition`.
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
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        planned_act = state["runtime"].get("next_act")
        instruction = build_l1_actor_instruction(state=state, memory_ctx=memory_ctx)

        def _resolve(extra: str = "") -> ResolvedAct:
            return normalize_resolved_act(
                raw_result=self.command(
                    instruction=instruction if not extra else f"{instruction}\n\n{extra}",
                    response_format=ACTOR_TURN_RESPONSE_SCHEMA,
                ),
                planned_act=planned_act,
                scene_plan=state["scene_plan"],
                on_stage=state["scene"].get("on_stage", []),
            )

        resolved = _resolve()
        if is_duplicate_act(resolved.get("content", ""), memory_ctx.short_term):
            resolved = _resolve(DEDUP_CORRECTION)
        return resolved
