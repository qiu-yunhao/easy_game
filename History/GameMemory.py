from __future__ import annotations

from typing import Literal, NotRequired, Optional, TypedDict


class HistoryItem(TypedDict):
    turn: int
    actor: Optional[str]
    mode: str
    content: str
    spoken_text: NotRequired[str]
    nonverbal_action: NotRequired[str]
    raw_content: NotRequired[str]
    raw_spoken_text: NotRequired[str]
    raw_nonverbal_action: NotRequired[str]
    narration_source: NotRequired[str]
    narration_style_preset: NotRequired[str]
    message_kind: NotRequired[str]
    tool_name: NotRequired[str]


class ScoredHistoryItem(HistoryItem):
    importance_score: float
    importance_bucket: Literal["high", "mid", "low"]
    score_reason: str


class CompressedHistoryBlock(TypedDict):
    kind: Literal["raw", "summary"]
    bucket: Literal["high", "mid", "low"]
    turn_start: int
    turn_end: int
    raw_items: list[HistoryItem]
    summary: str
    key_points: list[str]
    actors: list[str]
    avg_score: float
    max_score: float


class SceneMemory(TypedDict):
    turn_range: str
    summary: str
    key_events: list[str]
    revealed_facts: list[str]
    active_conflicts: list[str]
    open_loops: list[str]
    recent_speakers: list[str]
    response_pressure: list[str]
    tension_trend: Literal["stable", "rising", "high"]
    focus_suggestion: Optional[str]
    compressed_blocks: list[CompressedHistoryBlock]


class PlaywrightMemory(TypedDict):
    scene_summary: str
    key_events: list[str]
    revealed_facts: list[str]
    active_conflicts: list[str]
    open_loops: list[str]
    protected_secrets: list[str]
    character_objectives_hint: dict[str, str]


class DirectorMemory(TypedDict):
    scene_summary: str
    recent_stage_dynamics: list[str]
    current_focus: Optional[str]
    tension_trend: Literal["stable", "rising", "high"]
    who_needs_response: list[str]
    active_conflicts: list[str]
    beat_suggestion: Optional[str]


class SchedulerMemory(TypedDict):
    scene_summary: str
    last_rounds: list[str]
    recent_speakers: list[str]
    unanswered_prompts: list[str]
    on_stage: list[str]
    focus_character: Optional[str]
    response_pressure: list[str]


class MemoryState(TypedDict):
    last_compressed_turn: int
    scene_memory: SceneMemory
    playwright_memory: PlaywrightMemory
    director_memory: DirectorMemory
    scheduler_memory: SchedulerMemory


def empty_scene_memory() -> SceneMemory:
    return {
        "turn_range": "0-0",
        "summary": "",
        "key_events": [],
        "revealed_facts": [],
        "active_conflicts": [],
        "open_loops": [],
        "recent_speakers": [],
        "response_pressure": [],
        "tension_trend": "stable",
        "focus_suggestion": None,
        "compressed_blocks": [],
    }


def empty_playwright_memory() -> PlaywrightMemory:
    return {
        "scene_summary": "",
        "key_events": [],
        "revealed_facts": [],
        "active_conflicts": [],
        "open_loops": [],
        "protected_secrets": [],
        "character_objectives_hint": {},
    }


def empty_director_memory() -> DirectorMemory:
    return {
        "scene_summary": "",
        "recent_stage_dynamics": [],
        "current_focus": None,
        "tension_trend": "stable",
        "who_needs_response": [],
        "active_conflicts": [],
        "beat_suggestion": None,
    }


def empty_scheduler_memory() -> SchedulerMemory:
    return {
        "scene_summary": "",
        "last_rounds": [],
        "recent_speakers": [],
        "unanswered_prompts": [],
        "on_stage": [],
        "focus_character": None,
        "response_pressure": [],
    }


def empty_memory_state() -> MemoryState:
    return {
        "last_compressed_turn": 0,
        "scene_memory": empty_scene_memory(),
        "playwright_memory": empty_playwright_memory(),
        "director_memory": empty_director_memory(),
        "scheduler_memory": empty_scheduler_memory(),
    }
