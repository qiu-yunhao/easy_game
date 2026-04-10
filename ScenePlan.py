from __future__ import annotations

from typing import TypedDict


class ScenePlan(TypedDict):
    scene_goal: str
    must_happen: list[str]
    must_not_happen: list[str]
    dramatic_curve: list[str]
    character_objectives: dict[str, str]
    exit_condition: str
    notes: list[str]


def empty_scene_plan() -> ScenePlan:
    return {
        "scene_goal": "",
        "must_happen": [],
        "must_not_happen": [],
        "dramatic_curve": [],
        "character_objectives": {},
        "exit_condition": "",
        "notes": [],
    }
