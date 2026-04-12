from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict

from StoryStateUtils import clean_str_list, clean_text


MemoryDepth = Literal["full", "compact"]


class CharacterMemoryConfig(TypedDict):
    long_term_limit: int
    short_term_limit: int
    player_memory_limit: int
    pinned_long_term_limit: int
    consolidated_memory_limit: int
    consolidation_batch_size: int
    long_term_depth: MemoryDepth
    player_memory_depth: MemoryDepth


class LongTermMemoryEvent(TypedDict):
    turn_recorded: int
    event_summary: str
    subjective_interpretation: str
    belief_formed: str
    priority: str
    tags: list[str]
    pin_candidate: bool
    pin_reason: str
    linked_characters: list[str]


class ConsolidatedMemoryBlock(TypedDict):
    turn_start: int
    turn_end: int
    topic: str
    event_summary: str
    subjective_interpretation: str
    belief_formed: str
    linked_characters: list[str]
    source_event_count: int
    priority: str


class ShortTermMemoryEvent(TypedDict):
    turn: int
    chapter_id: str
    scene_id: str
    location_id: str
    actor: str | None
    mode: str
    summary: str


class PlayerImpressionEvent(TypedDict):
    turn: int
    summary: str
    impression: str
    rationale: str
    relation_delta: float
    tags: list[str]


class PlayerImpressionMemory(TypedDict):
    overall_impression: str
    relation_state: dict[str, float]
    key_events: list[PlayerImpressionEvent]


class CharacterMemoryState(TypedDict):
    pinned_long_term_memory: list[LongTermMemoryEvent]
    long_term_memory: list[LongTermMemoryEvent]
    consolidated_memory: list[ConsolidatedMemoryBlock]
    short_term_memory: list[ShortTermMemoryEvent]
    player_memory: PlayerImpressionMemory


L1_MEMORY_CONFIG: CharacterMemoryConfig = {
    "long_term_limit": 7,
    "short_term_limit": 30,
    "player_memory_limit": 8,
    "pinned_long_term_limit": 7,
    "consolidated_memory_limit": 6,
    "consolidation_batch_size": 3,
    "long_term_depth": "full",
    "player_memory_depth": "full",
}

L2_MEMORY_CONFIG: CharacterMemoryConfig = {
    "long_term_limit": 3,
    "short_term_limit": 30,
    "player_memory_limit": 3,
    "pinned_long_term_limit": 3,
    "consolidated_memory_limit": 3,
    "consolidation_batch_size": 3,
    "long_term_depth": "compact",
    "player_memory_depth": "compact",
}

ACTOR_MEMORY_CONFIG: CharacterMemoryConfig = {
    "long_term_limit": 3,
    "short_term_limit": 30,
    "player_memory_limit": 3,
    "pinned_long_term_limit": 3,
    "consolidated_memory_limit": 3,
    "consolidation_batch_size": 3,
    "long_term_depth": "compact",
    "player_memory_depth": "compact",
}


def memory_config_for_agent_type(agent_type: str) -> CharacterMemoryConfig:
    if agent_type == "L1":
        return dict(L1_MEMORY_CONFIG)
    if agent_type == "L2":
        return dict(L2_MEMORY_CONFIG)
    return dict(ACTOR_MEMORY_CONFIG)


def normalize_character_memory_config(
    value: Any,
    *,
    agent_type: str = "actor",
) -> CharacterMemoryConfig:
    source = value if isinstance(value, Mapping) else {}
    base = memory_config_for_agent_type(agent_type)
    normalized = dict(base)

    for field in (
        "long_term_limit",
        "short_term_limit",
        "player_memory_limit",
        "pinned_long_term_limit",
        "consolidated_memory_limit",
        "consolidation_batch_size",
    ):
        try:
            normalized[field] = max(1, int(source.get(field, normalized[field]) or normalized[field]))
        except (TypeError, ValueError):
            pass

    for field in ("long_term_depth", "player_memory_depth"):
        resolved = clean_text(source.get(field, ""), normalized[field]).lower()
        if resolved in {"full", "compact"}:
            normalized[field] = resolved

    return normalized  # type: ignore[return-value]


def empty_player_impression_memory() -> PlayerImpressionMemory:
    return {
        "overall_impression": "",
        "relation_state": {},
        "key_events": [],
    }


def empty_character_memory_state(agent_type: str = "actor") -> CharacterMemoryState:
    del agent_type
    return {
        "pinned_long_term_memory": [],
        "long_term_memory": [],
        "consolidated_memory": [],
        "short_term_memory": [],
        "player_memory": empty_player_impression_memory(),
    }


def _truncate_text(value: Any, *, limit: int = 160) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _normalize_memory_priority(value: Any, *, fallback: str = "medium") -> str:
    priority = clean_text(value, fallback).lower()
    if priority in {"critical", "high", "medium"}:
        return priority
    return fallback


def _normalize_long_term_memory_items(value: Any, *, limit: int) -> list[LongTermMemoryEvent]:
    if not isinstance(value, list):
        return []

    normalized: list[LongTermMemoryEvent] = []
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            continue
        try:
            turn_recorded = int(raw_item.get("turn_recorded", 0) or 0)
        except (TypeError, ValueError):
            turn_recorded = 0
        event_summary = _truncate_text(raw_item.get("event_summary", ""))
        subjective_interpretation = _truncate_text(raw_item.get("subjective_interpretation", ""))
        belief_formed = _truncate_text(raw_item.get("belief_formed", ""))
        if not event_summary:
            continue
        normalized.append(
            {
                "turn_recorded": turn_recorded,
                "event_summary": event_summary,
                "subjective_interpretation": subjective_interpretation,
                "belief_formed": belief_formed,
                "priority": _normalize_memory_priority(raw_item.get("priority", "")),
                "tags": clean_str_list(raw_item.get("tags", []))[:6],
                "pin_candidate": bool(raw_item.get("pin_candidate", False)),
                "pin_reason": _truncate_text(raw_item.get("pin_reason", ""), limit=80),
                "linked_characters": clean_str_list(raw_item.get("linked_characters", []))[:4],
            }
        )
    return normalized[-limit:]


def _normalize_short_term_memory_items(value: Any, *, limit: int) -> list[ShortTermMemoryEvent]:
    if not isinstance(value, list):
        return []

    normalized: list[ShortTermMemoryEvent] = []
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            continue
        try:
            turn = int(raw_item.get("turn", 0) or 0)
        except (TypeError, ValueError):
            turn = 0
        actor = clean_text(raw_item.get("actor", "")) or None
        summary = _truncate_text(raw_item.get("summary", ""))
        if not summary:
            continue
        normalized.append(
            {
                "turn": turn,
                "chapter_id": clean_text(raw_item.get("chapter_id", "")),
                "scene_id": clean_text(raw_item.get("scene_id", "")),
                "location_id": clean_text(raw_item.get("location_id", "")),
                "actor": actor,
                "mode": clean_text(raw_item.get("mode", "")),
                "summary": summary,
            }
        )
    return normalized[-limit:]


def _normalize_player_impression_events(value: Any, *, limit: int) -> list[PlayerImpressionEvent]:
    if not isinstance(value, list):
        return []

    normalized: list[PlayerImpressionEvent] = []
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            continue
        try:
            turn = int(raw_item.get("turn", 0) or 0)
        except (TypeError, ValueError):
            turn = 0
        try:
            relation_delta = float(raw_item.get("relation_delta", 0.0) or 0.0)
        except (TypeError, ValueError):
            relation_delta = 0.0
        summary = _truncate_text(raw_item.get("summary", ""))
        impression = _truncate_text(raw_item.get("impression", ""))
        rationale = _truncate_text(raw_item.get("rationale", ""))
        if not summary:
            continue
        normalized.append(
            {
                "turn": turn,
                "summary": summary,
                "impression": impression,
                "rationale": rationale,
                "relation_delta": relation_delta,
                "tags": clean_str_list(raw_item.get("tags", []))[:4],
            }
        )
    return normalized[-limit:]


def _normalize_player_impression_memory(
    value: Any,
    *,
    limit: int,
) -> PlayerImpressionMemory:
    source = value if isinstance(value, Mapping) else {}
    relation_state_raw = source.get("relation_state", {})
    relation_state: dict[str, float] = {}
    if isinstance(relation_state_raw, Mapping):
        for key, raw_value in relation_state_raw.items():
            relation_key = clean_text(key)
            if not relation_key:
                continue
            try:
                relation_state[relation_key] = float(raw_value)
            except (TypeError, ValueError):
                continue

    key_events = _normalize_player_impression_events(
        source.get("key_events", []),
        limit=limit,
    )
    overall_impression = clean_text(source.get("overall_impression", ""))
    if not overall_impression and key_events:
        overall_impression = key_events[-1]["impression"]

    return {
        "overall_impression": overall_impression,
        "relation_state": relation_state,
        "key_events": key_events,
    }


def _normalize_consolidated_memory_items(
    value: Any,
    *,
    limit: int,
) -> list[ConsolidatedMemoryBlock]:
    if not isinstance(value, list):
        return []

    normalized: list[ConsolidatedMemoryBlock] = []
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            continue
        try:
            turn_start = int(raw_item.get("turn_start", 0) or 0)
        except (TypeError, ValueError):
            turn_start = 0
        try:
            turn_end = int(raw_item.get("turn_end", turn_start) or turn_start)
        except (TypeError, ValueError):
            turn_end = turn_start
        try:
            source_event_count = max(1, int(raw_item.get("source_event_count", 1) or 1))
        except (TypeError, ValueError):
            source_event_count = 1

        event_summary = _truncate_text(raw_item.get("event_summary", ""))
        if not event_summary:
            continue

        normalized.append(
            {
                "turn_start": turn_start,
                "turn_end": max(turn_start, turn_end),
                "topic": clean_text(raw_item.get("topic", ""), "ongoing_tension"),
                "event_summary": event_summary,
                "subjective_interpretation": _truncate_text(
                    raw_item.get("subjective_interpretation", "")
                ),
                "belief_formed": _truncate_text(raw_item.get("belief_formed", "")),
                "linked_characters": clean_str_list(raw_item.get("linked_characters", []))[:4],
                "source_event_count": source_event_count,
                "priority": _normalize_memory_priority(raw_item.get("priority", "")),
            }
        )
    return normalized[-limit:]


def _seed_long_term_memory_from_profile(
    actor_profile: Mapping[str, Any] | None,
    *,
    limit: int,
) -> list[LongTermMemoryEvent]:
    profile = actor_profile or {}
    if not profile:
        return []

    agent_type = clean_text(profile.get("agent_type", "actor"), "actor")
    background = _truncate_text(profile.get("background", ""))
    story_role = _truncate_text(profile.get("story_role", ""))
    l2_profile = profile.get("l2_profile", {}) if isinstance(profile.get("l2_profile"), Mapping) else {}
    l1_profile = profile.get("l1_profile", {}) if isinstance(profile.get("l1_profile"), Mapping) else {}

    seeds: list[LongTermMemoryEvent] = []
    if background:
        seeds.append(
            {
                "turn_recorded": 0,
                "event_summary": background,
                "subjective_interpretation": (
                    clean_text(l1_profile.get("core_conflict", ""))
                    or clean_text(l2_profile.get("core_drive", ""))
                    or story_role
                ),
                "belief_formed": (
                    clean_text(l1_profile.get("inner_need", ""))
                    or clean_text((l2_profile.get("behavior_rule", []) or [""])[0])
                    or story_role
                ),
                "priority": "high" if agent_type == "L1" else "medium",
                "tags": ["profile_seed"],
                "pin_candidate": False,
                "pin_reason": "",
                "linked_characters": [],
            }
        )

    if agent_type == "L1":
        conflict = clean_text(l1_profile.get("core_conflict", ""))
        outer_goal = clean_text(l1_profile.get("outer_goal", ""))
        inner_need = clean_text(l1_profile.get("inner_need", ""))
        if conflict or outer_goal or inner_need:
            seeds.append(
                {
                    "turn_recorded": 0,
                    "event_summary": conflict or outer_goal or story_role,
                    "subjective_interpretation": outer_goal or conflict,
                    "belief_formed": inner_need or conflict,
                    "priority": "high",
                    "tags": ["profile_seed", "l1_core"],
                    "pin_candidate": False,
                    "pin_reason": "",
                    "linked_characters": [],
                }
            )
        relationship_pressure = clean_str_list(l1_profile.get("relationship_pressure", []))
        if relationship_pressure:
            seeds.append(
                {
                    "turn_recorded": 0,
                    "event_summary": relationship_pressure[0],
                    "subjective_interpretation": conflict or relationship_pressure[0],
                    "belief_formed": inner_need or relationship_pressure[0],
                    "priority": "high",
                    "tags": ["profile_seed", "relationship_pressure"],
                    "pin_candidate": False,
                    "pin_reason": "",
                    "linked_characters": relationship_pressure[:1],
                }
            )
    elif agent_type == "L2":
        core_drive = clean_text(l2_profile.get("core_drive", ""))
        if core_drive:
            behavior_rule = clean_str_list(l2_profile.get("behavior_rule", []))
            seeds.append(
                {
                    "turn_recorded": 0,
                    "event_summary": story_role or core_drive,
                    "subjective_interpretation": core_drive,
                    "belief_formed": behavior_rule[0] if behavior_rule else core_drive,
                    "priority": "medium",
                    "tags": ["profile_seed", "l2_core"],
                    "pin_candidate": False,
                    "pin_reason": "",
                    "linked_characters": [],
                }
            )

    unique: list[LongTermMemoryEvent] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    for item in seeds:
        signature = (
            item["event_summary"],
            item["subjective_interpretation"],
            item["belief_formed"],
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique.append(item)
    return unique[:limit]


def ensure_character_memory_state(
    value: Any,
    *,
    actor_profile: Mapping[str, Any] | None = None,
) -> CharacterMemoryState:
    agent_type = clean_text((actor_profile or {}).get("agent_type", "actor"), "actor")
    memory_profile = normalize_character_memory_config(
        (actor_profile or {}).get("memory_profile", {}),
        agent_type=agent_type,
    )
    source = value if isinstance(value, Mapping) else {}
    pinned_long_term_memory = _normalize_long_term_memory_items(
        source.get("pinned_long_term_memory", []),
        limit=memory_profile["pinned_long_term_limit"],
    )
    long_term_memory = _normalize_long_term_memory_items(
        source.get("long_term_memory", []),
        limit=memory_profile["long_term_limit"],
    )
    if not long_term_memory:
        long_term_memory = _seed_long_term_memory_from_profile(
            actor_profile,
            limit=memory_profile["long_term_limit"],
        )

    return {
        "pinned_long_term_memory": pinned_long_term_memory[
            -memory_profile["pinned_long_term_limit"] :
        ],
        "long_term_memory": long_term_memory[-memory_profile["long_term_limit"] :],
        "consolidated_memory": _normalize_consolidated_memory_items(
            source.get("consolidated_memory", []),
            limit=memory_profile["consolidated_memory_limit"],
        ),
        "short_term_memory": _normalize_short_term_memory_items(
            source.get("short_term_memory", []),
            limit=memory_profile["short_term_limit"],
        ),
        "player_memory": _normalize_player_impression_memory(
            source.get("player_memory", {}),
            limit=memory_profile["player_memory_limit"],
        ),
    }
