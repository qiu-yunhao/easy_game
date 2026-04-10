from __future__ import annotations

from typing import Protocol

from GameState import GameState
from Scheduler.SchedulerDecision import SchedulerDecision


class SchedulerPolicy(Protocol):
    def resolve_eligible_actors(self, state: GameState) -> list[str]:
        ...

    def decide_next_turn(self, state: GameState) -> SchedulerDecision:
        ...


class HeuristicSchedulerPolicy:
    def _can_repeat_actor(
        self,
        candidate: str,
        last_actor: str | None,
        eligible_actors: list[str],
    ) -> bool:
        return candidate != last_actor or len(eligible_actors) == 1

    def _collect_pending_director_actors(
        self,
        state: GameState,
        eligible_actors: list[str],
    ) -> list[str]:
        return [
            cid
            for cid in state["runtime"].get("pending_beat_actors", [])
            if cid in eligible_actors
        ]

    def _choose_fallback_actor(
        self,
        state: GameState,
        eligible_actors: list[str],
        last_actor: str | None,
    ) -> str:
        focus_character = state["scene"].get("focus_character")
        if (
            focus_character in eligible_actors
            and self._can_repeat_actor(focus_character, last_actor, eligible_actors)
        ):
            return str(focus_character)

        for cid in eligible_actors:
            if self._can_repeat_actor(cid, last_actor, eligible_actors):
                return cid

        return eligible_actors[0]

    def resolve_eligible_actors(self, state: GameState) -> list[str]:
        on_stage = state["scene"].get("on_stage", [])
        suppressed = set(state["scene"].get("suppressed", []))
        active_on_stage = [cid for cid in on_stage if cid not in suppressed]
        prioritized = [
            cid
            for cid in state["runtime"].get("eligible_actors", [])
            if cid in active_on_stage
        ]
        for cid in active_on_stage:
            if cid not in prioritized:
                prioritized.append(cid)
        return prioritized

    def decide_next_turn(self, state: GameState) -> SchedulerDecision:
        if state["runtime"].get("scene_finished", False):
            return {
                "next_actor": None,
                "mode": "event",
                "eligible_actors": [],
                "reason": "Scene is already marked as finished.",
            }

        eligible_actors = self.resolve_eligible_actors(state)
        if not eligible_actors:
            return {
                "next_actor": None,
                "mode": "event",
                "eligible_actors": [],
                "reason": "No eligible actors remain on stage.",
            }

        last_actor = state["runtime"].get("last_actor")
        director_priorities = self._collect_pending_director_actors(state, eligible_actors)

        if director_priorities:
            next_actor = director_priorities[0]
            reason = (
                "Director queued "
                f"{next_actor} from eligible actors {eligible_actors}."
            )
        elif int(state["runtime"].get("beat_fallback_turns_remaining", 0) or 0) > 0:
            next_actor = self._choose_fallback_actor(state, eligible_actors, last_actor)
            reason = (
                "Scheduler fallback selected "
                f"{next_actor} from eligible actors {eligible_actors}."
            )
        else:
            return {
                "next_actor": None,
                "mode": "event",
                "eligible_actors": eligible_actors,
                "reason": "The current beat has no remaining queued actors.",
            }

        return {
            "next_actor": next_actor,
            "mode": "speak",
            "eligible_actors": eligible_actors,
            "reason": reason,
        }
