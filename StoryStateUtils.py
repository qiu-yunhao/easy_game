from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile
    from GameState import GameState


def clean_text(value: Any, fallback: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def clean_str_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]

    cleaned: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def normalize_lookup_text(value: Any) -> str:
    return "".join(clean_text(value).lower().split())


def matches_lookup(target: Any, *candidates: Any) -> bool:
    normalized_target = normalize_lookup_text(target)
    if not normalized_target:
        return False
    for candidate in candidates:
        normalized_candidate = normalize_lookup_text(candidate)
        if normalized_candidate and (
            normalized_target == normalized_candidate
            or normalized_target in normalized_candidate
            or normalized_candidate in normalized_target
        ):
            return True
    return False


MAX_L1_CHARACTERS = 6
MAX_L2_CHARACTERS = 15
VALID_CHARACTER_ROSTER_FILTERS = ("L1", "L2", "ActorAgent", "all")


def normalize_roster_layer_filter(value: Any) -> str:
    lowered = clean_text(value, "all").lower().replace("_", "").replace("-", "")
    if lowered == "l1":
        return "L1"
    if lowered == "l2":
        return "L2"
    if lowered in {"actor", "actoragent", "actors"}:
        return "ActorAgent"
    return "all"


def matches_roster_layer(layer: str, layer_filter: Any) -> bool:
    normalized_filter = normalize_roster_layer_filter(layer_filter)
    return normalized_filter == "all" or clean_text(layer) == normalized_filter


def _remaining_count(current_count: int, max_count: int | None) -> int | None:
    if max_count is None:
        return None
    return max(max_count - current_count, 0)


def build_character_roster_summary(
    *,
    player_id: int | None,
    slot_name: str,
    layer_filter: Any,
    total_l1: int,
    total_l2: int,
    total_actor: int,
    filtered_total: int,
) -> dict[str, Any]:
    normalized_filter = normalize_roster_layer_filter(layer_filter)
    return {
        "player_id": player_id,
        "slot_name": slot_name,
        "layer_filter": normalized_filter,
        "total_L1": total_l1,
        "max_L1": MAX_L1_CHARACTERS,
        "remaining_L1": _remaining_count(total_l1, MAX_L1_CHARACTERS),
        "total_L2": total_l2,
        "max_L2": MAX_L2_CHARACTERS,
        "remaining_L2": _remaining_count(total_l2, MAX_L2_CHARACTERS),
        "total_ActorAgent": total_actor,
        "max_ActorAgent": None,
        "remaining_ActorAgent": None,
        "total_player_bound": total_l1 + total_l2,
        "total_all": total_l1 + total_l2 + total_actor,
        "filtered_total": filtered_total,
    }


def build_character_roster_decision_hints(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    hints: dict[str, dict[str, Any]] = {}
    for layer in ("L1", "L2", "ActorAgent"):
        current_count = int(summary.get(f"total_{layer}", 0) or 0)
        raw_max = summary.get(f"max_{layer}")
        max_count = int(raw_max) if isinstance(raw_max, (int, float)) else None
        remaining = _remaining_count(current_count, max_count)
        if max_count is None:
            reason = "ActorAgent characters come from shared templates, so there is no per-save hard cap."
            allowed = True
        else:
            allowed = current_count < max_count
            reason = (
                f"{layer} character slots are available ({current_count}/{max_count})."
                if allowed
                else f"{layer} character slots are full ({current_count}/{max_count})."
            )
        hints[layer] = {
            "layer": layer,
            "allowed": allowed,
            "current_count": current_count,
            "max_count": max_count,
            "remaining": remaining,
            "reason": reason,
        }
    return hints


def resolve_player_character_id(
    game_state: "GameState",
    character_profiles: dict[str, "CharacterProfile"],
) -> str:
    player_id = clean_text(game_state.get("player", {}).get("controlled_character"))
    if player_id and player_id in character_profiles:
        return player_id
    if "player" in character_profiles:
        return "player"
    return next(iter(character_profiles), "")


def resolve_player_profile(
    game_state: "GameState",
    character_profiles: dict[str, "CharacterProfile"],
) -> tuple[str, "CharacterProfile"]:
    player_id = resolve_player_character_id(game_state, character_profiles)
    return player_id, character_profiles.get(player_id, {})


def story_outline_entries(game_state: "GameState") -> list[dict[str, Any]]:
    return [
        dict(chapter)
        for chapter in game_state["plot"].get("story_outline", [])
        if isinstance(chapter, dict)
    ]


def current_outline_entry(game_state: "GameState") -> dict[str, Any]:
    chapter_id = clean_text(game_state["plot"].get("chapter_id"))
    story_outline = story_outline_entries(game_state)
    for chapter in story_outline:
        if clean_text(chapter.get("chapter_id")) == chapter_id:
            return dict(chapter)

    chapter_index = int(game_state["plot"].get("current_chapter_index", 0) or 0)
    if 0 <= chapter_index < len(story_outline):
        return dict(story_outline[chapter_index])
    return dict(story_outline[0]) if story_outline else {}


def outline_index(story_outline: list[dict[str, Any]], chapter_id: Any) -> int:
    resolved_chapter_id = clean_text(chapter_id)
    for index, chapter in enumerate(story_outline):
        if clean_text(chapter.get("chapter_id")) == resolved_chapter_id:
            return index
    return -1


def serialize_story_cast_member(
    character_id: str,
    profile: "CharacterProfile",
) -> dict[str, Any]:
    l2_profile = profile.get("l2_profile", {})
    l1_profile = profile.get("l1_profile", {})
    layer_assignment = profile.get("layer_assignment", {})
    memory_profile = profile.get("memory_profile", {})
    return {
        "character_id": character_id,
        "name": clean_text(profile.get("name", character_id), character_id),
        "background": clean_text(profile.get("background", "")),
        "story_role": clean_text(profile.get("story_role", "")),
        "spiritual_root": clean_text(profile.get("spiritual_root", "")),
        "realm": clean_text(profile.get("realm", "")),
        "main_technique": clean_text(profile.get("main_technique", "")),
        "persona": clean_str_list(profile.get("persona", [])),
        "base_style": clean_text(profile.get("base_style", "")),
        "agent_type": clean_text(profile.get("agent_type", "actor"), "actor"),
        "story_layer": clean_text(profile.get("story_layer", "actor"), "actor"),
        "storage_mode": clean_text(profile.get("storage_mode", "player_bound_instance"), "player_bound_instance"),
        "occupation": clean_text(profile.get("occupation", "")),
        "l2_profile": dict(l2_profile) if isinstance(l2_profile, dict) else {},
        "l1_profile": dict(l1_profile) if isinstance(l1_profile, dict) else {},
        "layer_assignment": dict(layer_assignment) if isinstance(layer_assignment, dict) else {},
        "memory_profile": dict(memory_profile) if isinstance(memory_profile, dict) else {},
        "is_active": bool(profile.get("is_active", True)),
        "is_offstage": bool(profile.get("is_offstage", False)),
        "planned_chapter_count": int(profile.get("planned_chapter_count", 0) or 0),
        "planned_chapter_ids": clean_str_list(profile.get("planned_chapter_ids", [])),
        "profile_source": clean_text(profile.get("profile_source", "")),
    }
