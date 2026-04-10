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
        resolved_act = actor_agent.perform_turn(
            state=state,
            character_profiles=deps.character_profiles,
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
