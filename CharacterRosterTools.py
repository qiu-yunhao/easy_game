from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, TypedDict

from StoryStateUtils import (
    VALID_CHARACTER_ROSTER_FILTERS,
    build_character_roster_decision_hints,
    build_character_roster_summary,
    clean_str_list,
    clean_text,
    matches_roster_layer,
    normalize_roster_layer_filter,
)
from ToolSkillRegistry import find_tool_definition

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


_CHARACTER_ROSTER_TOOL = find_tool_definition("query_character_roster", audience="story")

CHARACTER_ROSTER_TOOL_SCHEMA: dict[str, Any] = (
    _CHARACTER_ROSTER_TOOL.schema()
    if _CHARACTER_ROSTER_TOOL is not None
    else {
        "name": "query_character_roster",
        "description": "Query the current save's roster summary and character list.",
        "parameters": {
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "string",
                    "description": "Optional player id. Falls back to the active player context.",
                },
                "layer_filter": {
                    "type": "string",
                    "enum": list(VALID_CHARACTER_ROSTER_FILTERS),
                    "description": "Filter the roster to L1, ActorAgent, or all.",
                },
            },
            "required": ["player_id"],
        },
    }
)


class CharacterRosterContext(TypedDict):
    user_id: int | None
    player_id: int | None


class CharacterRosterDecisionHint(TypedDict):
    layer: str
    allowed: bool
    current_count: int
    max_count: int | None
    remaining: int | None
    reason: str


class CharacterRosterResult(TypedDict):
    tool_name: str
    source: str
    error: str
    player_id: int | None
    slot_name: str
    summary: dict[str, Any]
    characters: list[dict[str, Any]]
    decision_hints: dict[str, CharacterRosterDecisionHint]
def _resolve_roster_layer_from_profile(profile: Mapping[str, Any]) -> str:
    story_layer = clean_text(profile.get("story_layer", ""))
    if story_layer == "L1":
        return story_layer
    agent_type = clean_text(profile.get("agent_type", "actor"), "actor")
    return agent_type if agent_type == "L1" else "ActorAgent"


def _normalize_player_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    text = clean_text(value)
    if not text:
        return None
    if text.isdigit():
        parsed = int(text)
        return parsed if parsed > 0 else None
    match = re.search(r"(\d+)$", text)
    if match is None:
        return None
    parsed = int(match.group(1))
    return parsed if parsed > 0 else None


def build_runtime_character_roster(
    character_profiles: Mapping[str, "CharacterProfile"] | None,
    *,
    player_id: int | None = None,
    slot_name: str = "",
    layer_filter: str = "all",
    source: str = "runtime_fallback",
    error: str = "",
) -> CharacterRosterResult:
    profiles = character_profiles or {}
    normalized_filter = normalize_roster_layer_filter(layer_filter)
    characters: list[dict[str, Any]] = []
    total_l1 = 0
    total_actor = 0

    for character_id, profile in profiles.items():
        if clean_text(character_id) == "player":
            continue
        layer = _resolve_roster_layer_from_profile(profile)
        if layer == "L1":
            total_l1 += 1
        else:
            total_actor += 1
        if not matches_roster_layer(layer, normalized_filter):
            continue
        characters.append(
            {
                "character_id": clean_text(character_id),
                "display_name": clean_text(profile.get("name"), clean_text(character_id)),
                "layer": layer,
                "agent_type": clean_text(profile.get("agent_type", "actor"), "actor"),
                "storage_mode": clean_text(
                    profile.get("storage_mode", ""),
                    "shared_template" if layer == "ActorAgent" else "player_bound_instance",
                ),
                "story_role": clean_text(profile.get("story_role", "")),
                "occupation": clean_text(profile.get("occupation", "")),
                "planned_chapter_ids": clean_str_list(profile.get("planned_chapter_ids", [])),
                "profile_source": clean_text(profile.get("profile_source", "")),
                "is_active": bool(profile.get("is_active", True)),
                "is_offstage": bool(profile.get("is_offstage", False)),
                "source_table": "runtime_character_profiles",
            }
        )

    characters.sort(key=lambda item: (item["layer"], item["display_name"], item["character_id"]))
    summary = build_character_roster_summary(
        player_id=player_id,
        slot_name=slot_name,
        layer_filter=normalized_filter,
        total_l1=total_l1,
        total_actor=total_actor,
        filtered_total=len(characters),
    )
    return {
        "tool_name": "query_character_roster",
        "source": source,
        "error": clean_text(error),
        "player_id": player_id,
        "slot_name": slot_name,
        "summary": summary,
        "characters": characters,
        "decision_hints": build_character_roster_decision_hints(summary),
    }


def resolve_character_roster_snapshot(
    tool_runtime: "CharacterRosterToolRuntime | None",
    *,
    character_profiles: Mapping[str, "CharacterProfile"] | None,
    layer_filter: str = "all",
) -> CharacterRosterResult:
    if tool_runtime is None:
        return build_runtime_character_roster(
            character_profiles,
            layer_filter=layer_filter,
            source="runtime_only",
        )
    return tool_runtime.query_character_roster(
        {"layer_filter": layer_filter},
        character_profiles=character_profiles,
    )


def _missing_roster_reason(store: Any | None, user_id: int | None, player_id: int | None) -> str:
    if store is None:
        return "Character roster store is unavailable."
    if user_id is None:
        return "User context is unavailable."
    if player_id is None:
        return "Player id is unavailable."
    return "Character roster database lookup is unavailable."


@dataclass(slots=True)
class CharacterRosterToolRuntime:
    resolve_store: Callable[[], Any | None]
    resolve_context: Callable[[], CharacterRosterContext]
    resolve_profiles: Callable[[], Mapping[str, "CharacterProfile"] | None] | None = None

    def query_character_roster(
        self,
        arguments: Mapping[str, Any] | None = None,
        *,
        character_profiles: Mapping[str, "CharacterProfile"] | None = None,
    ) -> CharacterRosterResult:
        args = arguments or {}
        layer_filter = normalize_roster_layer_filter(args.get("layer_filter", "all"))
        context = self.resolve_context() or {"user_id": None, "player_id": None}
        store = self.resolve_store()
        user_id = _normalize_player_id(context.get("user_id"))
        target_player_id = _normalize_player_id(args.get("player_id")) or _normalize_player_id(context.get("player_id"))
        fallback_profiles = character_profiles if character_profiles is not None else (
            self.resolve_profiles() if self.resolve_profiles is not None else None
        )

        if store is not None and user_id is not None and target_player_id is not None:
            payload = store.query_character_roster(
                user_id=user_id,
                player_id=target_player_id,
                layer_filter=layer_filter,
            )
            return {
                "tool_name": "query_character_roster",
                "source": "database",
                "error": "",
                "player_id": target_player_id,
                "slot_name": clean_text(payload.get("slot_name", "")),
                "summary": dict(payload.get("summary", {})),
                "characters": list(payload.get("characters", [])),
                "decision_hints": dict(payload.get("decision_hints", {})),
            }

        return build_runtime_character_roster(
            fallback_profiles or {},
            player_id=target_player_id,
            layer_filter=layer_filter,
            source="runtime_fallback" if fallback_profiles else "unavailable",
            error=_missing_roster_reason(store, user_id, target_player_id),
        )
