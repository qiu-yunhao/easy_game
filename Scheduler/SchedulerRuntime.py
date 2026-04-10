from __future__ import annotations

from GameState import Act, GameState
from Scheduler.SchedulerDecision import SchedulerDecision


def apply_scheduler_decision(state: GameState, decision: SchedulerDecision) -> GameState:
    next_act: Act | None = None
    if decision["next_actor"] is not None:
        target = state["scene"].get("focus_character")
        if target == decision["next_actor"]:
            target = state["runtime"].get("last_actor")
        if target == decision["next_actor"]:
            target = None

        next_act = {
            "actor": decision["next_actor"],
            "mode": decision["mode"],
            "target": target,
            "motivation": decision["reason"],
            "content": "",
        }

    return {
        **state,
        "runtime": {
            **state["runtime"],
            "eligible_actors": decision["eligible_actors"],
            "next_act": next_act,
            "resolved_act": None,
            "scene_end_evaluation": None,
        },
    }
