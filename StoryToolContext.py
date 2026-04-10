from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from CharacterRosterTools import CharacterRosterToolRuntime, resolve_character_roster_snapshot
from StoryStateUtils import clean_str_list, clean_text
from ToolSkillRegistry import StoryToolTask, build_story_tool_prompt_payload, select_story_tool_skill_ids

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile
    from GameState import GameState


def build_scene_context_tool_snapshot(
    game_state: "GameState",
    character_profiles: Mapping[str, "CharacterProfile"] | Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    on_stage_ids = [clean_text(actor_id) for actor_id in game_state["scene"].get("on_stage", []) if clean_text(actor_id)]
    on_stage_characters: list[dict[str, Any]] = []
    for character_id in on_stage_ids:
        profile = character_profiles.get(character_id, {})
        runtime = game_state["characters"].get(character_id, {})
        on_stage_characters.append(
            {
                "character_id": character_id,
                "name": clean_text(profile.get("name", ""), character_id),
                "agent_type": clean_text(profile.get("agent_type", "actor"), "actor"),
                "story_role": clean_text(profile.get("story_role", "")),
                "persona": clean_str_list(profile.get("persona", [])),
                "intent": clean_text(runtime.get("intent", "")),
                "known_facts": clean_str_list(runtime.get("known_facts", []))[:5],
                "last_turn": int(runtime.get("last_turn", -1) or -1),
            }
        )
    return {
        "tool_name": "query_scene_context",
        "source": "game_state",
        "scene": {
            "location_id": clean_text(game_state["scene"].get("location_id", "")),
            "time_tag": clean_text(game_state["scene"].get("time_tag", "")),
            "beat": clean_text(game_state["scene"].get("beat", "")),
            "tension": float(game_state["scene"].get("tension", 0.0) or 0.0),
            "focus_character": clean_text(game_state["scene"].get("focus_character", "")),
            "on_stage": on_stage_ids,
            "suppressed": clean_str_list(game_state["scene"].get("suppressed", [])),
            "allow_interrupt": bool(game_state["scene"].get("allow_interrupt", False)),
        },
        "plot": {
            "chapter_id": clean_text(game_state["plot"].get("chapter_id", "")),
            "scene_id": clean_text(game_state["plot"].get("scene_id", "")),
            "chapter_goal": clean_text(game_state["plot"].get("chapter_goal", "")),
            "current_chapter_title": clean_text(game_state["plot"].get("current_chapter_title", "")),
            "current_chapter_overview": clean_text(game_state["plot"].get("current_chapter_overview", "")),
        },
        "scene_plan": dict(game_state.get("scene_plan", {})),
        "director_brief": dict(game_state.get("director_brief", {})),
        "runtime": {
            "turn_index": int(game_state["runtime"].get("turn_index", 0) or 0),
            "eligible_actors": clean_str_list(game_state["runtime"].get("eligible_actors", [])),
            "pending_intro_kind": clean_text(game_state["runtime"].get("pending_intro_kind", "")),
        },
        "on_stage_characters": on_stage_characters,
    }


def build_player_status_tool_snapshot(
    game_state: "GameState",
    character_profiles: Mapping[str, "CharacterProfile"] | Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    controlled_character = clean_text(game_state["player"].get("controlled_character", ""))
    player_id = controlled_character or "player"
    player_profile = character_profiles.get(player_id, {})
    return {
        "tool_name": "query_player_status",
        "source": "game_state",
        "player_profile": {
            "character_id": player_id,
            "name": clean_text(player_profile.get("name", ""), player_id),
        },
        "attributes": {
            "realm": clean_text(player_profile.get("realm", "")),
            "spiritual_root": clean_text(player_profile.get("spiritual_root", "")),
            "main_technique": clean_text(player_profile.get("main_technique", "")),
            "current_chapter_realm": clean_text(game_state["plot"].get("current_chapter_realm", "")),
            "next_chapter_realm": clean_text(game_state["plot"].get("next_chapter_realm", "")),
            "chapter_transition_requirement": clean_text(game_state["plot"].get("chapter_transition_requirement", "")),
        },
    }


def build_story_memory_tool_snapshot(game_state: "GameState") -> dict[str, Any]:
    memory = game_state["memory"]
    return {
        "tool_name": "query_story_memory",
        "source": "memory_state",
        "scene_memory": {
            "summary": clean_text(memory["scene_memory"].get("summary", "")),
            "key_events": clean_str_list(memory["scene_memory"].get("key_events", [])),
            "revealed_facts": clean_str_list(memory["scene_memory"].get("revealed_facts", [])),
            "active_conflicts": clean_str_list(memory["scene_memory"].get("active_conflicts", [])),
            "open_loops": clean_str_list(memory["scene_memory"].get("open_loops", [])),
            "recent_speakers": clean_str_list(memory["scene_memory"].get("recent_speakers", [])),
            "tension_trend": clean_text(memory["scene_memory"].get("tension_trend", "")),
            "focus_suggestion": clean_text(memory["scene_memory"].get("focus_suggestion", "")),
        },
        "playwright_memory": {
            "scene_summary": clean_text(memory["playwright_memory"].get("scene_summary", "")),
            "key_events": clean_str_list(memory["playwright_memory"].get("key_events", [])),
            "revealed_facts": clean_str_list(memory["playwright_memory"].get("revealed_facts", [])),
            "active_conflicts": clean_str_list(memory["playwright_memory"].get("active_conflicts", [])),
            "open_loops": clean_str_list(memory["playwright_memory"].get("open_loops", [])),
        },
        "director_memory": {
            "scene_summary": clean_text(memory["director_memory"].get("scene_summary", "")),
            "recent_stage_dynamics": clean_str_list(memory["director_memory"].get("recent_stage_dynamics", [])),
            "current_focus": clean_text(memory["director_memory"].get("current_focus", "")),
            "tension_trend": clean_text(memory["director_memory"].get("tension_trend", "")),
            "who_needs_response": clean_str_list(memory["director_memory"].get("who_needs_response", [])),
            "active_conflicts": clean_str_list(memory["director_memory"].get("active_conflicts", [])),
            "beat_suggestion": clean_text(memory["director_memory"].get("beat_suggestion", "")),
        },
        "recent_history": list(game_state.get("history", [])[-6:]),
    }


def build_story_tool_prompt_context(
    *,
    task: StoryToolTask,
    game_state: "GameState",
    character_profiles: Mapping[str, "CharacterProfile"] | Mapping[str, Mapping[str, Any]],
    character_roster_snapshot: Mapping[str, Any] | None = None,
    character_roster_tool_runtime: CharacterRosterToolRuntime | None = None,
    resolved_snapshots: dict[str, Any] | None = None,
    cast_size: int = 0,
    supporting_cast_count: int = 0,
    current_chapter_cast_count: int = 0,
    on_stage_count: int = 0,
    available_stage_candidate_count: int = 0,
    outline_exists: bool = False,
    history_count: int = 0,
    completed_chapter_count: int = 0,
) -> dict[str, Any]:
    skill_ids = select_story_tool_skill_ids(
        task=task,
        character_roster_snapshot=character_roster_snapshot,
        cast_size=cast_size,
        supporting_cast_count=supporting_cast_count,
        current_chapter_cast_count=current_chapter_cast_count,
        on_stage_count=on_stage_count,
        available_stage_candidate_count=available_stage_candidate_count,
        outline_exists=outline_exists,
        history_count=history_count,
        completed_chapter_count=completed_chapter_count,
    )
    payload = build_story_tool_prompt_payload(
        task=task,
        character_roster_snapshot=character_roster_snapshot,
        cast_size=cast_size,
        supporting_cast_count=supporting_cast_count,
        current_chapter_cast_count=current_chapter_cast_count,
        on_stage_count=on_stage_count,
        available_stage_candidate_count=available_stage_candidate_count,
        outline_exists=outline_exists,
        history_count=history_count,
        completed_chapter_count=completed_chapter_count,
    )
    resolved_roster_snapshot = character_roster_snapshot
    if "character_roster_skill" in skill_ids and resolved_roster_snapshot is None:
        resolved_roster_snapshot = resolve_character_roster_snapshot(
            character_roster_tool_runtime,
            character_profiles=character_profiles,
        )
    if "scene_skill" in skill_ids:
        payload["scene_context_snapshot"] = build_scene_context_tool_snapshot(game_state, character_profiles)
        if resolved_snapshots is not None:
            resolved_snapshots["scene_context_snapshot"] = payload["scene_context_snapshot"]
    if "character_status_skill" in skill_ids:
        payload["character_status_snapshot"] = build_player_status_tool_snapshot(game_state, character_profiles)
        if resolved_snapshots is not None:
            resolved_snapshots["character_status_snapshot"] = payload["character_status_snapshot"]
    if "memory_skill" in skill_ids:
        payload["story_memory_snapshot"] = build_story_memory_tool_snapshot(game_state)
        if resolved_snapshots is not None:
            resolved_snapshots["story_memory_snapshot"] = payload["story_memory_snapshot"]
    if "character_roster_skill" in skill_ids:
        payload["character_roster_snapshot"] = dict(resolved_roster_snapshot or {})
        if resolved_snapshots is not None:
            resolved_snapshots["character_roster_snapshot"] = payload["character_roster_snapshot"]
    return payload
