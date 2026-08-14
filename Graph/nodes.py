from __future__ import annotations

from Graph.component_resolution import (
    resolve_actor_create_agent as _resolve_actor_create_agent,
    resolve_playwright_agent as _resolve_playwright_agent,
)
from Graph.story_cast_nodes import _ensure_story_cast, _seed_scene_cast_for_current_chapter
from Graph.story_planning import (
    _ensure_chapter_expansion,
    _ensure_scene_candidates,
    _ensure_story_outline_brief,
    _ensure_story_premise,
    _revise_story_outline_brief_after_cast,
)
from GameState import GameState
from PlayerWriter import PlaywrightAgent
from Actor.ActorCreateAgent import ActorCreateAgent


# GraphDependencies 已抽到 Graph.dependencies(打破 nodes<->beat_nodes 循环)。
# 此处 re-export 以保持 `from Graph.nodes import GraphDependencies` 兼容。
from Graph.dependencies import GraphDependencies

# 对话/beat 节点已搬到 Graph.dialogue_nodes(继续打破 nodes<->beat_nodes 循环)。
# 此处 re-export 以保持既有 `from Graph.nodes import actor_node` 等导入路径兼容。
from Graph.dialogue_nodes import (
    CULTIVATION_SIGNAL_MARKERS,
    actor_node,
    beat_resolution_node,
    contextual_progression_node,
    cultivation_progress_node,
    director_node,
    history_commit_node,
    refresh_history_node,
    scene_end_node,
    scheduler_node,
    _build_cultivation_result_text,
    _looks_like_cultivation_turn,
    _polish_nonverbal_action,
    _resolve_agent_for_actor,
    _sync_plot_cultivation_state,
)


_STORY_PLANNING_OUTLINE_STEPS = ("outline",)
_STORY_PLANNING_CAST_STEPS = (*_STORY_PLANNING_OUTLINE_STEPS, "story_cast")
_STORY_PLANNING_REVISION_STEPS = (*_STORY_PLANNING_CAST_STEPS, "outline_revision")
_CHAPTER_PLANNING_STEPS = (*_STORY_PLANNING_REVISION_STEPS, "scene_cast", "chapter_expansion")


def _apply_story_planning_step(
    state: GameState,
    deps: GraphDependencies,
    *,
    step: str,
    playwright_agent: PlaywrightAgent | None,
    actor_create_agent: ActorCreateAgent | None,
) -> GameState:
    if step == "outline":
        return _ensure_story_outline_brief(
            state=state,
            deps=deps,
            playwright_agent=playwright_agent,
        )
    if step == "story_cast":
        return _ensure_story_cast(
            state=state,
            deps=deps,
            actor_create_agent=actor_create_agent,
        )
    if step == "outline_revision":
        return _revise_story_outline_brief_after_cast(
            state=state,
            deps=deps,
            playwright_agent=playwright_agent,
        )
    if step == "scene_cast":
        return _seed_scene_cast_for_current_chapter(state, deps)
    if step == "chapter_expansion":
        return _ensure_chapter_expansion(
            state=state,
            deps=deps,
            playwright_agent=playwright_agent,
        )
    raise RuntimeError(f"Unknown story planning step: {step}")


def _prepare_story_planning_node(
    state: GameState,
    deps: GraphDependencies,
    *steps: str,
) -> GameState:
    playwright_agent = _resolve_playwright_agent(deps)
    actor_create_agent = _resolve_actor_create_agent(deps)
    current = _ensure_story_premise(
        state=_sync_plot_cultivation_state(state, deps),
        deps=deps,
        playwright_agent=playwright_agent,
    )
    for step in steps:
        current = _apply_story_planning_step(
            current,
            deps,
            step=step,
            playwright_agent=playwright_agent,
            actor_create_agent=actor_create_agent,
        )
    return current


def story_premise_node(state: GameState, deps: GraphDependencies) -> GameState:
    return _prepare_story_planning_node(state, deps)


def story_outline_brief_node(state: GameState, deps: GraphDependencies) -> GameState:
    return _prepare_story_planning_node(state, deps, *_STORY_PLANNING_OUTLINE_STEPS)


def story_cast_construction_node(state: GameState, deps: GraphDependencies) -> GameState:
    return _prepare_story_planning_node(state, deps, *_STORY_PLANNING_CAST_STEPS)


def story_outline_revision_node(state: GameState, deps: GraphDependencies) -> GameState:
    return _prepare_story_planning_node(state, deps, *_STORY_PLANNING_REVISION_STEPS)


def chapter_expansion_node(state: GameState, deps: GraphDependencies) -> GameState:
    return _prepare_story_planning_node(state, deps, *_CHAPTER_PLANNING_STEPS)

def scene_candidates_node(state: GameState, deps: GraphDependencies) -> GameState:
    state = _prepare_story_planning_node(state, deps, *_CHAPTER_PLANNING_STEPS)
    return _ensure_scene_candidates(
        state=state,
        deps=deps,
        playwright_agent=_resolve_playwright_agent(deps),
    )

