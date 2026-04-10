from __future__ import annotations

from Director.DirectorBrief import DirectorBrief, StageActions, empty_director_brief
from Director.DirectorFormatter import DirectorFormatter
from LazyImport import LazySymbol


DirectorAgent = LazySymbol("Director.DirectorAgent", "DirectorAgent")
apply_director_brief = LazySymbol("Director.DirectorRuntime", "apply_director_brief")
apply_stage_actions_to_scene = LazySymbol("Director.DirectorRuntime", "apply_stage_actions_to_scene")
normalize_director_brief = LazySymbol("Director.DirectorRuntime", "normalize_director_brief")
normalize_stage_actions = LazySymbol("Director.DirectorRuntime", "normalize_stage_actions")

__all__ = [
    "DirectorAgent",
    "DirectorBrief",
    "DirectorFormatter",
    "StageActions",
    "apply_director_brief",
    "apply_stage_actions_to_scene",
    "empty_director_brief",
    "normalize_director_brief",
    "normalize_stage_actions",
]
