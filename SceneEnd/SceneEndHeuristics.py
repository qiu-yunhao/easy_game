from __future__ import annotations

from typing import Protocol

from Cultivation import has_reached_realm
from GameplayTuning import SceneEndTuning
from GameState import GameState
from SceneEnd.SceneEndEvaluation import SceneEndEvaluation


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def _get_unmet_requirements(state: GameState) -> list[str]:
    plot_flags = state["plot"].get("plot_flags", {})
    return [
        item
        for item in state["scene_plan"].get("must_happen", [])
        if item not in plot_flags
    ]


def _chapter_progress_flags_met(state: GameState) -> bool:
    chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    if not chapter_id:
        return False
    plot_flags = state["plot"].get("plot_flags", {})
    required_flags = (
        f"{chapter_id}_clue",
        f"{chapter_id}_route",
        f"{chapter_id}_choice",
    )
    return all(flag in plot_flags for flag in required_flags)


def _player_reached_next_realm(state: GameState) -> bool:
    current_player_realm = str(state["plot"].get("current_player_realm", "") or "").strip()
    next_chapter_realm = str(state["plot"].get("next_chapter_realm", "") or "").strip()
    if not current_player_realm or not next_chapter_realm:
        return False
    return has_reached_realm(current_player_realm, next_chapter_realm)


def _should_end_chapter(
    state: GameState,
    *,
    should_end_scene: bool,
    unresolved: list[str],
    resolved_act: dict[str, object] | None,
) -> bool:
    if not should_end_scene:
        return False
    if resolved_act and bool(resolved_act.get("should_end_chapter", False)):
        return True
    if unresolved:
        return False

    current_scene_index = int(state["plot"].get("current_scene_index", 0) or 0)
    if current_scene_index < 2:
        return _player_reached_next_realm(state)
    if _player_reached_next_realm(state):
        return True
    if _chapter_progress_flags_met(state):
        return True
    if not state["scene_plan"].get("must_happen", []):
        return True
    return bool(str(state["scene_plan"].get("exit_condition", "") or "").strip())


class SceneEndPolicy(Protocol):
    def evaluate(self, state: GameState) -> SceneEndEvaluation:
        ...


class HeuristicSceneEndPolicy:
    def __init__(self, tuning: SceneEndTuning | None = None) -> None:
        self.tuning = tuning or SceneEndTuning()

    def evaluate(self, state: GameState) -> SceneEndEvaluation:
        tuning = self.tuning
        unresolved = _get_unmet_requirements(state)
        exit_condition = state["scene_plan"].get("exit_condition", "").strip()
        resolved_act = state["runtime"].get("resolved_act")
        on_stage = state["scene"].get("on_stage", [])
        suppressed = set(state["scene"].get("suppressed", []))
        active_on_stage = [cid for cid in on_stage if cid not in suppressed]

        if state["runtime"].get("scene_finished", False) and resolved_act is None:
            return {
                "should_end_scene": True,
                "should_end_chapter": state["runtime"].get("chapter_finished", False),
                "reason": "Scene was already marked finished upstream.",
                "unmet_requirements": unresolved,
                "exit_condition_status": exit_condition,
                "confidence": 1.0,
            }

        if not active_on_stage:
            should_end_chapter = _should_end_chapter(
                state,
                should_end_scene=True,
                unresolved=unresolved,
                resolved_act=resolved_act,
            )
            return {
                "should_end_scene": True,
                "should_end_chapter": should_end_chapter,
                "reason": "No active actors remain on stage.",
                "unmet_requirements": unresolved,
                "exit_condition_status": exit_condition,
                "confidence": 1.0,
            }

        if unresolved:
            return {
                "should_end_scene": False,
                "should_end_chapter": False,
                "reason": "Scene still has unresolved must_happen constraints.",
                "unmet_requirements": unresolved,
                "exit_condition_status": exit_condition,
                "confidence": tuning.unresolved_confidence,
            }

        if resolved_act and resolved_act.get("should_end_scene", False):
            should_end_chapter = _should_end_chapter(
                state,
                should_end_scene=True,
                unresolved=[],
                resolved_act=resolved_act,
            )
            return {
                "should_end_scene": True,
                "should_end_chapter": should_end_chapter,
                "reason": "Actor explicitly marked the scene ready to end.",
                "unmet_requirements": [],
                "exit_condition_status": exit_condition,
                "confidence": tuning.actor_override_confidence,
            }

        signal_score = 0.0
        reasons: list[str] = []

        if resolved_act and resolved_act.get("triggered_plot_flags"):
            signal_score += tuning.completion_signal_weight
            reasons.append("latest turn completed a planned beat")

        pending_responses = [
            cid
            for cid in state["runtime"].get("pending_beat_actors", [])
            if cid in active_on_stage
        ]
        if not pending_responses:
            signal_score += tuning.no_pending_response_weight
            reasons.append("no pending director responses")

        if state["scene"].get("tension", 0.0) >= max(
            tuning.minimum_tension_floor,
            float(state["director_brief"].get("tension_target", 0.0)),
        ):
            signal_score += tuning.tension_reached_weight
            reasons.append("scene reached target tension")

        if state["runtime"].get("last_mode") in {"action", "event", "silence"}:
            signal_score += tuning.closing_motion_weight
            reasons.append("latest beat feels like a closing motion")

        should_end = bool(exit_condition) and signal_score >= tuning.end_threshold
        should_end_chapter = _should_end_chapter(
            state,
            should_end_scene=should_end,
            unresolved=[],
            resolved_act=resolved_act,
        )
        reason = (
            "Heuristic scene-end threshold met: " + ", ".join(reasons)
            if should_end
            else "Scene should continue: exit condition exists but closure signals are still weak."
        )
        return {
            "should_end_scene": should_end,
            "should_end_chapter": should_end_chapter,
            "reason": reason,
            "unmet_requirements": [],
            "exit_condition_status": exit_condition,
            "confidence": _clamp_confidence(
                tuning.confidence_base + signal_score * tuning.confidence_signal_scale
            ),
        }
