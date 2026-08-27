from __future__ import annotations

from Cultivation import build_chapter_transition_requirement
from GameState import GameState
from History.GameMemory import empty_memory_state
from WorldSetting.runtime import transition_requirement


def _build_transition_scene(
    state: GameState, location_id: str, time_tag: str, beat: str, tension: float, focus_character: str | None, on_stage: list[str]
) -> dict[str, object]:
    return {
        "location_id": location_id or str(state["scene"].get("location_id", "") or "").strip(),
        "time_tag": time_tag,
        "beat": beat,
        "tension": tension,
        "focus_character": focus_character,
        "on_stage": on_stage,
        "allow_interrupt": True,
        "suppressed": [],
    }


def build_chapter_transition_payload(
    state: GameState,
    *,
    next_chapter_id: str,
    next_index: int,
    next_title: str,
    next_chapter_realm: str,
    following_realm: str,
    next_location: str,
    default_on_stage: list[str],
    next_focus: str | None,
    turn_reset: dict[str, object],
) -> dict[str, object]:
    reset_memory = empty_memory_state()
    reset_memory["last_compressed_turn"] = int(state["runtime"].get("turn_index", 0) or 0)
    return {
        **state,
        "plot": {
            **state["plot"],
            "chapter_id": next_chapter_id,
            "scene_id": f"{next_chapter_id}-opening",
            "current_scene_index": 0,
            "chapter_goal": "",
            "current_chapter_hooks": [],
            "current_chapter_title": "",
            "current_chapter_overview": "",
            "active_outline_chapter_id": "",
            "chapter_expansion_source": "",
            "chapter_focus_source": "",
            "scene_candidates_source": "",
            "current_chapter_index": next_index,
            "current_chapter_realm": next_chapter_realm,
            "next_chapter_realm": following_realm,
            "chapter_transition_requirement": (
                transition_requirement(state["plot"]["world_setting"], next_chapter_realm, following_realm)
                if isinstance(state["plot"].get("world_setting"), dict)
                else build_chapter_transition_requirement(next_chapter_realm, following_realm)
            ),
        },
        "scene": _build_transition_scene(
            state, next_location, f"chapter-{next_index + 1}", f"进入{next_title}" if next_title else "进入下一章", 0.34, next_focus, default_on_stage
        ),
        **turn_reset,
        "memory": reset_memory,
    }


def build_scene_transition_payload(
    state: GameState,
    *,
    chapter_id: str,
    next_scene_index: int,
    next_location: str,
    next_tension: float,
    default_on_stage: list[str],
    next_focus: str | None,
    turn_reset: dict[str, object],
) -> dict[str, object]:
    plot = state["plot"]
    return {
        **state,
        "plot": {
            **plot,
            "scene_id": f"{chapter_id}-scene-{next_scene_index + 1}",
            "current_scene_index": next_scene_index,
            "scene_candidates_source": "",
        },
        "scene": _build_transition_scene(
            state, next_location, f"scene-{next_scene_index + 1}", f"转入第{next_scene_index + 1}场：{plot.get('current_chapter_title', '本章新局')}", next_tension, next_focus, default_on_stage
        ),
        **turn_reset,
    }
