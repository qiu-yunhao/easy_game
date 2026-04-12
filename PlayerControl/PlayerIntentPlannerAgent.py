from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

from BaseAgent import BaseAgent
from CharacterProfile import CharacterProfile
from GameState import GameState
from PlayerControl.PlayerCommandTools import (
    PLAYER_TOOL_NAMES,
    PlayerToolCall,
    empty_tool_call,
    infer_player_tool_call,
    load_tool_skills_for_prompt,
    normalize_tool_call,
    render_tool_schemas_for_prompt,
)
from PromptUtils import render_json_instruction


PlayerIntentStepKind = Literal["narrative_action", "tool_call"]


class PlayerIntentStep(TypedDict):
    kind: PlayerIntentStepKind
    content: str
    tool_call: PlayerToolCall
    reason: str


class PlayerIntentPlan(TypedDict):
    planned_steps: list[PlayerIntentStep]


PLAYER_INTENT_PLAN_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "player_intent_plan",
        "schema": {
            "type": "object",
            "properties": {
                "planned_steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["narrative_action", "tool_call"]},
                            "content": {"type": "string"},
                            "tool_call": {
                                "type": "object",
                                "properties": {
                                    "should_call": {"type": "boolean"},
                                    "name": {"type": "string", "enum": ["", *PLAYER_TOOL_NAMES]},
                                    "arguments": {"type": "object", "additionalProperties": True},
                                    "reason": {"type": "string"},
                                },
                                "required": ["should_call", "name", "arguments", "reason"],
                                "additionalProperties": False,
                            },
                            "reason": {"type": "string"},
                        },
                        "required": ["kind", "content", "tool_call", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["planned_steps"],
            "additionalProperties": False,
        },
    },
}


PLAYER_INTENT_PLANNER_SYSTEM_PROMPT = """
You are the Player Intent Planner for a roleplay game.
Split a player's input into a short, ordered list of safe runtime steps.

Rules:
1. Preserve the player's wording. Do not embellish.
2. Use `narrative_action` for in-scene actions, speech, movement, item usage, or attempts.
3. Use `tool_call` only for out-of-band game information or save/load requests.
4. Keep the order from the player's input.
5. Do not invent tools. Use only the loaded skill modules and available tool schemas.
6. If the player both acts in-scene and asks for game information, keep them as separate steps.
7. Return at most 5 steps.
"""


_STEP_SPLIT_PATTERN = re.compile(
    r"\s*(?:然后|接着|随后|再|顺便|并且|而且|同时|；|;|。|(?<!\w)and then(?!\w)|(?<!\w)then(?!\w))\s*",
    re.IGNORECASE,
)
_NARRATIVE_ITEM_USE_MARKERS = ("使用", "用", "拿", "打开", "开启", "解锁", "use", "open", "unlock")
_INVENTORY_READ_MARKERS = ("查看", "看看", "检查", "有什么", "清点", "show", "list", "check")


def _empty_tool_step(content: str, *, reason: str = "") -> PlayerIntentStep:
    return {
        "kind": "narrative_action",
        "content": content.strip(),
        "tool_call": empty_tool_call(),
        "reason": reason,
    }


def _tool_step(content: str, tool_call: PlayerToolCall) -> PlayerIntentStep:
    return {
        "kind": "tool_call",
        "content": content.strip(),
        "tool_call": tool_call,
        "reason": tool_call.get("reason", ""),
    }


def _split_intent_fragments(raw_input: str) -> list[str]:
    fragments = [fragment.strip(" ,，") for fragment in _STEP_SPLIT_PATTERN.split(raw_input.strip())]
    return [fragment for fragment in fragments if fragment]


def _should_keep_as_narrative(fragment: str, tool_call: PlayerToolCall) -> bool:
    if tool_call["name"] != "query_inventory":
        return False
    normalized = fragment.lower()
    has_item_action = any(marker in normalized for marker in _NARRATIVE_ITEM_USE_MARKERS)
    has_read_request = any(marker in normalized for marker in _INVENTORY_READ_MARKERS)
    return has_item_action and not has_read_request


def _normalize_planned_steps(raw_steps: Any, raw_input: str) -> list[PlayerIntentStep]:
    if not isinstance(raw_steps, list):
        return [_empty_tool_step(raw_input)]

    normalized_steps: list[PlayerIntentStep] = []
    for raw_step in raw_steps[:5]:
        if not isinstance(raw_step, dict):
            continue
        content = str(raw_step.get("content") or "").strip()
        kind = str(raw_step.get("kind") or "").strip()
        if kind == "tool_call":
            tool_call = normalize_tool_call(raw_step.get("tool_call") if isinstance(raw_step.get("tool_call"), dict) else None)
            if tool_call["should_call"]:
                normalized_steps.append(_tool_step(content or raw_input, tool_call))
        elif kind == "narrative_action" and content:
            normalized_steps.append(_empty_tool_step(content, reason=str(raw_step.get("reason", "") or "").strip()))

    return normalized_steps or [_empty_tool_step(raw_input)]


def normalize_player_intent_plan(raw_plan: dict[str, Any] | None, raw_input: str) -> PlayerIntentPlan:
    return {
        "planned_steps": _normalize_planned_steps(
            raw_plan.get("planned_steps") if isinstance(raw_plan, dict) else None,
            raw_input,
        )
    }


def build_heuristic_player_intent_plan(
    raw_input: str,
    *,
    character_profiles: dict[str, CharacterProfile] | None = None,
) -> PlayerIntentPlan:
    steps: list[PlayerIntentStep] = []
    for fragment in _split_intent_fragments(raw_input) or [raw_input.strip()]:
        tool_call = infer_player_tool_call(fragment, character_profiles=character_profiles)
        if tool_call is not None and not _should_keep_as_narrative(fragment, tool_call):
            steps.append(_tool_step(fragment, tool_call))
        elif fragment.strip():
            steps.append(_empty_tool_step(fragment))
    return {"planned_steps": steps or [_empty_tool_step(raw_input)]}


def _build_instruction(
    raw_input: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> str:
    return render_json_instruction(
        "Plan the following player input into ordered runtime steps as strict JSON.",
        {
            "raw_player_input": raw_input,
            "scene": state["scene"],
            "next_act": state["runtime"].get("next_act") or {},
            "on_stage_profiles": {
                character_id: character_profiles.get(character_id, {})
                for character_id in state["scene"].get("on_stage", [])
            },
            "loaded_tool_skills": load_tool_skills_for_prompt(raw_input),
            "available_tools": render_tool_schemas_for_prompt(raw_input),
        },
    )


class PlayerIntentPlannerAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=PLAYER_INTENT_PLANNER_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.1),
            max_tokens=kwargs.pop("max_tokens", 700),
            **kwargs,
        )

    def plan_action(
        self,
        raw_input: str,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
    ) -> PlayerIntentPlan:
        result = self.command(
            instruction=_build_instruction(raw_input, state, character_profiles),
            response_format=PLAYER_INTENT_PLAN_RESPONSE_SCHEMA,
        )
        return normalize_player_intent_plan(result, raw_input)
