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
    _append_narration_event,
    director_lead_in_node,
    director_wrap_up_node,
    narration_subgraph_node,
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
from Director import apply_director_brief
from GameState import GameState
from SceneEnd import apply_scene_end_evaluation
from Scheduler import apply_scheduler_decision
from StylisticPolish import deterministic_nonverbal_cleanup


CULTIVATION_SIGNAL_MARKERS = (
    "修炼",
    "打坐",
    "吐纳",
    "运功",
    "调息",
    "闭关",
    "冲关",
    "炼化",
    "灵气",
    "周天",
    "丹药",
    "服下",
    "药力",
)


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
    used_pill = any(marker in latest_input for marker in ("丹", "药", "药力"))
    if breakthrough_realm:
        return (
            f"{player_name}在洞府中运转周天，"
            f"体内灵息终于由散而聚，"
            f"一举踏入{breakthrough_realm}。"
        )
    if used_pill:
        return (
            f"{player_name}盘坐调息之间，"
            "药力沿经脉缓缓化开，"
            "气息比先前更凝练了几分，"
            "只是距破境还差最后一线水磨功夫。"
        )
    return (
        f"{player_name}收敛心神，在洞府中缓缓吐纳，"
        "体内灵息虽未立刻破关，"
        "却已在一次次循环之间渐渐稳固。"
    )


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
            deps.character_profiles.update_field(
                player_actor, "realm", breakthrough_realm
            )
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
            resolve_agent=lambda actor_id: _resolve_agent_for_actor(deps, actor_id),
            character_profiles=deps.character_profiles,
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
) -> ActorAgent | None:
    actor_profile = deps.character_profiles.get(actor_id, {})
    agent_type = _clean_text(actor_profile.get("agent_type", ""), "actor")
    if agent_type == "L2":
        return _resolve_component(
            deps,
            "l2_actor_agent",
            "build_l2_actor_agent",
            required_name="an L2ActorAgent",
        )
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
    selected_actor_agent = _resolve_agent_for_actor(deps, actor_id)

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
