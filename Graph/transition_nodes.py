from __future__ import annotations

from typing import TYPE_CHECKING

from Graph.component_resolution import resolve_actor_create_agent, resolve_playwright_agent
from Graph.contextual_scene_handoffs import build_contextual_scene_handoff
from Graph.story_cast_nodes import _ensure_story_cast, _merge_story_cast, _resolve_default_on_stage
from Graph.story_planning import _ensure_story_outline_brief
from Graph.transition_payloads import build_chapter_transition_payload, build_scene_transition_payload
from SceneEnd.SceneEndEvaluation import empty_scene_end_evaluation
from ScenePlan import empty_scene_plan
from StoryStateUtils import current_outline_entry, outline_index, story_outline_entries
from Director.DirectorBrief import empty_director_brief
from GameState import GameState

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def _next_outline_entry(state: GameState) -> tuple[int, dict[str, object]] | None:
    story_outline = story_outline_entries(state)
    if not story_outline:
        return None
    current_chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    current_index = outline_index(story_outline, current_chapter_id)
    if current_index < 0:
        current_index = int(state["plot"].get("current_chapter_index", 0) or 0)
    next_index = current_index + 1
    return (next_index, dict(story_outline[next_index])) if 0 <= next_index < len(story_outline) else None


def _dedupe_text(items: list[object]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _collect_current_chapter_history(state: GameState) -> list[dict[str, object]]:
    completed_chapters = list(state["plot"].get("completed_chapters", []))
    start_turn = int(completed_chapters[-1].get("completed_turn", 0) or 0) if completed_chapters else 0
    end_turn = int(state["runtime"].get("turn_index", 0) or 0)
    return [
        dict(item)
        for item in state["history"]
        if int(item.get("turn", 0) or 0) > start_turn and int(item.get("turn", 0) or 0) <= end_turn
    ]


def _build_chapter_archive(state: GameState) -> dict[str, object]:
    plot = state["plot"]
    scene_memory = state["memory"]["scene_memory"]
    playwright_memory = state["memory"]["playwright_memory"]
    scene_end = state["runtime"].get("scene_end_evaluation") or {}
    chapter_history = _collect_current_chapter_history(state)
    recent_events = _dedupe_text([item.get("content", "") for item in chapter_history[-3:]])
    return {
        "chapter_id": str(plot.get("chapter_id", "") or "").strip(),
        "title": str(plot.get("current_chapter_title", "") or "").strip(),
        "goal": str(plot.get("chapter_goal", "") or "").strip(),
        "overview": str(plot.get("current_chapter_overview", "") or "").strip(),
        "summary": " ".join(
            _dedupe_text(
                [
                    plot.get("current_chapter_overview", ""),
                    playwright_memory.get("scene_summary", ""),
                    scene_memory.get("summary", ""),
                    scene_end.get("reason", ""),
                ]
            )[:3]
        ).strip()
        or str(plot.get("chapter_goal", "") or "").strip(),
        "key_events": _dedupe_text(
            list(scene_memory.get("key_events", []))
            + list(playwright_memory.get("key_events", []))
            + recent_events
        ),
        "revealed_facts": _dedupe_text(
            list(scene_memory.get("revealed_facts", [])) + list(playwright_memory.get("revealed_facts", []))
        ),
        "open_loops": _dedupe_text(
            list(scene_memory.get("open_loops", []))
            + list(playwright_memory.get("open_loops", []))
            + list(scene_memory.get("active_conflicts", []))
        ),
        "completed_turn": int(state["runtime"].get("turn_index", 0) or 0),
    }


def _resolve_scene_focus_character(state: GameState, eligible_actors: list[str]) -> str | None:
    player_actor = state["player"].get("controlled_character")
    return player_actor if player_actor in eligible_actors else (eligible_actors[0] if eligible_actors else None)


def _resolve_transition_stage_defaults(
    state: GameState,
    deps: "GraphDependencies",
    *,
    chapter_id: str,
) -> tuple[list[str], str | None]:
    default_on_stage = _resolve_default_on_stage(state, deps, chapter_id=chapter_id)
    return default_on_stage, _resolve_scene_focus_character(state, default_on_stage)


def _build_turn_reset_payload(
    state: GameState,
    *,
    eligible_actors: list[str],
    pending_intro_kind: str = "",
) -> dict[str, object]:
    return {
        "runtime": {
            **state["runtime"],
            "last_actor": None,
            "last_mode": None,
            "eligible_actors": eligible_actors,
            "pending_intro_kind": pending_intro_kind,
            "pending_beat_actors": [],
            "beat_fallback_turns_remaining": 0,
            "narration_queue": [],
            "scene_candidates": [],
            "next_act": None,
            "resolved_act": None,
            "scene_end_evaluation": empty_scene_end_evaluation(),
            "scene_finished": False,
            "chapter_finished": False,
        },
        "scene_plan": empty_scene_plan(),
        "director_brief": empty_director_brief(),
        "player": {
            **state["player"],
            "last_input": "",
            "last_parsed_act": None,
        },
    }


def _resolve_next_scene_location(state: GameState, deps: "GraphDependencies") -> str:
    outline_entry = current_outline_entry(state) or {}
    key_locations = [str(location).strip() for location in outline_entry.get("key_locations", []) if str(location).strip()]
    next_scene_index = int(state["plot"].get("current_scene_index", 0) or 0) + 1
    if next_scene_index < len(key_locations):
        return key_locations[next_scene_index]
    current_location = str(state["scene"].get("location_id", "") or "").strip()
    for location in key_locations:
        if location != current_location:
            return location
    return str(deps.scene_config.get("default_location_id", current_location) or current_location).strip()


def _build_scene_transition(
    state: GameState,
    *,
    chapter_id: str,
    next_scene_index: int,
    next_location: str,
    next_tension: float,
    default_on_stage: list[str],
    next_focus: str | None,
    pending_intro_kind: str = "scene",
) -> dict[str, object]:
    return build_scene_transition_payload(
        state,
        chapter_id=chapter_id,
        next_scene_index=next_scene_index,
        next_location=next_location,
        next_tension=next_tension,
        default_on_stage=default_on_stage,
        next_focus=next_focus,
        turn_reset=_build_turn_reset_payload(
            state,
            eligible_actors=default_on_stage,
            pending_intro_kind=pending_intro_kind,
        ),
    )


def _build_contextual_scene_transition(
    state: GameState,
    deps: "GraphDependencies",
    *,
    chapter_id: str,
    next_scene_index: int,
    contextual_handoff: dict[str, object],
) -> GameState:
    state = _merge_story_cast(state, deps, contextual_handoff["supplemental_profiles"])
    payload = _build_scene_transition(
        state,
        chapter_id=chapter_id,
        next_scene_index=next_scene_index,
        next_location=str(contextual_handoff["next_location"]),
        next_tension=float(contextual_handoff["next_tension"]),
        default_on_stage=list(contextual_handoff["default_on_stage"]),
        next_focus=contextual_handoff["next_focus"],
        pending_intro_kind="" if contextual_handoff["skip_transition_intro"] else "scene",
    )
    return {
        **payload,
        "plot": {
            **payload["plot"],
            "scene_candidates_source": "contextual_handoff",
        },
        "scene": {
            **payload["scene"],
            "beat": contextual_handoff["scene_candidate"]["beat"],
        },
        "scene_plan": contextual_handoff["scene_plan"],
        "director_brief": empty_director_brief(),
        "runtime": {
            **payload["runtime"],
            "scene_candidates": [contextual_handoff["scene_candidate"]],
            "pending_beat_actors": [],
            "beat_fallback_turns_remaining": 0,
        },
    }


def _resolve_contextual_scene_handoff(
    state: GameState,
    deps: "GraphDependencies",
) -> dict[str, object] | None:
    actor_create_agent = deps.actor_create_agent
    if actor_create_agent is None and deps.agent_first:
        try:
            actor_create_agent = resolve_actor_create_agent(deps)
        except RuntimeError:
            actor_create_agent = None
    return build_contextual_scene_handoff(
        state,
        scene_config=deps.scene_config,
        character_profiles=deps.character_profiles,
        actor_create_agent=actor_create_agent,
    )


def _build_default_scene_transition(
    state: GameState,
    deps: "GraphDependencies",
    *,
    chapter_id: str,
    next_scene_index: int,
) -> GameState:
    default_on_stage, next_focus = _resolve_transition_stage_defaults(state, deps, chapter_id=chapter_id)
    return _build_scene_transition(
        state,
        chapter_id=chapter_id,
        next_scene_index=next_scene_index,
        next_location=_resolve_next_scene_location(state, deps),
        next_tension=max(0.28, min(0.74, float(state["scene"].get("tension", 0.42)) - 0.08)),
        default_on_stage=default_on_stage,
        next_focus=next_focus,
    )


def chapter_archive_node(state: GameState, deps: "GraphDependencies") -> GameState:
    if not state["runtime"].get("chapter_finished", False):
        return state
    chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    if not chapter_id:
        return state
    completed_chapters = list(state["plot"].get("completed_chapters", []))
    if completed_chapters and str(completed_chapters[-1].get("chapter_id", "") or "").strip() == chapter_id:
        return state
    archive = _build_chapter_archive(state)
    return {
        **state,
        "plot": {
            **state["plot"],
            "completed_chapters": [*completed_chapters, archive],
        },
    }


def chapter_transition_node(state: GameState, deps: "GraphDependencies") -> GameState:
    if not state["runtime"].get("chapter_finished", False):
        return state
    next_outline = _next_outline_entry(state)
    if next_outline is None:
        state = _ensure_story_outline_brief(
            state=state,
            deps=deps,
            playwright_agent=resolve_playwright_agent(deps),
        )
        next_outline = _next_outline_entry(state)
    if next_outline is None:
        return state

    state = _ensure_story_cast(state=state, deps=deps, actor_create_agent=resolve_actor_create_agent(deps))
    next_index, outline_entry = next_outline
    next_chapter_id = str(outline_entry.get("chapter_id", "") or "").strip()
    if not next_chapter_id:
        return state

    next_location = str(
        (
            list(outline_entry.get("key_locations", []))[0]
            if list(outline_entry.get("key_locations", []))
            else deps.scene_config.get("default_location_id", state["scene"].get("location_id", ""))
        )
        or ""
    ).strip()
    default_on_stage, next_focus = _resolve_transition_stage_defaults(state, deps, chapter_id=next_chapter_id)
    return build_chapter_transition_payload(
        state,
        next_chapter_id=next_chapter_id,
        next_index=next_index,
        next_title=str(outline_entry.get("title", "") or "").strip(),
        next_chapter_realm=str(outline_entry.get("realm_stage", "") or "").strip(),
        following_realm=str(outline_entry.get("next_realm", "") or "").strip(),
        next_location=next_location,
        default_on_stage=default_on_stage,
        next_focus=next_focus,
        turn_reset=_build_turn_reset_payload(
            state,
            eligible_actors=default_on_stage,
            pending_intro_kind="chapter",
        ),
    )


def scene_transition_node(state: GameState, deps: "GraphDependencies") -> GameState:
    if not state["runtime"].get("scene_finished", False) or state["runtime"].get("chapter_finished", False):
        return state
    chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    next_scene_index = int(state["plot"].get("current_scene_index", 0) or 0) + 1
    contextual_handoff = _resolve_contextual_scene_handoff(state, deps)
    if contextual_handoff is not None:
        return _build_contextual_scene_transition(
            state,
            deps,
            chapter_id=chapter_id,
            next_scene_index=next_scene_index,
            contextual_handoff=contextual_handoff,
        )
    return _build_default_scene_transition(
        state,
        deps,
        chapter_id=chapter_id,
        next_scene_index=next_scene_index,
    )
