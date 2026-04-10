from __future__ import annotations

from GameState import GameState
from SceneEnd.SceneEndEvaluation import SceneEndEvaluation


def apply_scene_end_evaluation(
    state: GameState,
    evaluation: SceneEndEvaluation,
) -> GameState:
    return {
        **state,
        "runtime": {
            **state["runtime"],
            "scene_end_evaluation": evaluation,
            "scene_finished": evaluation["should_end_scene"],
            "chapter_finished": evaluation["should_end_chapter"],
        },
    }
