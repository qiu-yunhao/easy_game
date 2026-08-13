from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from GameState import GameState
from Graph.graph_compile import NodeStep, compile_graph_with_nodes
from Graph.hookable_node import HookableNode

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies

# Emit newly committed history entries to a streaming consumer. Receives one
# raw history dict per call, in commit order.
BeatEventCallback = Callable[[dict[str, Any]], None]


def build_beat_execution_subgraph(
    *,
    director_lead_in: HookableNode,
    actor: HookableNode,
    narration: HookableNode,
    cultivation_progress: HookableNode,
    scene_end: HookableNode,
) -> NodeStep:
    return compile_graph_with_nodes(
        [
            (director_lead_in.name, director_lead_in.as_step()),
            (actor.name, actor.as_step()),
            (narration.name, narration.as_step()),
            (cultivation_progress.name, cultivation_progress.as_step()),
            (scene_end.name, scene_end.as_step()),
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


def _next_group(state: GameState) -> list[str]:
    """Return the next parallel group of still-active actors, or []."""
    active = set(state["runtime"].get("pending_beat_actors", []) or [])
    for group in state["runtime"].get("pending_response_groups", []) or []:
        eligible = [cid for cid in group if cid in active]
        if len(eligible) > 1:
            return eligible
    return []


def _consume_group(state: GameState, group: list[str]) -> GameState:
    """Prune a resolved group from the pending queues and clear next_act."""
    consumed = set(group)
    pending_actors = [
        cid
        for cid in (state["runtime"].get("pending_beat_actors", []) or [])
        if cid not in consumed
    ]
    pending_groups = [
        remaining
        for remaining in (
            [cid for cid in grp if cid not in consumed]
            for grp in (state["runtime"].get("pending_response_groups", []) or [])
        )
        if remaining
    ]
    return {
        **state,
        "runtime": {
            **state["runtime"],
            "pending_beat_actors": pending_actors,
            "pending_response_groups": pending_groups,
            "next_act": None,
        },
    }


def run_beat_loop(
    state: GameState,
    deps: "GraphDependencies",
    *,
    scheduler_step: NodeStep,
    execution_subgraph: NodeStep,
    flush_step: NodeStep,
    wrap_step: NodeStep,
    group_step: Callable[[GameState, list[str]], GameState] | None = None,
    on_event: BeatEventCallback | None = None,
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

    # Track how many history entries have already been streamed so each step
    # only emits the entries it newly committed, in order.
    emitted = len(current.get("history", []))

    def _flush(next_state: GameState) -> GameState:
        nonlocal emitted
        if on_event is None:
            return next_state
        history = next_state.get("history", [])
        for entry in history[emitted:]:
            on_event(entry)
        emitted = len(history)
        return next_state

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

        group = _next_group(current) if group_step is not None else []
        if group and str((current["runtime"].get("next_act") or {}).get("actor", "")) in group:
            current = group_step(current, group)
            current = _consume_group(current, group)
        else:
            current = execution_subgraph(current)
        current = _flush(current)
        resolved_turns += 1

        if not beat_has_remaining_turns(current):
            break
    else:
        raise RuntimeError(
            "Beat resolution exceeded the safety limit before the director queue was exhausted."
        )

    return _flush(wrap_step(_flush(flush_step(current))))
