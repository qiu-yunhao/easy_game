from __future__ import annotations

from typing import TYPE_CHECKING

from GameState import GameState
from PlayerWriter.StoryPlanningHeuristics import (
    build_heuristic_chapter_expansion,
    build_heuristic_scene_candidates,
    build_heuristic_story_outline_brief,
    build_heuristic_story_premise,
)
from Graph.story_planning_state import (
    _apply_chapter_expansion,
    _apply_scene_candidates,
    _apply_story_outline_brief,
    _apply_story_premise,
    _has_scene_candidates,
    _has_story_outline_brief,
    _has_story_premise,
    _has_valid_chapter_expansion,
    _remaining_outline_chapters,
)
from StoryStateUtils import (
    clean_text as _clean_text,
    current_outline_entry,
)

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies
    from PlayerWriter import PlaywrightAgent


OUTLINE_LOOKAHEAD_CHAPTERS = 3
OUTLINE_EXTENSION_BATCH_SIZE = 2
FIXED_MAINLINE_MARKERS = (
    "问心台",
    "青岚宗",
    "韩照",
    "灵髓",
    "旧事线索",
    "旧案",
    "执法堂",
    "审问",
    "追查",
)
OPEN_WORLD_PROGRESS_MARKERS = (
    "长生",
    "修行",
    "境界",
    "求道",
    "longevity",
    "immortal",
    "cultivation",
    "realm",
)


def _looks_fixed_mainline_text(value: object) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return False
    return any(marker.lower() in text for marker in FIXED_MAINLINE_MARKERS)


def _has_open_world_progress_signal(value: object) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return False
    return any(marker.lower() in text for marker in OPEN_WORLD_PROGRESS_MARKERS)


def _needs_open_world_premise_reset(premise: dict[str, object]) -> bool:
    story_premise = _clean_text(premise.get("story_premise", ""))
    exploration_drive = _clean_text(premise.get("exploration_drive", ""))
    combined = "\n".join([story_premise, exploration_drive]).strip()
    if not story_premise or not exploration_drive:
        return True
    if _looks_fixed_mainline_text(combined):
        return True
    return not _has_open_world_progress_signal(combined)


def _needs_open_world_outline_reset(outline: list[dict[str, object]]) -> bool:
    if not outline:
        return True
    for chapter in outline:
        title = _clean_text(chapter.get("title", ""))
        goal = _clean_text(chapter.get("main_goal", ""))
        summary = _clean_text(chapter.get("summary", ""))
        combined = "\n".join([title, goal, summary]).strip()
        if not title or not goal or not summary:
            return True
        if _looks_fixed_mainline_text(combined):
            return True
    return False


def _needs_open_world_chapter_reset(chapter_expansion: dict[str, object]) -> bool:
    chapter_title = _clean_text(chapter_expansion.get("chapter_title", ""))
    chapter_goal = _clean_text(chapter_expansion.get("chapter_goal", ""))
    chapter_overview = _clean_text(chapter_expansion.get("chapter_overview", ""))
    exploration_hooks = [
        _clean_text(item)
        for item in chapter_expansion.get("exploration_hooks", [])
        if _clean_text(item)
    ]
    key_locations = [
        _clean_text(item)
        for item in chapter_expansion.get("key_locations", [])
        if _clean_text(item)
    ]
    combined = "\n".join(
        [
            chapter_title,
            chapter_goal,
            chapter_overview,
            *exploration_hooks,
            *key_locations,
        ]
    ).strip()
    if not chapter_title or not chapter_goal or not chapter_overview:
        return True
    if not exploration_hooks or not key_locations:
        return True
    return _looks_fixed_mainline_text(combined)


def _needs_open_world_scene_candidates_reset(candidates: list[dict[str, object]]) -> bool:
    if not candidates:
        return True
    for candidate in candidates:
        candidate_id = _clean_text(candidate.get("candidate_id", ""))
        location_id = _clean_text(candidate.get("location_id", ""))
        beat = _clean_text(candidate.get("beat", ""))
        scene_goal = _clean_text(candidate.get("scene_goal", ""))
        exit_condition = _clean_text(candidate.get("exit_condition", ""))
        combined = "\n".join([candidate_id, location_id, beat, scene_goal, exit_condition]).strip()
        if not candidate_id or not location_id or not beat or not scene_goal or not exit_condition:
            return True
        if _looks_fixed_mainline_text(combined):
            return True
    return False


def _ensure_story_premise(
    state: GameState,
    deps: "GraphDependencies",
    playwright_agent: "PlaywrightAgent | None",
) -> GameState:
    if _has_story_premise(state):
        return state

    source = "playwright_agent" if playwright_agent is not None else "heuristic"
    if playwright_agent is not None:
        try:
            premise = playwright_agent.plan_story_premise(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
            )
        except RuntimeError:
            premise = build_heuristic_story_premise(
                state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
            )
            source = "heuristic"
    else:
        premise = build_heuristic_story_premise(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
    if _needs_open_world_premise_reset(premise):
        premise = build_heuristic_story_premise(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
        source = "heuristic"
    next_state = _apply_story_premise(state, premise, source=source)
    if not _has_story_premise(next_state):
        raise RuntimeError("Story setup could not produce a valid story premise.")
    return next_state


def _ensure_story_outline_brief(
    state: GameState,
    deps: "GraphDependencies",
    playwright_agent: "PlaywrightAgent | None",
    *,
    force_refresh: bool = False,
    source_suffix: str = "",
) -> GameState:
    remaining = _remaining_outline_chapters(state)
    needs_extension = remaining < OUTLINE_LOOKAHEAD_CHAPTERS
    if _has_story_outline_brief(state) and not needs_extension and not force_refresh:
        return state

    source_base = "playwright_agent" if playwright_agent is not None else "heuristic"
    source = f"{source_base}{source_suffix}"
    desired_chapter_count = (
        len(list(state["plot"].get("story_outline", [])))
        if force_refresh and list(state["plot"].get("story_outline", []))
        else (
            OUTLINE_LOOKAHEAD_CHAPTERS
            if not state["plot"].get("story_outline", [])
            else OUTLINE_EXTENSION_BATCH_SIZE
        )
    )
    if playwright_agent is not None:
        try:
            outline = playwright_agent.plan_story_outline_brief(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                desired_chapter_count=desired_chapter_count,
            )
        except RuntimeError:
            outline = build_heuristic_story_outline_brief(
                state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                desired_chapter_count=desired_chapter_count,
            )
            source = f"heuristic{source_suffix}"
    else:
        outline = build_heuristic_story_outline_brief(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
            desired_chapter_count=desired_chapter_count,
        )
    if _needs_open_world_outline_reset(outline):
        outline = build_heuristic_story_outline_brief(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
            desired_chapter_count=desired_chapter_count,
        )
        source = f"heuristic{source_suffix}"
    next_state = _apply_story_outline_brief(state, outline, source=source)
    if (
        not _has_story_outline_brief(next_state)
        or _remaining_outline_chapters(next_state) < min(OUTLINE_LOOKAHEAD_CHAPTERS, desired_chapter_count)
    ):
        raise RuntimeError("Story setup could not produce a valid story outline.")
    return next_state


def _revise_story_outline_brief_after_cast(
    state: GameState,
    deps: "GraphDependencies",
    playwright_agent: "PlaywrightAgent | None",
) -> GameState:
    if not _has_story_outline_brief(state):
        return state
    if str(state["plot"].get("story_outline_source", "") or "").strip().endswith("_cast_revised"):
        return state
    if len(deps.character_profiles) <= 1:
        return state

    return _ensure_story_outline_brief(
        state=state,
        deps=deps,
        playwright_agent=playwright_agent,
        force_refresh=True,
        source_suffix="_cast_revised",
    )


def _ensure_chapter_expansion(
    state: GameState,
    deps: "GraphDependencies",
    playwright_agent: "PlaywrightAgent | None",
) -> GameState:
    if _has_valid_chapter_expansion(state):
        return state

    outline_entry = current_outline_entry(state)
    fallback_title = str((outline_entry or {}).get("title", "") or "").strip()
    fallback_goal = str((outline_entry or {}).get("main_goal", "") or "").strip()
    fallback_overview = str((outline_entry or {}).get("summary", "") or "").strip()

    source = "playwright_agent" if playwright_agent is not None else "heuristic"
    if playwright_agent is not None:
        try:
            chapter_expansion = playwright_agent.expand_current_chapter(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                template_service=deps.story_template_service,
            )
        except RuntimeError:
            chapter_expansion = build_heuristic_chapter_expansion(
                state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
            )
            source = "heuristic"
    else:
        chapter_expansion = build_heuristic_chapter_expansion(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
    if _needs_open_world_chapter_reset(chapter_expansion):
        chapter_expansion = build_heuristic_chapter_expansion(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
        source = "heuristic"

    if not deps.agent_first and not str(chapter_expansion.get("chapter_title", "") or "").strip():
        chapter_expansion["chapter_title"] = fallback_title
    if not deps.agent_first and not str(chapter_expansion.get("chapter_goal", "") or "").strip():
        chapter_expansion["chapter_goal"] = fallback_goal
    if not deps.agent_first and not str(chapter_expansion.get("chapter_overview", "") or "").strip():
        chapter_expansion["chapter_overview"] = fallback_overview

    next_state = _apply_chapter_expansion(state, chapter_expansion, source=source)
    if not _has_valid_chapter_expansion(next_state):
        raise RuntimeError("Story setup could not produce a valid chapter expansion.")
    return next_state


def _ensure_scene_candidates(
    state: GameState,
    deps: "GraphDependencies",
    playwright_agent: "PlaywrightAgent | None",
) -> GameState:
    if _has_scene_candidates(state):
        return state

    source = "playwright_agent" if playwright_agent is not None else "heuristic"
    if playwright_agent is not None:
        try:
            candidates = playwright_agent.generate_scene_candidates(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                template_service=deps.story_template_service,
            )
        except RuntimeError:
            candidates = build_heuristic_scene_candidates(
                state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
            )
            source = "heuristic"
    else:
        candidates = build_heuristic_scene_candidates(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
    if _needs_open_world_scene_candidates_reset(candidates):
        candidates = build_heuristic_scene_candidates(
            state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
        )
        source = "heuristic"
    formatter = getattr(playwright_agent, "formatter", None) or deps.component_factory.config.playwright_formatter_builder()
    next_state = _apply_scene_candidates(
        state,
        candidates,
        source=source,
        formatter=formatter,
    )
    if not _has_scene_candidates(next_state):
        raise RuntimeError("Story setup could not produce valid scene candidates.")
    return next_state
