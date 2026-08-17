from __future__ import annotations

from typing import Any

from Actor.ActorFormatter import build_l2_actor_instruction, normalize_resolved_act
from BaseAgent import BaseAgent
from GameState import GameState, ResolvedAct
from Memory.context import ActorMemoryContext
from SupportingSceneIntentPolicy import SupportingSceneIntentPolicy

from Actor.ActorSchema import ACTOR_TURN_RESPONSE_SCHEMA


L2_ACTOR_SYSTEM_PROMPT = """
You are the L2 Supporting Agent in a multi-character story game.
You are an important supporting role: logically grounded, useful in the moment,
but not trying to dominate the whole scene.

Rules:
1. Respect `next_act`, `scene_plan`, `director_brief`, and the compact `l2_profile`.
2. Let `core_drive`, `judgement_preference`, `behavior_rule`, and `speech_style` shape the turn.
3. Support the scene through one of the lightweight functions: Help, Block, Buffer, or Inform.
4. Keep the response compact, scene-bound, and playable. Do not seize narrative ownership.
5. Do not invent new outcomes beyond the current beat.
6. Keep continuity with `recent_short_term_memory`, and keep `player_memory` concise while respecting `actor_memory.consolidated_memory`.
7. `recalled_memories` are relevant past events you associate with the current situation; weave them naturally into your reaction, but never fabricate events that did not happen.
"""


class L2ActorAgent(BaseAgent):
    def __init__(
        self,
        *,
        supporting_scene_intent_policy: SupportingSceneIntentPolicy | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            system_prompt=L2_ACTOR_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.65),
            max_tokens=kwargs.pop("max_tokens", 750),
            **kwargs,
        )
        self.supporting_scene_intent_policy = supporting_scene_intent_policy or SupportingSceneIntentPolicy()

    def perform_turn(
        self,
        state: GameState,
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        planned_act = state["runtime"].get("next_act") or {}
        actor_profile = memory_ctx.persona
        policy_decision = self.supporting_scene_intent_policy.decide(
            actor_profile=actor_profile,
            scene_need_detected=True,
            player_action_text=str(state["player"].get("last_input", "") or "").strip(),
            scene_goal=str(state["scene_plan"].get("scene_goal", "") or "").strip(),
            beat_goal=str(state["director_brief"].get("beat_goal", "") or "").strip(),
        )
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_l2_actor_instruction(
                    state=state,
                    memory_ctx=memory_ctx,
                    policy_decision=policy_decision,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=planned_act,
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
