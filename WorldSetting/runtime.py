from __future__ import annotations

from typing import Any


def world_context(world_setting: dict[str, Any] | None) -> dict[str, str]:
    """Return the small, stable subset of a setting that agents need."""
    setting = world_setting or {}
    progression = setting.get("progression") or {}
    facts = [str(item).strip() for item in setting.get("incremental_facts", []) if str(item).strip()]
    places = [str(item.get("name", "") or "").strip() for item in setting.get("factions_geography", []) if isinstance(item, dict)]
    return {
        "genre_tag": str(setting.get("genre_tag", "") or ""),
        "tone": str(setting.get("tone", "") or ""),
        "core_drive": str(setting.get("core_drive", "") or ""),
        "core_conflict": str(setting.get("core_conflict", "") or ""),
        "power_system": str(setting.get("power_system", "") or ""),
        "progression_name": str(progression.get("system_name", "") or ""),
        "incremental_facts": "；".join(facts[-8:]),
        "known_places": "、".join(place for place in places[-8:] if place),
    }


def tier_pair(world_setting: dict[str, Any], current_index: int | None = None) -> tuple[str, str]:
    progression = world_setting.get("progression") or {}
    tiers = progression.get("tiers") or []
    if not tiers:
        return "", ""
    index = progression.get("current_tier_index", 0) if current_index is None else current_index
    index = max(0, min(int(index), len(tiers) - 1))
    current = str(tiers[index].get("name", "") or "")
    following = str(tiers[min(index + 1, len(tiers) - 1)].get("name", "") or "")
    return current, following


def chapter_tier_sequence(world_setting: dict[str, Any], start_tier: str, count: int) -> list[tuple[str, str]]:
    tiers = (world_setting.get("progression") or {}).get("tiers") or []
    names = [str(tier.get("name", "") or "") for tier in tiers]
    if not names or count <= 0:
        return []
    try:
        start = names.index(start_tier)
    except ValueError:
        start = int((world_setting.get("progression") or {}).get("current_tier_index", 0) or 0)
    return [(names[min(start + index, len(names) - 1)], names[min(start + index + 1, len(names) - 1)]) for index in range(count)]


def transition_requirement(world_setting: dict[str, Any], current_tier: str, next_tier: str) -> str:
    if not current_tier or current_tier == next_tier:
        return "当前已处于该体系的最高阶段，后续由叙事节奏决定。"
    tiers = (world_setting.get("progression") or {}).get("tiers") or []
    condition: dict[str, Any] = {}
    for tier in tiers:
        if str(tier.get("name", "") or "") == current_tier:
            condition = tier.get("advance_condition") or {}
            break
    kind = condition.get("type")
    if kind == "event":
        return str(condition.get("description", "") or f"完成通往{next_tier}的关键事件。")
    if kind == "threshold":
        return f"{condition.get('counter_key', '进度')}达到 {condition.get('target_value', 0)}，晋升至{next_tier}。"
    if kind == "composite":
        return f"满足通往{next_tier}的组合条件。"
    return f"在叙事中获得晋升至{next_tier}的契机。"
