from __future__ import annotations

from WorldSetting.schema import WorldSetting, build_advance_condition, build_tier


def build_infinite_flow_world_setting() -> WorldSetting:
    return {
        "genre_tag": "infinite_flow", "tone": "悬疑压迫", "core_drive": "穿过不断开启的副本，找回离开轮回空间的资格。",
        "core_conflict": "规则、队友与生存资源都在逼迫每个人暴露真实选择。",
        "power_system": "副本规则、轮回积分、权限与临场协作。",
        "progression": {"system_name": "轮回权限", "current_tier_index": 0, "tiers": [
            build_tier(name="新人", advance_condition=build_advance_condition("threshold", counter_key="cleared_rounds", target_value=3)),
            build_tier(name="正式行者", advance_condition=build_advance_condition("threshold", counter_key="cleared_rounds", target_value=8)),
            build_tier(name="资深行者", advance_condition=build_advance_condition("narrative")),
        ]},
        "protagonist": {"character_id": "player", "name": "新入局者", "role": "protagonist", "start_tier_index": 0, "motivation": "带着失去的记忆活下去", "initial_relations": {}, "secrets": ["记忆里藏着一次失败轮回的残片。"]},
        "key_characters": [{"character_id": "teammate", "name": "林雾", "role": "teammate", "start_tier_index": 0, "motivation": "寻找失散的搭档"}],
        "factions_geography": [{"name": "废弃医院", "kind": "location", "description": "第一场副本的封闭入口。"}, {"name": "轮回终端", "kind": "faction", "description": "发布规则却从不解释目的的系统。"}],
        "title": "轮回入口", "summary": "新人被投进第一场规则副本，必须决定信任谁。", "source": "preset", "template_ref": [], "incremental_facts": [],
    }
