from __future__ import annotations

from typing import Any

from Persistence.Models import (
    PlayerActorInteraction,
    PlayerQuest,
    PlayerSaveSnapshot,
    PlayerSlot,
    PlayerStoryCharacter,
    StoryCharacterTemplate,
    UserAccount,
)
from Persistence.store_common import clean_text, clone_json, dedupe_character_ids, serialize_dt, serialize_numeric
from Memory.store import MemoryStore

_MEMORY_STORE = MemoryStore()


def require_snapshot_value(snapshot: dict[str, Any], key: str, expected_type: type) -> Any:
    value = snapshot.get(key)
    if not isinstance(value, expected_type):
        raise ValueError(f"session snapshot is missing `{key}` or it has an invalid type")
    return value


def player_character_id_from_snapshot(snapshot: dict[str, Any]) -> str:
    session_meta = require_snapshot_value(snapshot, "session", dict)
    state = require_snapshot_value(snapshot, "state", dict)
    return clean_text(
        session_meta.get("player_character"),
        clean_text(state.get("player", {}).get("controlled_character"), "player"),
    )


def player_profile_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    player_profile = require_snapshot_value(snapshot, "character_profiles", dict).get(
        player_character_id_from_snapshot(snapshot)
    )
    return clone_json(player_profile) if isinstance(player_profile, dict) else {}


def build_player_attributes(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = require_snapshot_value(snapshot, "state", dict)
    player_profile = player_profile_from_snapshot(snapshot)
    attributes = {key: player_profile[key] for key in ("hp", "mp", "money", "stamina", "luck", "attack", "defense") if key in player_profile}
    attributes.setdefault("realm", player_profile.get("realm", ""))
    attributes.setdefault("spiritual_root", player_profile.get("spiritual_root", ""))
    attributes.setdefault("main_technique", player_profile.get("main_technique", ""))
    attributes.setdefault("tension_percent", int(float(state.get("scene", {}).get("tension", 0.0) or 0.0) * 100))
    return clone_json(attributes)


def _merge_character_memory(
    characters: dict[str, Any], character_memory: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for character_id, character in characters.items():
        if not isinstance(character, dict):
            result[character_id] = character
            continue
        merged = {key: value for key, value in character.items() if key != "memory"}
        kept = character_memory.get(character_id)
        if kept:
            merged["memory"] = kept
        result[character_id] = merged
    return result


def build_world_state_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = require_snapshot_value(snapshot, "state", dict)
    memory_fragment = _MEMORY_STORE.deserialize_memory(_MEMORY_STORE.serialize_memory(state))
    payload = {key: clone_json(state.get(key, default)) for key, default in (
        ("plot", {}),
        ("scene", {}),
        ("runtime", {}),
        ("scene_plan", {}),
        ("director_brief", {}),
        ("history", []),
        ("player", {}),
    )}
    payload["memory"] = memory_fragment["memory"]
    payload["characters"] = _merge_character_memory(
        clone_json(state.get("characters", {})),
        memory_fragment["character_memory"],
    )
    return payload


def build_plot_flags_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return clone_json(require_snapshot_value(snapshot, "state", dict).get("plot", {}).get("plot_flags", {}))


def build_scene_flags_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = require_snapshot_value(snapshot, "state", dict)
    scene = state.get("scene", {})
    runtime = state.get("runtime", {})
    return {
        "on_stage": clone_json(scene.get("on_stage", [])),
        "suppressed": clone_json(scene.get("suppressed", [])),
        "focus_character": clean_text(scene.get("focus_character")),
        "allow_interrupt": bool(scene.get("allow_interrupt", False)),
        "scene_finished": bool(runtime.get("scene_finished", False)),
        "chapter_finished": bool(runtime.get("chapter_finished", False)),
    }


def _collect_story_character_ids(snapshot: dict[str, Any]) -> list[str]:
    state = require_snapshot_value(snapshot, "state", dict)
    player_character_id = player_character_id_from_snapshot(snapshot)
    candidates = [
        *[
            item.get("actor")
            for item in state.get("history", [])
            if isinstance(item, dict) and clean_text(item.get("actor")) and item.get("actor") != player_character_id
        ],
        *state.get("scene", {}).get("on_stage", []),
        *state.get("scene", {}).get("suppressed", []),
        *state.get("runtime", {}).get("eligible_actors", []),
        state.get("scene", {}).get("focus_character"),
    ]
    return [character_id for character_id in dedupe_character_ids(candidates) if character_id != player_character_id]


def _resolve_story_layer(profile: dict[str, Any]) -> str:
    story_layer = clean_text(profile.get("story_layer", ""))
    if story_layer in {"player", "actor", "L1"}:
        return story_layer
    agent_type = clean_text(profile.get("agent_type", "actor"), "actor")
    if agent_type == "L1":
        return agent_type
    return "actor"


def _resolve_story_character_affection(
    player_character_id: str, profile: dict[str, Any], runtime_state: dict[str, Any]
) -> float:
    try:
        base_value = float(profile.get("base_relationship", {}).get(player_character_id, 0.0) or 0.0)
    except (TypeError, ValueError):
        base_value = 0.0
    try:
        delta_value = float(runtime_state.get("relationship_delta", {}).get(player_character_id, 0.0) or 0.0)
    except (TypeError, ValueError):
        delta_value = 0.0
    return base_value + delta_value


def _resolve_story_character_life_status(profile: dict[str, Any], runtime_state: dict[str, Any]) -> str:
    for key in ("life_status", "status", "current_status"):
        value = clean_text(runtime_state.get(key))
        if value:
            return value
    for key in ("life_status", "status"):
        value = clean_text(profile.get(key))
        if value:
            return value
    return "dead" if bool(runtime_state.get("is_dead", False)) or bool(profile.get("is_dead", False)) else "alive"


def _resolve_story_character_dialogue_flags(profile: dict[str, Any], runtime_state: dict[str, Any]) -> list[Any]:
    for source in (runtime_state, profile):
        for key in ("dialogue_branch_flags", "dialogue_flags", "unlocked_dialogue_flags"):
            value = source.get(key)
            if isinstance(value, list):
                return clone_json(value)
    return []


def build_story_character_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    state = require_snapshot_value(snapshot, "state", dict)
    character_profiles = require_snapshot_value(snapshot, "character_profiles", dict)
    player_character_id = player_character_id_from_snapshot(snapshot)
    visible_actor_ids = set(dedupe_character_ids(state.get("scene", {}).get("on_stage", [])))
    runtime_characters = state.get("characters", {})
    history = state.get("history", [])
    records: list[dict[str, Any]] = []

    for actor_id in _collect_story_character_ids(snapshot):
        profile = character_profiles.get(actor_id, {})
        if _resolve_story_layer(profile) != "L1":
            continue
        runtime_state = runtime_characters.get(actor_id, {})
        history_turns = [
            int(item.get("turn", 0) or 0)
            for item in history
            if isinstance(item, dict) and clean_text(item.get("actor")) == actor_id
        ]
        records.append(
            {
                "actor_character_id": actor_id,
                "display_name": clean_text(profile.get("name"), actor_id),
                "avatar_url": clean_text(profile.get("avatar_url")) or None,
                "agent_layer": _resolve_story_layer(profile),
                "has_met": True,
                "affection_score": _resolve_story_character_affection(player_character_id, profile, runtime_state),
                "life_status": _resolve_story_character_life_status(profile, runtime_state),
                "is_on_stage": actor_id in visible_actor_ids,
                "is_active": bool(profile.get("is_active", True)),
                "is_offstage": bool(profile.get("is_offstage", False)),
                "dialogue_flags_json": _resolve_story_character_dialogue_flags(profile, runtime_state),
                "runtime_state_json": clone_json(runtime_state) if isinstance(runtime_state, dict) else {},
                "profile_snapshot_json": clone_json(profile) if isinstance(profile, dict) else {},
                "first_seen_turn": min(history_turns) if history_turns else None,
                "last_seen_turn": max(history_turns) if history_turns else None,
            }
        )
    return records


def build_actor_interaction_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    state = require_snapshot_value(snapshot, "state", dict)
    character_profiles = require_snapshot_value(snapshot, "character_profiles", dict)
    player_character_id = player_character_id_from_snapshot(snapshot)
    runtime_characters = state.get("characters", {})
    history = state.get("history", [])
    records: list[dict[str, Any]] = []

    for actor_id in _collect_story_character_ids(snapshot):
        profile = character_profiles.get(actor_id, {})
        if _resolve_story_layer(profile) != "actor":
            continue
        runtime_state = runtime_characters.get(actor_id, {})
        history_turns = [
            int(item.get("turn", 0) or 0)
            for item in history
            if isinstance(item, dict) and clean_text(item.get("actor")) == actor_id
        ]
        records.append(
            {
                "actor_character_id": actor_id,
                "display_name": clean_text(profile.get("name"), actor_id),
                "occupation": clean_text(profile.get("occupation", "")),
                "template_key": clean_text(profile.get("template_key", actor_id), actor_id),
                "favor_score": _resolve_story_character_affection(player_character_id, profile, runtime_state),
                "interaction_flags_json": _resolve_story_character_dialogue_flags(profile, runtime_state),
                "interaction_state_json": clone_json(runtime_state) if isinstance(runtime_state, dict) else {},
                "met_count": 1 if history_turns else 0,
                "last_seen_turn": max(history_turns) if history_turns else None,
                "profile_snapshot_json": clone_json(profile) if isinstance(profile, dict) else {},
            }
        )
    return records


def build_player_quest_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    state = require_snapshot_value(snapshot, "state", dict)
    plot = state.get("plot", {})
    scene = state.get("scene", {})
    scene_plan = state.get("scene_plan", {})
    director_brief = state.get("director_brief", {})

    chapter_id = clean_text(plot.get("chapter_id"), "current")
    scene_id = clean_text(plot.get("scene_id"), clean_text(scene.get("location_id"), "current"))
    records: list[dict[str, Any]] = []

    def append_record(
        *,
        quest_key: str,
        category: str,
        title: str,
        description: Any,
        sort_order: int,
        progress_json: dict[str, Any] | None = None,
        source_json: dict[str, Any] | None = None,
    ) -> None:
        description_text = clean_text(description)
        if not description_text:
            return
        records.append(
            {
                "quest_key": quest_key,
                "category": category,
                "title": clean_text(title, quest_key),
                "description": description_text,
                "status": "active",
                "sort_order": sort_order,
                "progress_json": clone_json(progress_json or {}),
                "source_json": clone_json(source_json or {}),
            }
        )

    append_record(
        quest_key=f"chapter:{chapter_id}",
        category="chapter",
        title=clean_text(plot.get("current_chapter_title"), "当前章节目标"),
        description=plot.get("chapter_goal"),
        sort_order=10,
        progress_json={
            "chapter_id": chapter_id,
            "scene_index": int(plot.get("current_scene_index", 0) or 0),
        },
        source_json={"source": "runtime_snapshot", "path": "plot.chapter_goal"},
    )
    append_record(
        quest_key=f"scene:{scene_id}",
        category="scene",
        title="当前场景目标",
        description=scene_plan.get("scene_goal"),
        sort_order=20,
        progress_json={
            "scene_id": scene_id,
            "location_id": clean_text(scene.get("location_id")),
        },
        source_json={"source": "runtime_snapshot", "path": "scene_plan.scene_goal"},
    )
    append_record(
        quest_key=f"beat:{scene_id}",
        category="beat",
        title="当前推进重点",
        description=director_brief.get("beat_goal"),
        sort_order=30,
        progress_json={
            "scene_id": scene_id,
            "beat": clean_text(scene.get("beat")),
        },
        source_json={"source": "runtime_snapshot", "path": "director_brief.beat_goal"},
    )
    append_record(
        quest_key=f"cultivation:{chapter_id}",
        category="cultivation",
        title="修行目标",
        description=plot.get("cultivation_goal"),
        sort_order=40,
        progress_json={
            "current_realm": clean_text(plot.get("current_player_realm")),
            "target_realm": clean_text(plot.get("next_chapter_realm")),
        },
        source_json={"source": "runtime_snapshot", "path": "plot.cultivation_goal"},
    )
    return records


def serialize_user(user: UserAccount) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status,
        "created_at": serialize_dt(user.created_at),
        "updated_at": serialize_dt(user.updated_at),
    }


def serialize_player(player: PlayerSlot) -> dict[str, Any]:
    return {
        "id": player.id,
        "user_id": player.user_id,
        "slot_name": player.slot_name,
        "status": player.status,
        "mode": player.mode,
        "narration_style_preset": player.narration_style_preset,
        "player_character_id": player.player_character_id,
        "current_story_node_id": player.current_story_node_id,
        "current_scene_id": player.current_scene_id,
        "current_scene_location_id": player.current_scene_location_id,
        "current_scene_index": player.current_scene_index,
        "current_scene_time_tag": player.current_scene_time_tag,
        "current_scene_beat": player.current_scene_beat,
        "inventory_json": clone_json(player.inventory_json),
        "attributes_json": clone_json(player.attributes_json),
        "player_profile_json": clone_json(player.player_profile_json),
        "scene_state_json": clone_json(player.scene_state_json),
        "story_initialized": player.story_initialized,
        "last_handoff_reason": player.last_handoff_reason,
        "latest_snapshot_id": player.latest_snapshot_id,
        "last_saved_at": serialize_dt(player.last_saved_at),
        "created_at": serialize_dt(player.created_at),
        "updated_at": serialize_dt(player.updated_at),
    }


def serialize_story_character(row: PlayerStoryCharacter) -> dict[str, Any]:
    return {
        "id": row.id,
        "player_id": row.player_id,
        "template_id": row.template_id,
        "actor_character_id": row.actor_character_id,
        "display_name": row.display_name,
        "avatar_url": row.avatar_url,
        "agent_layer": row.agent_layer,
        "has_met": row.has_met,
        "affection_score": serialize_numeric(row.affection_score),
        "life_status": row.life_status,
        "is_on_stage": row.is_on_stage,
        "is_active": row.is_active,
        "is_offstage": row.is_offstage,
        "dialogue_flags_json": clone_json(row.dialogue_flags_json),
        "runtime_state_json": clone_json(row.runtime_state_json),
        "profile_snapshot_json": clone_json(row.profile_snapshot_json),
        "first_seen_turn": row.first_seen_turn,
        "last_seen_turn": row.last_seen_turn,
        "created_at": serialize_dt(row.created_at),
        "updated_at": serialize_dt(row.updated_at),
    }


def serialize_actor_interaction(row: PlayerActorInteraction) -> dict[str, Any]:
    return {
        "player_id": row.player_id,
        "template_id": row.template_id,
        "favor_score": serialize_numeric(row.favor_score),
        "interaction_flags_json": clone_json(row.interaction_flags_json),
        "interaction_state_json": clone_json(row.interaction_state_json),
        "met_count": row.met_count,
        "last_seen_turn": row.last_seen_turn,
        "created_at": serialize_dt(row.created_at),
        "updated_at": serialize_dt(row.updated_at),
    }


def serialize_snapshot(row: PlayerSaveSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "player_id": row.player_id,
        "save_kind": row.save_kind,
        "save_label": row.save_label,
        "snapshot_version": row.snapshot_version,
        "created_at": serialize_dt(row.created_at),
    }


def serialize_player_quest(row: PlayerQuest) -> dict[str, Any]:
    return {
        "id": row.id,
        "player_id": row.player_id,
        "quest_key": row.quest_key,
        "category": row.category,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "sort_order": row.sort_order,
        "progress_json": clone_json(row.progress_json),
        "source_json": clone_json(row.source_json),
        "started_at": serialize_dt(row.started_at),
        "completed_at": serialize_dt(row.completed_at),
        "created_at": serialize_dt(row.created_at),
        "updated_at": serialize_dt(row.updated_at),
    }


def serialize_template(template: StoryCharacterTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "template_key": template.template_key,
        "display_name": template.display_name,
        "occupation": template.occupation,
        "template_kind": template.template_kind,
        "default_avatar_url": template.default_avatar_url,
        "default_profile_json": clone_json(template.default_profile_json),
        "default_runtime_json": clone_json(template.default_runtime_json),
        "default_dialogue_flags_json": clone_json(template.default_dialogue_flags_json),
        "starter_enabled": template.starter_enabled,
        "created_at": serialize_dt(template.created_at),
        "updated_at": serialize_dt(template.updated_at),
    }
