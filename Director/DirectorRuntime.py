from __future__ import annotations

import re
from typing import Any, Mapping

from Director.DirectorBrief import (
    DirectorBrief,
    StageActions,
    empty_director_brief,
    empty_stage_actions,
)
from GameState import GameState, SceneState


CONFLICT_MARKERS = (
    "conflict",
    "tension_peak",
    "冲突",
    "对峙",
    "对抗",
    "争吵",
    "争执",
    "战斗",
    "敌对",
    "威胁",
    "背叛",
    "破裂",
    "剑拔弩张",
    "反目",
)
TRANSITION_POLLUTION_MARKERS = (
    "Heuristic scene-end",
    "response_pressure",
    "must_happen",
    "scene_end",
    "recent_history",
)
TRANSITION_DUMP_PATTERN = re.compile(
    r"\b\d+:[A-Za-z_][A-Za-z0-9_]*:(?:speak|action|event|interrupt|silence|observe)\b"
)
SYSTEM_HANDOFF_MARKERS = (
    "请选择",
    "请决定",
    "选择你的行动",
    "下一步行动",
    "下一步做什么",
)


def clamp_float(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, float(value)))


def _clean_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _contains_conflict_marker(value: Any) -> bool:
    text = _clean_text(value).lower()
    return bool(text) and any(marker in text for marker in CONFLICT_MARKERS)


def _sentence_count(value: str) -> int:
    return len([chunk for chunk in re.split(r"[。！？!?]+", _clean_text(value)) if chunk.strip()])


def _looks_like_internal_dump(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    if TRANSITION_DUMP_PATTERN.search(text):
        return True
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in TRANSITION_POLLUTION_MARKERS)


def _looks_like_system_handoff(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    return any(marker in text for marker in SYSTEM_HANDOFF_MARKERS)


def _display_name(
    actor_id: str | None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
    fallback: str,
) -> str:
    if actor_id is None:
        return fallback
    profile = (character_profiles or {}).get(str(actor_id), {})
    return _clean_text(profile.get("name"), fallback)


def _secondary_focus_name(
    state: GameState,
    *,
    focus_character: str | None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    for actor_id in state["scene"].get("on_stage", []):
        resolved_id = str(actor_id or "").strip()
        if not resolved_id or resolved_id == focus_character:
            continue
        return _display_name(resolved_id, character_profiles, "另一人")
    return "对面的人"


def _requires_conflict_triptych(
    state: GameState,
    brief: DirectorBrief,
) -> bool:
    if any(
        _contains_conflict_marker(value)
        for value in (
            state["scene"].get("beat", ""),
            state["scene_plan"].get("scene_goal", ""),
            brief.get("beat", ""),
            brief.get("beat_goal", ""),
            " ".join(state["scene_plan"].get("dramatic_curve", [])),
            " ".join(brief.get("notes", [])),
        )
    ):
        return True

    if float(brief.get("tension_target", 0.0) or 0.0) >= 0.62:
        return True
    if float(state["scene"].get("tension", 0.0) or 0.0) >= 0.68:
        return True

    director_memory = state["memory"].get("director_memory", {})
    if str(director_memory.get("beat_suggestion", "") or "").strip() == "escalate_conflict":
        return True
    if (
        director_memory.get("active_conflicts")
        and str(director_memory.get("tension_trend", "") or "").strip() in {"rising", "high"}
    ):
        return True

    resolved_act = state["runtime"].get("resolved_act") or {}
    relationship_update = resolved_act.get("relationship_update", {})
    try:
        if any(float(value) <= -0.5 for value in relationship_update.values()):
            return True
    except (TypeError, ValueError):
        return False
    return False


def _build_conflict_lead_in_text(
    state: GameState,
    *,
    focus_character: str | None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    location = _clean_text(state["scene"].get("location_id"), "眼前这片地方")
    focus_name = _display_name(focus_character, character_profiles, "对面的那人")
    other_name = _secondary_focus_name(
        state,
        focus_character=focus_character,
        character_profiles=character_profiles,
    )
    return (
        f"{location}里的气流像是被谁一点点按住，原本浮动的声息也跟着低了下去。"
        f"{focus_name}没有立刻开口，只是将视线稳稳压在{other_name}身上，肩背与指节都透出难以忽视的绷紧。"
        "那份无声积蓄的压迫感缓慢堆高，谁都能感觉到，接下来不会只是寻常一句应答。"
    )


def _build_conflict_wrap_up_text(
    state: GameState,
    *,
    focus_character: str | None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    focus_name = _display_name(focus_character, character_profiles, "那人")
    return (
        "正面相撞的力道虽已暂时落下，场中的紧绷却没有立刻散尽。"
        f"{focus_name}收住了表面的声势，神色与肩线间却仍压着未曾完全退去的余劲。"
        "空气像是慢了一拍才重新流动起来，而那道冲突留下的裂纹，依旧横在众人的呼吸之间。"
    )


def _ensure_conflict_triptych(
    state: GameState,
    brief: DirectorBrief,
    *,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
) -> DirectorBrief:
    if not _requires_conflict_triptych(state, brief):
        return brief

    focus_character = brief.get("focus_character") or state["scene"].get("focus_character")
    next_brief = dict(brief)
    lead_in_text = _clean_text(brief.get("lead_in_text"))
    wrap_up_text = _clean_text(brief.get("wrap_up_text"))
    if _sentence_count(lead_in_text) < 2 or _looks_like_internal_dump(lead_in_text):
        next_brief["lead_in_text"] = _build_conflict_lead_in_text(
            state,
            focus_character=focus_character,
            character_profiles=character_profiles,
        )
    if (
        _sentence_count(wrap_up_text) < 2
        or _looks_like_internal_dump(wrap_up_text)
        or _looks_like_system_handoff(wrap_up_text)
    ):
        next_brief["wrap_up_text"] = _build_conflict_wrap_up_text(
            state,
            focus_character=focus_character,
            character_profiles=character_profiles,
        )
    return next_brief


def _normalize_actor_id_sequence(
    value: Any,
    *,
    allowed_actor_ids: set[str] | None,
) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        actor_id = str(item).strip()
        if not actor_id:
            continue
        if allowed_actor_ids is not None and actor_id not in allowed_actor_ids:
            continue
        if actor_id not in normalized:
            normalized.append(actor_id)
    return normalized


def normalize_stage_actions(
    stage_actions: Mapping[str, Any] | None,
    *,
    allowed_actor_ids: set[str] | None = None,
) -> StageActions:
    normalized = empty_stage_actions()
    if not stage_actions:
        return normalized

    for field in normalized:
        normalized[field] = _normalize_actor_id_sequence(
            stage_actions.get(field, []),
            allowed_actor_ids=allowed_actor_ids,
        )
    return normalized


def _resolve_actor_tier(
    actor_id: str | None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    if actor_id is None:
        return "actor"
    profile = (character_profiles or {}).get(str(actor_id), {})
    agent_type = str(profile.get("agent_type", "actor")).strip()
    if agent_type in {"L1", "actor"}:
        return agent_type
    return "actor"


def _prioritize_active_actors(
    actor_ids: list[str],
    *,
    focus_character: str | None,
    tension_target: float,
    character_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    unique_actor_ids: list[str] = []
    for actor_id in actor_ids:
        resolved_id = str(actor_id).strip()
        if resolved_id and resolved_id not in unique_actor_ids:
            unique_actor_ids.append(resolved_id)

    if not unique_actor_ids:
        return []

    focus_block: list[str] = []
    if focus_character in unique_actor_ids:
        focus_block.append(str(focus_character))

    remaining_actor_ids = [cid for cid in unique_actor_ids if cid not in focus_block]
    grouped: dict[str, list[str]] = {
        "actor": [],
        "L1": [],
    }
    for actor_id in remaining_actor_ids:
        grouped[_resolve_actor_tier(actor_id, character_profiles)].append(actor_id)

    focus_tier = _resolve_actor_tier(focus_character, character_profiles)
    l1_pressure_active = bool(focus_tier == "L1" or (grouped["L1"] and tension_target >= 0.55))

    if l1_pressure_active:
        tier_order = ("L1", "actor")
    else:
        tier_order = ("actor", "L1")

    prioritized = list(focus_block)
    for tier in tier_order:
        prioritized.extend(grouped[tier])
    return prioritized


def _normalize_response_groups(
    raw_groups: Any,
    who_should_respond: list[str],
) -> list[list[str]]:
    allowed = set(who_should_respond)
    serial = [[cid] for cid in who_should_respond]
    if not isinstance(raw_groups, list):
        return serial

    groups: list[list[str]] = []
    seen: set[str] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            return serial
        group: list[str] = []
        for item in raw_group:
            cid = str(item).strip()
            if not cid or cid not in allowed or cid in seen:
                continue
            seen.add(cid)
            group.append(cid)
        if group:
            groups.append(group)

    if seen != allowed:
        return serial
    return groups


def _split_interrupt_actor(
    groups: list[list[str]],
    *,
    focus_character: str | None,
    allow_interrupt: bool,
) -> list[list[str]]:
    if not allow_interrupt or not focus_character:
        return groups
    focus = str(focus_character).strip()
    if not focus:
        return groups
    remaining: list[list[str]] = []
    found = False
    for group in groups:
        stripped = [cid for cid in group if cid != focus]
        if focus in group:
            found = True
        if stripped:
            remaining.append(stripped)
    if not found:
        return groups
    return [[focus], *remaining]


def normalize_director_brief(
    brief: Mapping[str, Any] | None,
    current_on_stage: list[str],
    *,
    allowed_actor_ids: list[str] | None = None,
    character_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    player_character_id: str | None = None,
) -> DirectorBrief:
    normalized = empty_director_brief()
    if not brief:
        return normalized

    allowed_actor_set = {
        str(actor_id).strip()
        for actor_id in (allowed_actor_ids or [])
        if str(actor_id).strip()
    }
    allowed_actor_set.update(str(actor_id).strip() for actor_id in current_on_stage if str(actor_id).strip())

    stage_actions = normalize_stage_actions(
        brief.get("stage_actions"),
        allowed_actor_ids=allowed_actor_set or None,
    )
    future_on_stage = [cid for cid in current_on_stage if cid not in stage_actions["leave"]]
    for cid in stage_actions["enter"]:
        if cid not in future_on_stage:
            future_on_stage.append(cid)

    normalized["beat"] = str(brief.get("beat", "")).strip()
    normalized["beat_goal"] = str(brief.get("beat_goal", "")).strip()

    focus_character = brief.get("focus_character")
    normalized["focus_character"] = (
        str(focus_character) if focus_character in future_on_stage else None
    )
    normalized["tension_target"] = clamp_float(brief.get("tension_target", 0.0))
    normalized["allow_interrupt"] = bool(brief.get("allow_interrupt", False))
    player_id = str(player_character_id or "").strip() or None
    non_player_on_stage = [
        cid for cid in future_on_stage if player_id is None or cid != player_id
    ]
    requested_respond = [
        str(cid)
        for cid in brief.get("who_should_respond", [])
        if cid in future_on_stage
    ]
    # The player just acted. If the director only queued the player (or queued
    # nobody) while other characters are on stage, they never react and the beat
    # loop re-queues the player against themselves. Fall back to the on-stage
    # NPCs so the scene actually answers. A mixed queue that the director chose
    # deliberately (e.g. scripted turn-taking) is left intact.
    only_player_requested = (
        player_id is not None
        and requested_respond
        and all(cid == player_id for cid in requested_respond)
    )
    if only_player_requested and non_player_on_stage:
        requested_respond = []
    normalized["who_should_respond"] = requested_respond
    if not normalized["who_should_respond"]:
        fallback_pool = non_player_on_stage if non_player_on_stage else future_on_stage
        normalized["who_should_respond"] = _prioritize_active_actors(
            fallback_pool,
            focus_character=normalized["focus_character"],
            tension_target=normalized["tension_target"],
            character_profiles=character_profiles,
        )
    normalized["lead_in_text"] = str(brief.get("lead_in_text", "") or "").strip()
    normalized["wrap_up_text"] = str(brief.get("wrap_up_text", "") or "").strip()
    normalized["stage_actions"] = stage_actions
    normalized["notes"] = [str(note) for note in brief.get("notes", []) if str(note).strip()]
    normalized["response_groups"] = _split_interrupt_actor(
        _normalize_response_groups(
            brief.get("response_groups"),
            normalized["who_should_respond"],
        ),
        focus_character=normalized["focus_character"],
        allow_interrupt=normalized["allow_interrupt"],
    )
    return normalized


def apply_stage_actions_to_scene(
    scene: SceneState,
    stage_actions: StageActions,
) -> SceneState:
    current_on_stage = list(scene["on_stage"])
    current_suppressed = list(scene.get("suppressed", []))

    new_on_stage = [cid for cid in current_on_stage if cid not in set(stage_actions["leave"])]
    for cid in stage_actions["enter"]:
        if cid not in new_on_stage:
            new_on_stage.append(cid)

    new_suppressed = [cid for cid in current_suppressed if cid in new_on_stage]
    for cid in stage_actions["suppress"]:
        if cid in new_on_stage and cid not in new_suppressed:
            new_suppressed.append(cid)

    new_suppressed = [cid for cid in new_suppressed if cid not in set(stage_actions["unsuppress"])]
    focus_character = scene.get("focus_character")
    if focus_character not in new_on_stage:
        focus_character = None

    return {
        **scene,
        "on_stage": new_on_stage,
        "suppressed": new_suppressed,
        "focus_character": focus_character,
    }


def apply_director_brief(
    state: GameState,
    brief: DirectorBrief,
    character_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> GameState:
    allowed_actor_ids = [
        str(actor_id).strip()
        for actor_id in state["characters"].keys()
        if str(actor_id).strip()
    ]
    normalized = normalize_director_brief(
        brief,
        state["scene"]["on_stage"],
        allowed_actor_ids=allowed_actor_ids,
        character_profiles=character_profiles,
        player_character_id=state["player"].get("controlled_character"),
    )
    normalized = _ensure_conflict_triptych(
        state,
        normalized,
        character_profiles=character_profiles,
    )
    updated_scene = apply_stage_actions_to_scene(state["scene"], normalized["stage_actions"])

    focus_character = normalized["focus_character"]
    if focus_character not in updated_scene["on_stage"]:
        focus_character = updated_scene.get("focus_character")

    updated_scene = {
        **updated_scene,
        "beat": normalized["beat"] or updated_scene["beat"],
        "tension": clamp_float(normalized["tension_target"]),
        "allow_interrupt": normalized["allow_interrupt"],
        "focus_character": focus_character,
    }
    active_on_stage = [
        cid
        for cid in updated_scene["on_stage"]
        if cid not in set(updated_scene.get("suppressed", []))
    ]
    prioritized_active_on_stage = _prioritize_active_actors(
        active_on_stage,
        focus_character=updated_scene.get("focus_character"),
        tension_target=updated_scene["tension"],
        character_profiles=character_profiles,
    )
    pending_beat_actors = [
        cid for cid in normalized["who_should_respond"] if cid in prioritized_active_on_stage
    ]
    pending_response_groups = [
        filtered
        for filtered in (
            [cid for cid in group if cid in prioritized_active_on_stage]
            for group in normalized["response_groups"]
        )
        if filtered
    ]
    if not pending_response_groups and pending_beat_actors:
        pending_response_groups = [[cid] for cid in pending_beat_actors]
    fallback_turns = 0 if pending_beat_actors else int(bool(prioritized_active_on_stage))

    return {
        **state,
        "scene": updated_scene,
        "director_brief": normalized,
        "runtime": {
            **state["runtime"],
            "eligible_actors": prioritized_active_on_stage,
            "pending_beat_actors": pending_beat_actors,
            "pending_response_groups": pending_response_groups,
            "beat_fallback_turns_remaining": fallback_turns,
            "next_act": None,
            "resolved_act": None,
            "scene_end_evaluation": None,
        },
    }
