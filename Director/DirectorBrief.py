from __future__ import annotations

from typing import Optional, TypedDict


class StageActions(TypedDict):
    enter: list[str]
    leave: list[str]
    suppress: list[str]
    unsuppress: list[str]


class DirectorBrief(TypedDict):
    beat: str
    beat_goal: str
    focus_character: Optional[str]
    tension_target: float
    allow_interrupt: bool
    who_should_respond: list[str]
    stage_actions: StageActions
    lead_in_text: str
    wrap_up_text: str
    notes: list[str]


def empty_stage_actions() -> StageActions:
    return {
        "enter": [],
        "leave": [],
        "suppress": [],
        "unsuppress": [],
    }


def empty_director_brief() -> DirectorBrief:
    return {
        "beat": "",
        "beat_goal": "",
        "focus_character": None,
        "tension_target": 0.0,
        "allow_interrupt": False,
        "who_should_respond": [],
        "stage_actions": empty_stage_actions(),
        "lead_in_text": "",
        "wrap_up_text": "",
        "notes": [],
    }
