from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from Actor import ActorAgent
from Actor import build_heuristic_resolved_act
from GameState import GameState
from PlayerControl import (
    ConsolePlayerInterface,
    build_heuristic_player_resolved_act,
)

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def resolve_player_turn_state(
    state: GameState,
    deps: "GraphDependencies",
) -> GameState:
    player_state = state.get("player", {})
    player_actor = player_state.get("controlled_character")
    player_interface = deps.player_interface or ConsolePlayerInterface()
    raw_input = player_interface.collect_action(
        state=state,
        actor_id=str(player_actor),
        character_profiles=deps.character_profiles,
    )

    semantic_parser_agent = deps.semantic_parser_agent
    if semantic_parser_agent is None and deps.agent_first:
        semantic_parser_agent = deps.component_factory.build_semantic_parser_agent()

    if semantic_parser_agent is not None:
        resolved_act = semantic_parser_agent.parse_action(
            raw_input=raw_input,
            state=state,
            character_profiles=deps.character_profiles,
        )
    else:
        if deps.agent_first:
            raise RuntimeError(
                "Agent-first mode requires a SemanticParserAgent for player turns, but none is available."
            )
        resolved_act = build_heuristic_player_resolved_act(
            raw_input=raw_input,
            state=state,
            character_profiles=deps.character_profiles,
        )

    return {
        **state,
        "runtime": {
            **state["runtime"],
            "resolved_act": resolved_act,
        },
        "player": {
            **state["player"],
            "last_input": raw_input,
            "last_parsed_act": resolved_act,
        },
    }


def resolve_npc_turn_state(
    state: GameState,
    deps: "GraphDependencies",
    *,
    actor_agent: ActorAgent | None = None,
    polish_nonverbal_action: Callable[[GameState, "GraphDependencies", dict[str, object]], dict[str, object]],
) -> GameState:
    if actor_agent is not None:
        # 从计划的 next_act 取 actor_id,由记忆工厂 build 出只读记忆上下文。
        planned_act = state["runtime"].get("next_act") or {}
        actor_id = str(planned_act.get("actor", "") or "").strip()
        assert deps.actor_memory_provider is not None, "actor_memory_provider 未注入(本轮强制注入,不做静默降级)"
        memory_ctx = deps.actor_memory_provider.build(actor_id, state)
        resolved_act = actor_agent.perform_turn(
            state=state,
            memory_ctx=memory_ctx,
        )
    else:
        if deps.agent_first:
            raise RuntimeError("Agent-first mode requires an ActorAgent, but none is available.")
        resolved_act = build_heuristic_resolved_act(
            state=state,
            character_profiles=deps.character_profiles,
            relationship_tuning=deps.gameplay_tuning.relationship,
        )

    if not (deps.agent_first or deps.narrator_agent is not None):
        resolved_act = polish_nonverbal_action(
            state,
            deps,
            resolved_act,
        )

    return {
        **state,
        "runtime": {
            **state["runtime"],
            "resolved_act": resolved_act,
        },
    }
