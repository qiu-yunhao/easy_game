from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict

from StoryStateUtils import clean_str_list, clean_text


MemoryDepth = Literal["full", "compact"]


class CharacterMemoryConfig(TypedDict):
    player_memory_limit: int
    player_memory_depth: MemoryDepth


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
    player_memory: PlayerImpressionMemory


L1_MEMORY_CONFIG: CharacterMemoryConfig = {
    "player_memory_limit": 8,
    "player_memory_depth": "full",
}

ACTOR_MEMORY_CONFIG: CharacterMemoryConfig = {
    "player_memory_limit": 3,
    "player_memory_depth": "compact",
}


def memory_config_for_agent_type(agent_type: str) -> CharacterMemoryConfig:
    if agent_type == "L1":
        return dict(L1_MEMORY_CONFIG)
    return dict(ACTOR_MEMORY_CONFIG)


def normalize_character_memory_config(
    value: Any,
    *,
    agent_type: str = "actor",
) -> CharacterMemoryConfig:
    source = value if isinstance(value, Mapping) else {}
    normalized = memory_config_for_agent_type(agent_type)
    try:
        normalized["player_memory_limit"] = max(
            1, int(source.get("player_memory_limit", normalized["player_memory_limit"]) or normalized["player_memory_limit"])
        )
    except (TypeError, ValueError):
        pass
    depth = clean_text(source.get("player_memory_depth", ""), normalized["player_memory_depth"]).lower()
    if depth in {"full", "compact"}:
        normalized["player_memory_depth"] = depth
    return normalized  # type: ignore[return-value]


def empty_player_impression_memory() -> PlayerImpressionMemory:
    return {
        "overall_impression": "",
        "relation_state": {},
        "key_events": [],
    }


def empty_character_memory_state(agent_type: str = "actor") -> CharacterMemoryState:
    del agent_type
    return {"player_memory": empty_player_impression_memory()}


def _truncate_text(value: Any, *, limit: int = 160) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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
    return {
        "player_memory": _normalize_player_impression_memory(
            source.get("player_memory", {}),
            limit=memory_profile["player_memory_limit"],
        ),
    }
