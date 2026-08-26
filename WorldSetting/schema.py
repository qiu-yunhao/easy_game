from __future__ import annotations

from typing import Any, Literal, TypedDict


ADVANCE_CONDITION_TYPES = ("event", "threshold", "narrative", "composite")

AdvanceConditionType = Literal["event", "threshold", "narrative", "composite"]


class AdvanceCondition(TypedDict, total=False):
    type: AdvanceConditionType
    # event
    description: str
    completion_marker: str
    # threshold
    counter_key: str
    target_value: int
    # composite
    op: Literal["AND", "OR"]
    sub_conditions: list["AdvanceCondition"]


class Tier(TypedDict):
    name: str
    advance_condition: AdvanceCondition


class ProgressionSystem(TypedDict):
    system_name: str
    current_tier_index: int
    tiers: list[Tier]


class CharacterSeed(TypedDict, total=False):
    character_id: str
    name: str
    role: str
    start_tier_index: int
    motivation: str
    initial_relations: dict[str, str]
    secrets: list[str]


class FactionGeography(TypedDict, total=False):
    name: str
    kind: str  # "location" | "faction"
    description: str


class TemplateRef(TypedDict, total=False):
    template_id: int
    passages: list[str]


class WorldSetting(TypedDict):
    # A. 锁定骨架
    genre_tag: str
    tone: str
    core_drive: str
    core_conflict: str
    power_system: str
    progression: ProgressionSystem
    protagonist: CharacterSeed
    # B. 增量种子
    key_characters: list[CharacterSeed]
    factions_geography: list[FactionGeography]
    # 元信息
    title: str
    summary: str
    source: str  # "preset" | "dialogue" | "rag_import"
    template_ref: list[TemplateRef]


def build_advance_condition(condition_type: str, **fields: Any) -> AdvanceCondition:
    condition: AdvanceCondition = {"type": condition_type}  # type: ignore[typeddict-item]
    condition.update(fields)  # type: ignore[typeddict-item]
    return condition


def build_tier(*, name: str, advance_condition: AdvanceCondition) -> Tier:
    return {"name": name, "advance_condition": advance_condition}


def build_empty_progression() -> ProgressionSystem:
    return {"system_name": "", "current_tier_index": 0, "tiers": []}


def build_empty_world_setting() -> WorldSetting:
    return {
        "genre_tag": "",
        "tone": "",
        "core_drive": "",
        "core_conflict": "",
        "power_system": "",
        "progression": build_empty_progression(),
        "protagonist": {},
        "key_characters": [],
        "factions_geography": [],
        "title": "",
        "summary": "",
        "source": "dialogue",
        "template_ref": [],
    }
