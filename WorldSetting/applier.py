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

    # CharacterProfile keeps legacy field names for save compatibility.  Supplying
    # neutral values here prevents non-xianxia worlds from inheriting xianxia text.
    for profile in profiles.values():
        profile.update({
            "spiritual_root": world_setting.get("power_system", "") or "世界资质",
            "realm": current_tier["name"],
            "main_technique": world_setting.get("power_system", "") or "基础能力",
        })

    scene_notes = [
        f"世界基调：{world_setting.get('tone', '')}",
        f"核心冲突：{world_setting.get('core_conflict', '')}",
        f"力量体系：{world_setting.get('power_system', '')}",
    ]

    return {
        "opening_kwargs": {
            "location_id": opening_location,
            "cultivation_goal": world_setting.get("core_drive", ""),
            # 注意:这里的 realm 是通用阶梯的 tier 名(如 xianxia preset 的"炼气"),
            # 与现有 Cultivation 数值链路用的子境界全名("练气一层")不是同一格式。
            # 阶段2 默认路径仍走 player_context 的全名,未消费这三个字段;将来若要接入
            # 数值链路,必须先把 tier 名映射回 Cultivation 的 realm 全名,否则会静默断链。
            "current_player_realm": current_tier["name"],
            "current_chapter_realm": current_tier["name"],
            "next_chapter_realm": next_tier["name"],
            "scene_notes": scene_notes,
            "world_setting": world_setting,
        },
        "character_profiles": profiles,
    }
