from __future__ import annotations

from typing import Any

from WorldSetting.schema import CharacterSeed, WorldSetting


def _seed_to_profile(seed: CharacterSeed, *, default_id: str) -> dict[str, Any]:
    character_id = str(seed.get("character_id", "") or default_id)
    return {
        "character_id": character_id,
        "name": str(seed.get("name", "") or character_id),
        "background": str(seed.get("motivation", "") or ""),
        "persona": [],
        "base_style": "",
        "secrets": list(seed.get("secrets", []) or []),
        "base_relationship": dict(seed.get("initial_relations", {}) or {}),
    }


def apply_world_setting(world_setting: WorldSetting) -> dict[str, Any]:
    """把 WorldSetting 映射成 build_opening_state 所需 kwargs + character_profiles 覆盖。

    不直接构建 state,保持纯函数;由 session_bootstrap 组装。
    """
    progression = world_setting["progression"]
    tiers = progression["tiers"]
    current_index = int(progression.get("current_tier_index", 0) or 0)
    current_tier = tiers[current_index]
    next_tier = tiers[min(current_index + 1, len(tiers) - 1)]

    factions = world_setting.get("factions_geography", []) or []
    opening_location = str(factions[0]["name"]) if factions else "开场之地"

    protagonist = world_setting.get("protagonist", {}) or {}
    profiles: dict[str, dict[str, Any]] = {
        "player": _seed_to_profile(protagonist, default_id="player"),
    }
    for index, seed in enumerate(world_setting.get("key_characters", []) or []):
        profile = _seed_to_profile(seed, default_id=f"npc_{index}")
        profiles[profile["character_id"]] = profile

    scene_notes = [
        f"世界基调：{world_setting.get('tone', '')}",
        f"核心冲突：{world_setting.get('core_conflict', '')}",
        f"力量体系：{world_setting.get('power_system', '')}",
    ]

    return {
        "opening_kwargs": {
            "location_id": opening_location,
            "cultivation_goal": world_setting.get("core_drive", ""),
            "current_player_realm": current_tier["name"],
            "current_chapter_realm": current_tier["name"],
            "next_chapter_realm": next_tier["name"],
            "scene_notes": scene_notes,
        },
        "character_profiles": profiles,
    }
