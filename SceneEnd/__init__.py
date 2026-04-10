from __future__ import annotations

from SceneEnd.SceneEndEvaluation import SceneEndEvaluation, empty_scene_end_evaluation
from LazyImport import LazySymbol


HeuristicSceneEndPolicy = LazySymbol(
    "SceneEnd.SceneEndHeuristics",
    "HeuristicSceneEndPolicy",
)
apply_scene_end_evaluation = LazySymbol(
    "SceneEnd.SceneEndRuntime",
    "apply_scene_end_evaluation",
)

__all__ = [
    "HeuristicSceneEndPolicy",
    "SceneEndEvaluation",
    "apply_scene_end_evaluation",
    "empty_scene_end_evaluation",
]
