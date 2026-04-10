from __future__ import annotations

from typing import TypedDict


class SceneEndEvaluation(TypedDict):
    should_end_scene: bool
    should_end_chapter: bool
    reason: str
    unmet_requirements: list[str]
    exit_condition_status: str
    confidence: float


def empty_scene_end_evaluation() -> SceneEndEvaluation:
    return {
        "should_end_scene": False,
        "should_end_chapter": False,
        "reason": "",
        "unmet_requirements": [],
        "exit_condition_status": "",
        "confidence": 0.0,
    }
