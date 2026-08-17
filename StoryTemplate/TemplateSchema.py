from __future__ import annotations

from typing import Any, TypedDict

"""4 类模板产物的数据契约（纯 TypedDict）+ LLM JSON response schema。

沿用 PlayerWriter/PlaywriterSchema.py 的 json_schema 风格：response schema 供
BaseAgent.command(response_format=...) 约束 LLM 输出结构。TypedDict 是出库/入库口径。
"""


class StyleBible(TypedDict):
    narrative_voice: str
    tone_tags: list[str]
    prose_rhythm: str
    signature_devices: list[str]
    world_premise: str
    cultivation_system: str
    factions: list[str]
    key_locations: list[str]
    world_rules: list[str]
    lexicon: list[str]


class CharacterArchetype(TypedDict):
    name: str
    role_summary: str
    persona: list[str]
    speech_style: str
    secrets: list[str]
    signature_relations: list[str]
    suggested_layer: str


class PlotBeat(TypedDict):
    beat_id: str
    label: str
    tags: list[str]
    summary: str
    dramatic_function: str
    reusable_conflict: str


class PlotSkeletonNode(TypedDict):
    node_id: str
    order_index: int
    title: str
    event_summary: str
    preconditions: list[str]
    maps_to_chapter_hint: str


class ChunkSignal(TypedDict):
    """Level1 逐块提炼出的局部信号（未归并）。"""
    chunk_id: str
    order_index: int
    style_tone_tags: list[str]
    style_devices: list[str]
    characters: list[dict[str, Any]]  # {name, behavior}
    is_event: bool
    event_summary: str


def empty_style_bible() -> StyleBible:
    return {
        "narrative_voice": "", "tone_tags": [], "prose_rhythm": "",
        "signature_devices": [], "world_premise": "", "cultivation_system": "",
        "factions": [], "key_locations": [], "world_rules": [], "lexicon": [],
    }


def _obj_schema(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}

STYLE_BIBLE_RESPONSE_SCHEMA = _obj_schema(
    "style_bible",
    {
        "narrative_voice": _STR, "tone_tags": _STR_LIST, "prose_rhythm": _STR,
        "signature_devices": _STR_LIST, "world_premise": _STR,
        "cultivation_system": _STR, "factions": _STR_LIST,
        "key_locations": _STR_LIST, "world_rules": _STR_LIST, "lexicon": _STR_LIST,
    },
    ["narrative_voice", "tone_tags", "prose_rhythm", "signature_devices",
     "world_premise", "cultivation_system", "factions", "key_locations",
     "world_rules", "lexicon"],
)

CHARACTER_ARCHETYPE_RESPONSE_SCHEMA = _obj_schema(
    "character_archetypes",
    {"characters": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": _STR, "role_summary": _STR, "persona": _STR_LIST,
            "speech_style": _STR, "secrets": _STR_LIST,
            "signature_relations": _STR_LIST, "suggested_layer": _STR,
        },
        "required": ["name", "role_summary", "persona", "speech_style",
                     "secrets", "signature_relations", "suggested_layer"],
        "additionalProperties": False,
    }}},
    ["characters"],
)

PLOT_BEAT_RESPONSE_SCHEMA = _obj_schema(
    "plot_beats",
    {"beats": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "label": _STR, "tags": _STR_LIST, "summary": _STR,
            "dramatic_function": _STR, "reusable_conflict": _STR,
        },
        "required": ["label", "tags", "summary", "dramatic_function", "reusable_conflict"],
        "additionalProperties": False,
    }}},
    ["beats"],
)

PLOT_SKELETON_RESPONSE_SCHEMA = _obj_schema(
    "plot_skeleton",
    {"nodes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": _STR, "event_summary": _STR,
            "preconditions": _STR_LIST, "maps_to_chapter_hint": _STR,
        },
        "required": ["title", "event_summary", "preconditions", "maps_to_chapter_hint"],
        "additionalProperties": False,
    }}},
    ["nodes"],
)

CHUNK_SIGNAL_RESPONSE_SCHEMA = _obj_schema(
    "chunk_signal",
    {
        "style_tone_tags": _STR_LIST, "style_devices": _STR_LIST,
        "characters": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _STR, "behavior": _STR},
            "required": ["name", "behavior"], "additionalProperties": False,
        }},
        "is_event": {"type": "boolean"}, "event_summary": _STR,
    },
    ["style_tone_tags", "style_devices", "characters", "is_event", "event_summary"],
)
