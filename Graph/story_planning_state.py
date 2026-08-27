from __future__ import annotations

from typing import Any

from Cultivation import build_chapter_transition_requirement
from GameState import GameState
from StoryStateUtils import outline_index, story_outline_entries
from WorldSetting.runtime import transition_requirement


def _resolve_story_foundation_source(plot: dict[str, object]) -> str:
    premise_source = str(plot.get("story_premise_source", "") or "").strip()
    outline_source = str(plot.get("story_outline_source", "") or "").strip()
    return premise_source if premise_source and premise_source == outline_source else ""


def _remaining_outline_chapters(state: GameState) -> int:
    story_outline = story_outline_entries(state)
    if not story_outline:
        return 0
    current_chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    current_index = outline_index(story_outline, current_chapter_id)
    if current_index < 0:
        current_index = int(state["plot"].get("current_chapter_index", 0) or 0)
    return max(0, len(story_outline) - max(current_index, 0))


def _has_story_premise(state: GameState) -> bool:
    plot = state["plot"]
    return bool(
        str(plot.get("story_premise", "") or "").strip()
        and str(plot.get("exploration_drive", "") or "").strip()
    )


def _has_story_outline_brief(state: GameState) -> bool:
    outline = list(state["plot"].get("story_outline", []))
    if not outline:
        return False
    first = outline[0]
    return bool(
        str(first.get("chapter_id", "") or "").strip()
        and str(first.get("title", "") or "").strip()
        and str(first.get("main_goal", "") or "").strip()
        and str(first.get("summary", "") or "").strip()
    )


def _has_valid_chapter_expansion(state: GameState) -> bool:
    plot = state["plot"]
    chapter_id = str(plot.get("chapter_id", "") or "").strip()
    return bool(
        str(plot.get("chapter_goal", "") or "").strip()
        and str(plot.get("current_chapter_title", "") or "").strip()
        and str(plot.get("current_chapter_overview", "") or "").strip()
        and list(plot.get("current_chapter_hooks", []))
        and str(plot.get("active_outline_chapter_id", "") or "").strip() == chapter_id
    )


def _has_scene_candidates(state: GameState) -> bool:
    return bool(list(state["runtime"].get("scene_candidates", []))) and bool(
        str(state["scene_plan"].get("scene_goal", "") or "").strip()
    )


def _apply_story_premise(
    state: GameState,
    premise: dict[str, object],
    *,
    source: str,
) -> GameState:
    next_plot = {
        **state["plot"],
        "story_premise": str(premise.get("story_premise", "") or "").strip(),
        "exploration_drive": str(premise.get("exploration_drive", "") or "").strip(),
        "story_premise_source": source,
    }
    next_plot["story_foundation_source"] = _resolve_story_foundation_source(next_plot)
    return {
        **state,
        "plot": next_plot,
    }


def _apply_story_outline_brief(
    state: GameState,
    story_outline: list[dict[str, object]],
    *,
    source: str,
) -> GameState:
    incoming_outline = [
        {
            "chapter_id": str(item.get("chapter_id", "") or "").strip(),
            "title": str(item.get("title", "") or "").strip(),
            "main_goal": str(item.get("main_goal", "") or "").strip(),
            "summary": str(item.get("summary", "") or "").strip(),
            "exploration_hooks": [str(hook).strip() for hook in item.get("exploration_hooks", []) if str(hook).strip()],
            "key_locations": [str(location).strip() for location in item.get("key_locations", []) if str(location).strip()],
            "realm_stage": str(item.get("realm_stage", "") or "").strip(),
            "next_realm": str(item.get("next_realm", "") or "").strip(),
        }
        for item in story_outline
        if isinstance(item, dict)
    ]
    existing_outline = [dict(item) for item in state["plot"].get("story_outline", []) if isinstance(item, dict)]
    merged_outline: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for existing in existing_outline:
        chapter_id = str(existing.get("chapter_id", "") or "").strip()
        if not chapter_id:
            continue
        replacement = next(
            (
                incoming
                for incoming in incoming_outline
                if str(incoming.get("chapter_id", "") or "").strip() == chapter_id
            ),
            None,
        )
        merged_outline.append(
            existing
            if replacement is None
            else {
                "chapter_id": chapter_id,
                "title": str(replacement.get("title", "") or "").strip() or str(existing.get("title", "") or "").strip(),
                "main_goal": str(replacement.get("main_goal", "") or "").strip()
                or str(existing.get("main_goal", "") or "").strip(),
                "summary": str(replacement.get("summary", "") or "").strip() or str(existing.get("summary", "") or "").strip(),
                "exploration_hooks": list(existing.get("exploration_hooks", [])) or list(replacement.get("exploration_hooks", [])),
                "key_locations": list(existing.get("key_locations", [])) or list(replacement.get("key_locations", [])),
                "realm_stage": str(replacement.get("realm_stage", "") or "").strip()
                or str(existing.get("realm_stage", "") or "").strip(),
                "next_realm": str(replacement.get("next_realm", "") or "").strip()
                or str(existing.get("next_realm", "") or "").strip(),
            }
        )
        seen_ids.add(chapter_id)

    for incoming in incoming_outline:
        chapter_id = str(incoming.get("chapter_id", "") or "").strip()
        if chapter_id and chapter_id not in seen_ids:
            merged_outline.append(incoming)
            seen_ids.add(chapter_id)

    current_chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    current_index = outline_index(merged_outline, current_chapter_id)
    if merged_outline and current_index < 0:
        current_index = 0
        current_chapter_id = str(merged_outline[0].get("chapter_id", "") or "").strip()
    current_outline_entry = dict(merged_outline[current_index]) if merged_outline and 0 <= current_index < len(merged_outline) else {}
    next_plot = {
        **state["plot"],
        "chapter_id": current_chapter_id or str(state["plot"].get("chapter_id", "") or "").strip(),
        "story_outline": merged_outline,
        "story_outline_source": source,
        "current_chapter_index": max(current_index, 0),
        "current_chapter_title": str(state["plot"].get("current_chapter_title", "") or "").strip()
        or str(current_outline_entry.get("title", "") or "").strip(),
        "chapter_goal": str(state["plot"].get("chapter_goal", "") or "").strip()
        or str(current_outline_entry.get("main_goal", "") or "").strip(),
        "current_chapter_overview": str(state["plot"].get("current_chapter_overview", "") or "").strip()
        or str(current_outline_entry.get("summary", "") or "").strip(),
        "current_chapter_realm": str(current_outline_entry.get("realm_stage", "") or "").strip()
        or str(state["plot"].get("current_chapter_realm", "") or "").strip(),
        "next_chapter_realm": str(current_outline_entry.get("next_realm", "") or "").strip()
        or str(state["plot"].get("next_chapter_realm", "") or "").strip(),
    }
    setting = next_plot.get("world_setting")
    next_plot["chapter_transition_requirement"] = (
        transition_requirement(setting, next_plot.get("current_chapter_realm", ""), next_plot.get("next_chapter_realm", ""))
        if isinstance(setting, dict) else build_chapter_transition_requirement(next_plot.get("current_chapter_realm", ""), next_plot.get("next_chapter_realm", ""))
    )
    next_plot["story_foundation_source"] = _resolve_story_foundation_source(next_plot)
    return {
        **state,
        "plot": next_plot,
    }


def _apply_chapter_expansion(
    state: GameState,
    chapter_expansion: dict[str, object],
    *,
    source: str,
) -> GameState:
    chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    updated_outline = []
    for item in state["plot"].get("story_outline", []):
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if str(normalized.get("chapter_id", "") or "").strip() == chapter_id:
            normalized["title"] = str(chapter_expansion.get("chapter_title", "") or "").strip() or str(
                normalized.get("title", "") or ""
            ).strip()
            normalized["main_goal"] = str(chapter_expansion.get("chapter_goal", "") or "").strip() or str(
                normalized.get("main_goal", "") or ""
            ).strip()
            normalized["summary"] = str(chapter_expansion.get("chapter_overview", "") or "").strip() or str(
                normalized.get("summary", "") or ""
            ).strip()
            normalized["exploration_hooks"] = [
                str(hook).strip() for hook in chapter_expansion.get("exploration_hooks", []) if str(hook).strip()
            ]
            normalized["key_locations"] = [
                str(location).strip() for location in chapter_expansion.get("key_locations", []) if str(location).strip()
            ]
        updated_outline.append(normalized)

    return {
        **state,
        "plot": {
            **state["plot"],
            "chapter_goal": str(chapter_expansion.get("chapter_goal", "") or "").strip(),
            "current_chapter_title": str(chapter_expansion.get("chapter_title", "") or "").strip(),
            "current_chapter_overview": str(chapter_expansion.get("chapter_overview", "") or "").strip(),
            "current_chapter_hooks": [
                str(hook).strip() for hook in chapter_expansion.get("exploration_hooks", []) if str(hook).strip()
            ],
            "active_outline_chapter_id": chapter_id,
            "chapter_expansion_source": source,
            "chapter_focus_source": source,
            "story_outline": updated_outline,
            "chapter_transition_requirement": (
                transition_requirement(state["plot"]["world_setting"], state["plot"].get("current_chapter_realm", ""), state["plot"].get("next_chapter_realm", ""))
                if isinstance(state["plot"].get("world_setting"), dict)
                else build_chapter_transition_requirement(state["plot"].get("current_chapter_realm", ""), state["plot"].get("next_chapter_realm", ""))
            ),
        },
    }


def _select_scene_candidate(state: GameState, candidates: list[dict[str, object]]) -> dict[str, object] | None:
    if not candidates:
        return None
    current_location = str(state["scene"].get("location_id", "") or "").strip()
    for candidate in candidates:
        if str(candidate.get("location_id", "") or "").strip() == current_location:
            return candidate
    return dict(candidates[0])


def _apply_scene_candidates(
    state: GameState,
    candidates: list[dict[str, object]],
    *,
    source: str,
    formatter: Any,
) -> GameState:
    selected = _select_scene_candidate(state, candidates)
    next_scene = dict(state["scene"])
    if selected is not None:
        next_scene["location_id"] = str(
            selected.get("location_id", "") or state["scene"].get("location_id", "")
        ).strip()
        next_scene["beat"] = str(selected.get("beat", "") or state["scene"].get("beat", "")).strip()
    return {
        **state,
        "plot": {
            **state["plot"],
            "scene_candidates_source": source,
        },
        "scene": next_scene,
        "scene_plan": formatter.scene_candidate_to_plan(selected),
        "runtime": {
            **state["runtime"],
            "scene_candidates": candidates,
        },
    }


def apply_selected_template(state: GameState, template_id: object) -> GameState:
    """建游戏/大章开始时设定当前情节模板。template_id<=0（或非法）清为 0=无模板。

    不可变更新：返回新 state，不原地改。软指导链路读 plot.selected_template_id。
    """
    try:
        tid = int(template_id)
    except (TypeError, ValueError):
        tid = 0
    if tid <= 0:
        tid = 0
    return {
        **state,
        "plot": {
            **state["plot"],
            "selected_template_id": tid,
        },
    }
