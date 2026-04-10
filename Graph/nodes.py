from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from Actor import ActorAgent, apply_resolved_act
from Actor.ActorFormatter import compose_resolved_act_content
from CharacterProfile import CharacterProfile
from ComponentFactory import ComponentFactory
from Graph.actor_paths import resolve_npc_turn_state, resolve_player_turn_state
from Graph.beat_subgraph import (
    build_beat_execution_subgraph,
    is_player_turn,
    run_beat_loop,
)
from Graph.component_resolution import (
    resolve_actor_create_agent as _resolve_actor_create_agent,
    resolve_component as _resolve_component,
    resolve_playwright_agent as _resolve_playwright_agent,
    resolve_stylistic_polish_agent as _resolve_stylistic_polish_agent,
)
from Graph.narration_nodes import (
    _append_narration_event,
    director_lead_in_node,
    director_wrap_up_node,
    narration_subgraph_node,
)
from Graph.contextual_scene_handoffs import apply_contextual_scene_progression
from Graph.story_cast_nodes import _ensure_story_cast, _seed_scene_cast_for_current_chapter
from Graph.story_planning import (
    _ensure_chapter_expansion,
    _ensure_scene_candidates,
    _ensure_story_outline_brief,
    _ensure_story_premise,
    _revise_story_outline_brief_after_cast,
)
from StoryStateUtils import (
    clean_text as _clean_text,
    current_outline_entry,
    resolve_player_character_id,
)
from Cultivation import (
    build_chapter_transition_requirement,
    detect_breakthrough_realm,
    has_reached_realm,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
)
from Director import DirectorAgent, apply_director_brief
from GameState import GameState
from GameplayTuning import GameplayTuning
from History import HistoryManager
from Narrator.NarratorAgent import NarratorAgent
from PlayerControl import (
    PlayerInterface,
    SemanticParserAgent,
)
from PlayerWriter import PlaywrightAgent
from SceneConfig import SceneConfig
from SceneEnd import apply_scene_end_evaluation
from SceneEnd.SceneEndHeuristics import SceneEndPolicy
from Scheduler import apply_scheduler_decision
from Scheduler.SchedulerPolicy import SchedulerPolicy
from StylisticPolish import StylisticPolishAgent, deterministic_nonverbal_cleanup
from actor_create_agent import ActorCreateAgent

if TYPE_CHECKING:
    from History.HistorySummarizerAgent import HistorySummarizerAgent
    from PlayerControl.PlayerCommandTools import PlayerCommandToolRuntime


@dataclass(slots=True)
class GraphDependencies:
    scene_config: SceneConfig
    character_profiles: dict[str, CharacterProfile]
    playwright_agent: PlaywrightAgent | None = None
    actor_create_agent: ActorCreateAgent | None = None
    director_agent: DirectorAgent | None = None
    actor_agent: ActorAgent | None = None
    l2_actor_agent: ActorAgent | None = None
    l1_actor_agent: ActorAgent | None = None
    narrator_agent: NarratorAgent | None = None
    semantic_parser_agent: SemanticParserAgent | None = None
    player_command_tools: "PlayerCommandToolRuntime | None" = None
    stylistic_polish_agent: StylisticPolishAgent | None = None
    history_summarizer_agent: "HistorySummarizerAgent | None" = None
    history_manager: HistoryManager | None = None
    scheduler_policy: SchedulerPolicy | None = None
    scene_end_policy: SceneEndPolicy | None = None
    player_interface: PlayerInterface | None = None
    gameplay_tuning: GameplayTuning = field(default_factory=GameplayTuning)
    component_factory: ComponentFactory = field(default_factory=ComponentFactory)
    agent_first: bool = False
    actor_create_signature: str = ""
    beat_execution_subgraph: Callable[[GameState], GameState] | None = None


CULTIVATION_SIGNAL_MARKERS = (
    "\u4fee\u70bc",
    "\u6253\u5750",
    "\u5410\u7eb3",
    "\u8fd0\u529f",
    "\u8c03\u606f",
    "\u95ed\u5173",
    "\u51b2\u5173",
    "\u70bc\u5316",
    "\u7075\u6c14",
    "\u5468\u5929",
    "\u4e39\u836f",
    "\u670d\u4e0b",
    "\u836f\u529b",
)
_STORY_PLANNING_OUTLINE_STEPS = ("outline",)
_STORY_PLANNING_CAST_STEPS = (*_STORY_PLANNING_OUTLINE_STEPS, "story_cast")
_STORY_PLANNING_REVISION_STEPS = (*_STORY_PLANNING_CAST_STEPS, "outline_revision")
_CHAPTER_PLANNING_STEPS = (*_STORY_PLANNING_REVISION_STEPS, "scene_cast", "chapter_expansion")


def refresh_history_node(state: GameState, deps: GraphDependencies) -> GameState:
    if deps.history_manager is None:
        return state
    if not deps.history_manager.should_refresh(state):
        return state
    return {
        **state,
        "memory": deps.history_manager.build_memory(state),
    }

def _looks_like_cultivation_turn(candidate_text: str) -> bool:
    lowered = candidate_text.lower()
    return any(marker in candidate_text for marker in CULTIVATION_SIGNAL_MARKERS) or any(
        marker in lowered for marker in ("cultivat", "meditat", "breathwork")
    )


def _build_cultivation_result_text(
    state: GameState,
    deps: GraphDependencies,
    *,
    player_actor: str,
    breakthrough_realm: str = "",
) -> str:
    player_name = str(
        deps.character_profiles.get(player_actor, {}).get("name", "") or player_actor
    ).strip()
    latest_input = " ".join(
        [
            str(state["player"].get("last_input", "") or "").strip(),
            str((state["runtime"].get("resolved_act") or {}).get("content", "") or "").strip(),
        ]
    )
    used_pill = any(marker in latest_input for marker in ("\u4e39", "\u836f", "\u836f\u529b"))
    if breakthrough_realm:
        return (
            f"{player_name}\u5728\u6d1e\u5e9c\u4e2d\u8fd0\u8f6c\u5468\u5929\uff0c"
            f"\u4f53\u5185\u7075\u606f\u7ec8\u4e8e\u7531\u6563\u800c\u805a\uff0c"
            f"\u4e00\u4e3e\u8e0f\u5165{breakthrough_realm}\u3002"
        )
    if used_pill:
        return (
            f"{player_name}\u76d8\u5750\u8c03\u606f\u4e4b\u95f4\uff0c"
            "\u836f\u529b\u6cbf\u7ecf\u8109\u7f13\u7f13\u5316\u5f00\uff0c"
            "\u6c14\u606f\u6bd4\u5148\u524d\u66f4\u51dd\u7ec3\u4e86\u51e0\u5206\uff0c"
            "\u53ea\u662f\u8ddd\u7834\u5883\u8fd8\u5dee\u6700\u540e\u4e00\u7ebf\u6c34\u78e8\u529f\u592b\u3002"
        )
    return (
        f"{player_name}\u6536\u655b\u5fc3\u795e\uff0c\u5728\u6d1e\u5e9c\u4e2d\u7f13\u7f13\u5410\u7eb3\uff0c"
        "\u4f53\u5185\u7075\u606f\u867d\u672a\u7acb\u523b\u7834\u5173\uff0c"
        "\u5374\u5df2\u5728\u4e00\u6b21\u6b21\u5faa\u73af\u4e4b\u95f4\u6e10\u6e10\u7a33\u56fa\u3002"
    )

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


def _sync_plot_cultivation_state(state: GameState, deps: GraphDependencies) -> GameState:
    player_actor = resolve_player_character_id(state, deps.character_profiles)
    player_profile = deps.character_profiles.get(player_actor, {})
    current_player_realm = normalize_realm_text(player_profile.get("realm", ""), "炼气一层")
    current_outline = current_outline_entry(state) or {}
    current_chapter_realm = _clean_text(
        current_outline.get("realm_stage"),
    ) or _clean_text(state["plot"].get("current_chapter_realm", "")) or normalize_major_realm(
        current_player_realm
    )
    next_chapter_realm = _clean_text(
        current_outline.get("next_realm"),
    ) or _clean_text(state["plot"].get("next_chapter_realm", "")) or next_major_realm(
        current_chapter_realm
    )
    next_plot = {
        **state["plot"],
        "cultivation_goal": str(state["plot"].get("cultivation_goal", "") or "").strip() or "修仙求长生",
        "current_player_realm": current_player_realm,
        "current_chapter_realm": current_chapter_realm,
        "next_chapter_realm": next_chapter_realm,
        "chapter_transition_requirement": build_chapter_transition_requirement(
            current_chapter_realm,
            next_chapter_realm,
        ),
    }
    return {
        **state,
        "plot": next_plot,
    }


def cultivation_progress_node(state: GameState, deps: GraphDependencies) -> GameState:
    state = _sync_plot_cultivation_state(state, deps)
    resolved_act = state["runtime"].get("resolved_act") or {}
    if not resolved_act:
        return state

    player_actor = resolve_player_character_id(state, deps.character_profiles)
    if str(resolved_act.get("actor", "") or "").strip() != player_actor:
        return state

    target_realm = _clean_text(state["plot"].get("next_chapter_realm", ""))
    if not target_realm:
        return state

    candidate_text = " ".join(
        [
            str(resolved_act.get("content", "") or "").strip(),
            str(state["player"].get("last_input", "") or "").strip(),
        ]
    ).strip()
    cultivation_signal = _looks_like_cultivation_turn(candidate_text)
    breakthrough_realm = detect_breakthrough_realm(candidate_text, [target_realm])
    if breakthrough_realm is not None:
        current_realm = deps.character_profiles.get(player_actor, {}).get("realm", "")
        if not has_reached_realm(current_realm, breakthrough_realm):
            deps.character_profiles[player_actor] = {
                **deps.character_profiles.get(player_actor, {}),
                "realm": breakthrough_realm,
            }
            chapter_id = _clean_text(state["plot"].get("chapter_id", ""))
            plot_flags = dict(state["plot"].get("plot_flags", {}))
            if chapter_id:
                plot_flags[f"{chapter_id}_breakthrough"] = breakthrough_realm

            next_state = {
                **state,
                "plot": {
                    **state["plot"],
                    "plot_flags": plot_flags,
                },
            }
            synced_state = _sync_plot_cultivation_state(next_state, deps)
            return _append_narration_event(
                state=synced_state,
                content=_build_cultivation_result_text(
                    synced_state,
                    deps,
                    player_actor=player_actor,
                    breakthrough_realm=breakthrough_realm,
                ),
                source="cultivation_progress",
                style_preset=str(deps.gameplay_tuning.narration.style_preset or "xianxia_default").strip(),
            )

    if not cultivation_signal:
        return state

    return _append_narration_event(
        state=state,
        content=_build_cultivation_result_text(
            state,
            deps,
            player_actor=player_actor,
        ),
        source="cultivation_progress",
        style_preset=str(deps.gameplay_tuning.narration.style_preset or "xianxia_default").strip(),
    )


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


def director_node(state: GameState, deps: GraphDependencies) -> GameState:
    director_agent = _resolve_component(
        deps,
        "director_agent",
        "build_director_agent",
        required_name="a DirectorAgent",
    )
    if director_agent is None:
        return state
    brief = director_agent.update_stage(
        state=state,
        character_profiles=deps.character_profiles,
    )
    return apply_director_brief(
        state,
        brief,
        character_profiles=deps.character_profiles,
    )


def scheduler_node(state: GameState, deps: GraphDependencies) -> GameState:
    policy = deps.scheduler_policy or deps.component_factory.build_scheduler_policy()
    decision = policy.decide_next_turn(state)
    return apply_scheduler_decision(state, decision)


def beat_resolution_node(state: GameState, deps: GraphDependencies) -> GameState:
    execution_subgraph = deps.beat_execution_subgraph
    if execution_subgraph is None:
        execution_subgraph = build_beat_execution_subgraph(
            lead_in_step=lambda current: director_lead_in_node(current, deps),
            actor_step=lambda current: actor_node(current, deps),
            history_commit_step=lambda current: history_commit_node(current, deps),
            contextual_progression_step=lambda current: contextual_progression_node(current, deps),
            narration_step=lambda current: narration_subgraph_node(current, deps),
            cultivation_step=lambda current: cultivation_progress_node(current, deps),
            scene_end_step=lambda current: scene_end_node(current, deps),
            refresh_history_step=lambda current: refresh_history_node(current, deps),
        )
        deps.beat_execution_subgraph = execution_subgraph

    return run_beat_loop(
        state,
        deps,
        scheduler_step=lambda current: scheduler_node(current, deps),
        execution_subgraph=execution_subgraph,
        flush_step=lambda current: narration_subgraph_node(current, deps, force_flush=True),
        wrap_step=lambda current: director_wrap_up_node(current, deps),
    )


def actor_node(state: GameState, deps: GraphDependencies) -> GameState:
    if state["runtime"].get("next_act") is None:
        return state

    if is_player_turn(state):
        return resolve_player_turn_state(state, deps)

    planned_act = state["runtime"].get("next_act") or {}
    actor_id = str(planned_act.get("actor", "") or "").strip()
    actor_profile = deps.character_profiles.get(actor_id, {})
    agent_type = _clean_text(actor_profile.get("agent_type", ""), "actor")
    selected_actor_agent: ActorAgent | None
    if agent_type == "L2":
        selected_actor_agent = _resolve_component(
            deps,
            "l2_actor_agent",
            "build_l2_actor_agent",
            required_name="an L2ActorAgent",
        )
    elif agent_type == "L1":
        selected_actor_agent = _resolve_component(
            deps,
            "l1_actor_agent",
            "build_l1_actor_agent",
            required_name="an L1ActorAgent",
        )
    else:
        selected_actor_agent = _resolve_component(
            deps,
            "actor_agent",
            "build_actor_agent",
            required_name="an ActorAgent",
        )

    return resolve_npc_turn_state(
        state,
        deps,
        actor_agent=selected_actor_agent,
        polish_nonverbal_action=_polish_nonverbal_action,
    )


def _polish_nonverbal_action(
    state: GameState,
    deps: GraphDependencies,
    resolved_act: dict[str, object],
) -> dict[str, object]:
    actor_id = str(resolved_act.get("actor") or "")
    if not actor_id:
        return resolved_act

    if actor_id == state["player"].get("controlled_character"):
        return resolved_act

    nonverbal_action = str(resolved_act.get("nonverbal_action", "") or "").strip()
    if not nonverbal_action:
        return {
            **resolved_act,
            "content": compose_resolved_act_content(
                mode=str(resolved_act.get("mode", "speak")),
                spoken_text=str(resolved_act.get("spoken_text", "") or ""),
                nonverbal_action="",
                fallback_content=str(resolved_act.get("content", "") or ""),
            ),
        }

    stylistic_polish_agent = _resolve_stylistic_polish_agent(deps)
    if stylistic_polish_agent is not None:
        polished_action = stylistic_polish_agent.polish_nonverbal_action(
            draft_action=nonverbal_action,
            actor_id=actor_id,
            mode=str(resolved_act.get("mode", "speak")),
            state=state,
            character_profiles=deps.character_profiles,
        )
    else:
        polished_action = deterministic_nonverbal_cleanup(nonverbal_action)

    return {
        **resolved_act,
        "nonverbal_action": polished_action,
        "content": compose_resolved_act_content(
            mode=str(resolved_act.get("mode", "speak")),
            spoken_text=str(resolved_act.get("spoken_text", "") or ""),
            nonverbal_action=polished_action,
            fallback_content=str(resolved_act.get("content", "") or ""),
        ),
    }

def history_commit_node(state: GameState, deps: GraphDependencies) -> GameState:
    return apply_resolved_act(
        state,
        deps.gameplay_tuning.relationship,
        character_profiles=deps.character_profiles,
    )


def contextual_progression_node(state: GameState, deps: GraphDependencies) -> GameState:
    return apply_contextual_scene_progression(state, deps.character_profiles)


def scene_end_node(state: GameState, deps: GraphDependencies) -> GameState:
    policy = deps.scene_end_policy or deps.component_factory.build_scene_end_policy(
        deps.gameplay_tuning.scene_end
    )
    evaluation = policy.evaluate(state)
    return apply_scene_end_evaluation(state, evaluation)
