from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

from CharacterMemory import CharacterMemoryState, empty_character_memory_state
from Director.DirectorBrief import DirectorBrief, empty_director_brief
from History.GameMemory import HistoryItem, MemoryState, empty_memory_state
from Narrator.NarratorTypes import NarrationQueueItem
from ScenePlan import ScenePlan, empty_scene_plan
from SceneEnd.SceneEndEvaluation import SceneEndEvaluation, empty_scene_end_evaluation


class ChapterOutline(TypedDict):
    chapter_id: str
    title: str
    main_goal: str
    summary: str
    exploration_hooks: list[str]
    key_locations: list[str]
    realm_stage: str
    next_realm: str


class ChapterArchive(TypedDict):
    chapter_id: str
    title: str
    goal: str
    overview: str
    summary: str
    key_events: list[str]
    revealed_facts: list[str]
    open_loops: list[str]
    completed_turn: int


class SceneCandidate(TypedDict):
    candidate_id: str
    label: str
    location_id: str
    beat: str
    scene_goal: str
    must_happen: list[str]
    must_not_happen: list[str]
    dramatic_curve: list[str]
    character_objectives: dict[str, str]
    exit_condition: str
    notes: list[str]


class PlotState(TypedDict):
    chapter_id: str
    scene_id: str
    current_scene_index: int
    chapter_goal: str
    current_chapter_hooks: list[str]
    plot_flags: dict[str, str]
    story_premise: str
    exploration_drive: str
    story_outline: list[ChapterOutline]
    current_chapter_title: str
    current_chapter_overview: str
    active_outline_chapter_id: str
    story_premise_source: str
    story_outline_source: str
    chapter_expansion_source: str
    story_foundation_source: str
    chapter_focus_source: str
    scene_candidates_source: str
    current_chapter_index: int
    cultivation_goal: str
    current_player_realm: str
    current_chapter_realm: str
    next_chapter_realm: str
    chapter_transition_requirement: str
    completed_chapters: list[ChapterArchive]
    selected_template_id: int
    world_setting: dict[str, Any]


class SceneState(TypedDict):
    location_id: str
    time_tag: str
    beat: str
    tension: float
    focus_character: Optional[str]
    on_stage: list[str]
    allow_interrupt: bool
    suppressed: list[str]


class CharacterRuntimeState(TypedDict):
    emotion: dict[str, float]
    intent: str
    known_facts: list[str]
    relationship_delta: dict[str, float]
    last_turn: int
    memory: CharacterMemoryState


class Act(TypedDict, total=False):
    actor: Optional[str]
    mode: Literal["speak", "action", "silence", "interrupt", "event"]
    target: Optional[str]
    motivation: str
    content: str


class ResolvedAct(TypedDict):
    actor: Optional[str]
    mode: Literal["speak", "action", "silence", "interrupt", "event"]
    target: Optional[str]
    content: str
    spoken_text: str
    nonverbal_action: str
    next_intent: str
    emotion_update: dict[str, float]
    relationship_update: dict[str, float]
    revealed_facts: list[str]
    triggered_plot_flags: dict[str, str]
    should_end_scene: bool
    should_end_chapter: bool


class RuntimeState(TypedDict):
    turn_index: int
    last_actor: Optional[str]
    last_mode: Optional[str]
    eligible_actors: list[str]
    pending_intro_kind: Literal["", "opening", "chapter", "scene"]
    pending_beat_actors: list[str]
    pending_response_groups: list[list[str]]
    beat_fallback_turns_remaining: int
    narration_queue: list[NarrationQueueItem]
    scene_candidates: list[SceneCandidate]
    next_act: Optional[Act]
    resolved_act: Optional[ResolvedAct]
    scene_end_evaluation: Optional[SceneEndEvaluation]
    scene_finished: bool
    chapter_finished: bool


class PlayerState(TypedDict):
    enabled: bool
    controlled_character: Optional[str]
    auto_mode: bool
    last_input: str
    last_parsed_act: Optional[ResolvedAct]


class GameState(TypedDict):
    plot: PlotState
    scene: SceneState
    characters: dict[str, CharacterRuntimeState]
    history: list[HistoryItem]
    runtime: RuntimeState
    scene_plan: ScenePlan
    director_brief: DirectorBrief
    memory: MemoryState
    player: PlayerState


def create_runtime_state(on_stage: list[str] | None = None) -> RuntimeState:
    return {
        "turn_index": 0,
        "last_actor": None,
        "last_mode": None,
        "eligible_actors": list(on_stage or []),
        "pending_intro_kind": "opening",
        "pending_beat_actors": [],
        "pending_response_groups": [],
        "beat_fallback_turns_remaining": 0,
        "narration_queue": [],
        "scene_candidates": [],
        "next_act": None,
        "resolved_act": None,
        "scene_end_evaluation": empty_scene_end_evaluation(),
        "scene_finished": False,
        "chapter_finished": False,
    }


def create_character_runtime_state(
    *,
    emotion: dict[str, float] | None = None,
    intent: str = "",
    known_facts: list[str] | None = None,
    relationship_delta: dict[str, float] | None = None,
    last_turn: int = -1,
    memory: CharacterMemoryState | None = None,
) -> CharacterRuntimeState:
    return {
        "emotion": emotion or {},
        "intent": intent,
        "known_facts": known_facts or [],
        "relationship_delta": relationship_delta or {},
        "last_turn": last_turn,
        "memory": memory or empty_character_memory_state(),
    }


def create_player_state(
    *,
    controlled_character: str | None = None,
    enabled: bool | None = None,
    auto_mode: bool = False,
    last_input: str = "",
    last_parsed_act: ResolvedAct | None = None,
) -> PlayerState:
    return {
        "enabled": bool(controlled_character) if enabled is None else enabled,
        "controlled_character": controlled_character,
        "auto_mode": auto_mode,
        "last_input": last_input,
        "last_parsed_act": last_parsed_act,
    }


def create_initial_game_state(
    *,
    plot: PlotState,
    scene: SceneState,
    characters: dict[str, CharacterRuntimeState],
    history: list[HistoryItem] | None = None,
    runtime: RuntimeState | None = None,
    scene_plan: ScenePlan | None = None,
    director_brief: DirectorBrief | None = None,
    memory: MemoryState | None = None,
    player: PlayerState | None = None,
) -> GameState:
    return {
        "plot": plot,
        "scene": scene,
        "characters": characters,
        "history": list(history or []),
        "runtime": runtime or create_runtime_state(scene.get("on_stage", [])),
        "scene_plan": scene_plan or empty_scene_plan(),
        "director_brief": director_brief or empty_director_brief(),
        "memory": memory or empty_memory_state(),
        "player": player or create_player_state(),
    }
