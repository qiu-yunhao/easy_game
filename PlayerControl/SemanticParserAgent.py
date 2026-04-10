from __future__ import annotations

from typing import Any

from Actor.ActorFormatter import normalize_resolved_act
from BaseAgent import BaseAgent
from CharacterProfile import CharacterProfile
from GameState import GameState, ResolvedAct
from PlayerControl.PlayerCommandTools import (
    load_tool_skills_for_prompt,
    normalize_tool_call,
    render_tool_schemas_for_prompt,
)
from PlayerControl.SemanticParserSchema import PLAYER_ACTION_RESPONSE_SCHEMA
from PromptUtils import render_json_instruction
from ResolvedActUtils import build_resolved_act_payload


SEMANTIC_PARSER_SYSTEM_PROMPT = """
You are the Semantic Parser Agent for a roleplay game.
Convert the player's natural-language action into strict JSON that the runtime can apply.

Rules:
1. Treat the player's raw input as the canonical content. Do not rewrite or embellish it.
2. Infer only metadata needed by the runtime: mode, target, intent shifts, emotional shifts,
   relationship deltas, revealed facts, plot flags, and whether the scene or chapter should end.
3. Keep updates local, conservative, and grounded in the current scene context.
4. `target` must be an on-stage character id or null.
5. Only set `triggered_plot_flags` for items that appear in `scene_plan.must_happen`.
6. Split the action into:
   - `spoken_text`: dialogue only.
   - `nonverbal_action`: movement, gesture, posture, silence, or other nonverbal behavior.
7. If the player is asking for out-of-band game information or save/load operations
   such as inventory, status, relations, quests, save, or load, set `tool_call`
   instead of forcing a narrative action. For those cases:
   - prefer `mode: "event"`
   - keep `spoken_text` and `nonverbal_action` empty unless the player also acts in-scene
   - fill `tool_call.name` and any minimal arguments the runtime needs
8. Tool definitions are organized into modular `skills/*.md` files.
   Use only the skill modules loaded for the current request instead of assuming every tool is always available.
"""


def _build_instruction(
    raw_input: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> str:
    planned_act = state["runtime"].get("next_act") or {}
    actor_id = planned_act.get("actor")
    payload = {
        "raw_player_input": raw_input,
        "scene": state["scene"],
        "scene_plan": state["scene_plan"],
        "director_brief": state["director_brief"],
        "next_act": planned_act,
        "actor_profile": character_profiles.get(actor_id or "", {}),
        "actor_runtime": state["characters"].get(actor_id or "", {}),
        "recent_history": state["history"][-8:],
        "loaded_tool_skills": load_tool_skills_for_prompt(raw_input),
        "available_tools": render_tool_schemas_for_prompt(raw_input),
    }
    return render_json_instruction(
        "Parse the following player action into runtime metadata as strict JSON.",
        payload,
    )


def _normalize_parsed_result(
    raw_input: str,
    raw_result: dict[str, Any] | None,
    state: GameState,
) -> ResolvedAct:
    planned_act = state["runtime"].get("next_act")
    tool_call = normalize_tool_call(raw_result.get("tool_call") if isinstance(raw_result, dict) else None)
    normalized = normalize_resolved_act(
        raw_result=build_resolved_act_payload(
            actor=planned_act.get("actor") if planned_act else None,
            mode=raw_result.get("mode", planned_act.get("mode", "speak")) if raw_result else "speak",
            target=raw_result.get("target") if raw_result else None,
            content=raw_input.strip() or "...",
            spoken_text=raw_result.get("spoken_text", "") if raw_result else "",
            nonverbal_action=raw_result.get("nonverbal_action", "") if raw_result else "",
            next_intent=raw_result.get("next_intent", "") if raw_result else "",
            emotion_update=raw_result.get("emotion_update", {}) if raw_result else {},
            relationship_update=raw_result.get("relationship_update", {}) if raw_result else {},
            revealed_facts=raw_result.get("revealed_facts", []) if raw_result else [],
            triggered_plot_flags=raw_result.get("triggered_plot_flags", {}) if raw_result else {},
            should_end_scene=raw_result.get("should_end_scene", False) if raw_result else False,
            should_end_chapter=raw_result.get("should_end_chapter", False) if raw_result else False,
        ),
        planned_act=planned_act,
        scene_plan=state["scene_plan"],
        on_stage=state["scene"].get("on_stage", []),
    )

    actor_id = normalized.get("actor") or ""
    if not normalized["next_intent"]:
        normalized["next_intent"] = state["characters"].get(actor_id, {}).get("intent", "")

    if not raw_input.strip():
        normalized["mode"] = "silence"
        normalized["content"] = "..."
        normalized["spoken_text"] = ""
        normalized["nonverbal_action"] = "..."

    normalized["tool_call"] = tool_call
    return normalized


class SemanticParserAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=SEMANTIC_PARSER_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.2),
            max_tokens=kwargs.pop("max_tokens", 700),
            **kwargs,
        )

    def parse_action(
        self,
        raw_input: str,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
    ) -> ResolvedAct:
        result = self.command(
            instruction=_build_instruction(raw_input, state, character_profiles),
            response_format=PLAYER_ACTION_RESPONSE_SCHEMA,
        )
        return _normalize_parsed_result(raw_input, result, state)
