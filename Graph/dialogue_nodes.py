from __future__ import annotations

from Actor import ActorAgent, apply_resolved_act
from Actor.ActorFormatter import compose_resolved_act_content
from Graph.actor_paths import resolve_npc_turn_state, resolve_player_turn_state
from Graph.beat_subgraph import (
    BeatEventCallback,
    build_beat_execution_subgraph,
    is_player_turn,
    run_beat_loop,
)
from Graph.component_resolution import (
    resolve_component as _resolve_component,
    resolve_stylistic_polish_agent as _resolve_stylistic_polish_agent,
)
from Graph.contextual_scene_handoffs import apply_contextual_scene_progression
from Graph.dependencies import GraphDependencies
from Graph.narration_nodes import (
    director_lead_in_node,
    director_wrap_up_node,
    narration_subgraph_node,
)
from StoryStateUtils import clean_text as _clean_text
# 修炼节点逻辑已抽到 Cultivation 领域插件;此处仅按需导入其对外节点。
from Cultivation import cultivation_progress_node
from Director import apply_director_brief
from GameState import GameState
from History.MemoryRefreshPolicy import run_async_refresh
from SceneEnd import apply_scene_end_evaluation
from Scheduler import apply_scheduler_decision
from StylisticPolish import deterministic_nonverbal_cleanup


def refresh_history_node(state: GameState, deps: GraphDependencies) -> GameState:
    return run_async_refresh(
        state,
        manager=deps.history_manager,
        store=deps.memory_store,
        compactor=deps.memory_compactor,
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


def beat_resolution_node(
    state: GameState,
    deps: GraphDependencies,
    on_event: BeatEventCallback | None = None,
) -> GameState:
    execution_subgraph = deps.beat_execution_subgraph
    if execution_subgraph is None:
        # Lazy import breaks Graph.dialogue_nodes <-> Graph.beat_nodes circular dependency.
        from Graph.beat_nodes import (
            ActorNode,
            CultivationProgressNode,
            DirectorLeadInNode,
            NarrationNode,
            SceneEndNode,
        )

        registry = deps.hook_registry
        execution_subgraph = build_beat_execution_subgraph(
            director_lead_in=DirectorLeadInNode(deps, registry),
            actor=ActorNode(deps, registry),
            narration=NarrationNode(deps, registry),
            cultivation_progress=CultivationProgressNode(deps, registry),
            scene_end=SceneEndNode(deps, registry),
        )
        deps.beat_execution_subgraph = execution_subgraph

    def _group_step(current: GameState, group: list[str]) -> GameState:
        from Graph.beat_group import apply_group_results, run_actor_group

        # Parallel groups skip the per-turn execution_subgraph, so emit the
        # beat's one-shot director lead-in here to match the serial path.
        current = director_lead_in_node(current, deps)
        successes, failures = run_actor_group(
            current,
            group=group,
            resolve_agent=lambda actor_id: _resolve_agent_for_actor(deps, actor_id, current),
            provider=deps.actor_memory_provider,
        )
        applied = apply_group_results(
            current,
            successes=successes,
            failures=failures,
            relationship_tuning=deps.gameplay_tuning.relationship,
            character_profiles=deps.character_profiles,
        )
        applied = narration_subgraph_node(applied, deps)
        applied = cultivation_progress_node(applied, deps)
        return scene_end_node(applied, deps)

    return run_beat_loop(
        state,
        deps,
        scheduler_step=lambda current: scheduler_node(current, deps),
        execution_subgraph=execution_subgraph,
        flush_step=lambda current: narration_subgraph_node(current, deps, force_flush=True),
        wrap_step=lambda current: director_wrap_up_node(current, deps),
        group_step=_group_step,
        on_event=on_event,
    )


def _resolve_agent_for_actor(
    deps: GraphDependencies,
    actor_id: str,
    state: GameState,
) -> ActorAgent | None:
    player = state["player"]
    if player.get("auto_mode", False) and actor_id == player.get("controlled_character"):
        # 玩家在自动模式下由 L1 agent 演绎;不读也不改 character_profiles.agent_type。
        return _resolve_component(
            deps,
            "l1_actor_agent",
            "build_l1_actor_agent",
            required_name="an L1ActorAgent",
        )
    actor_profile = deps.character_profiles.get(actor_id, {})
    agent_type = _clean_text(actor_profile.get("agent_type", ""), "actor")
    if agent_type == "L1":
        return _resolve_component(
            deps,
            "l1_actor_agent",
            "build_l1_actor_agent",
            required_name="an L1ActorAgent",
        )
    return _resolve_component(
        deps,
        "actor_agent",
        "build_actor_agent",
        required_name="an ActorAgent",
    )


def actor_node(state: GameState, deps: GraphDependencies) -> GameState:
    if state["runtime"].get("next_act") is None:
        return state

    if is_player_turn(state):
        return resolve_player_turn_state(state, deps)

    planned_act = state["runtime"].get("next_act") or {}
    actor_id = str(planned_act.get("actor", "") or "").strip()
    selected_actor_agent = _resolve_agent_for_actor(deps, actor_id, state)

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
