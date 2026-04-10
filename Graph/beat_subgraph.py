from __future__ import annotations

from typing import TYPE_CHECKING

from GameState import GameState
from Graph.graph_compile import NodeStep, compile_graph_with_nodes

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def build_beat_execution_subgraph(
    *,
    lead_in_step: NodeStep,
    actor_step: NodeStep,
    history_commit_step: NodeStep,
    contextual_progression_step: NodeStep,
    narration_step: NodeStep,
    cultivation_step: NodeStep,
    scene_end_step: NodeStep,
    refresh_history_step: NodeStep,
) -> NodeStep:
    return compile_graph_with_nodes(
        [
            ("director_lead_in", lead_in_step),
            ("actor", actor_step),
            ("history_commit", history_commit_step),
            ("contextual_progression", contextual_progression_step),
            ("narration", narration_step),
            ("cultivation_progress", cultivation_step),
            ("scene_end", scene_end_step),
            ("refresh_history", refresh_history_step),
        ],
        fallback_to_runner=True,
    )


def is_player_turn(state: GameState) -> bool:
    next_act = state["runtime"].get("next_act")
    return bool(
        next_act is not None
        and state["player"].get("enabled", False)
        and next_act.get("actor") == state["player"].get("controlled_character")
    )


def can_auto_resolve_player_turn(deps: "GraphDependencies") -> bool:
    player_interface = deps.player_interface
    if player_interface is None:
        return True

    has_pending_action = getattr(player_interface, "has_pending_action", None)
    if callable(has_pending_action):
        return bool(has_pending_action())
    return True


def beat_has_remaining_turns(state: GameState) -> bool:
    if state["runtime"].get("next_act") is not None:
        return True
    if state["runtime"].get("pending_beat_actors", []):
        return True
    return int(state["runtime"].get("beat_fallback_turns_remaining", 0) or 0) > 0


def run_beat_loop(
    state: GameState,
    deps: "GraphDependencies",
    *,
    scheduler_step: NodeStep,
    execution_subgraph: NodeStep,
    flush_step: NodeStep,
    wrap_step: NodeStep,
) -> GameState:
    current = state
    safety_limit = max(
        1,
        len(current["runtime"].get("pending_beat_actors", []))
        + int(current["runtime"].get("beat_fallback_turns_remaining", 0) or 0)
        + len(current["scene"].get("on_stage", []))
        + 1,
    )
    resolved_turns = 0

    while resolved_turns < safety_limit:
        if current["runtime"].get("scene_finished", False):
            break
        if current["runtime"].get("chapter_finished", False):
            break
        if current["runtime"].get("next_act") is None:
            if not beat_has_remaining_turns(current):
                break
            current = scheduler_step(current)
            if current["runtime"].get("next_act") is None:
                break

        if is_player_turn(current) and not can_auto_resolve_player_turn(deps):
            break

        current = execution_subgraph(current)
        resolved_turns += 1

        if not beat_has_remaining_turns(current):
            break
    else:
        raise RuntimeError(
            "Beat resolution exceeded the safety limit before the director queue was exhausted."
        )

    return wrap_step(flush_step(current))
