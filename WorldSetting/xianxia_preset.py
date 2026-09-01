from __future__ import annotations

from Cultivation.realms import REALM_ORDER
from WorldSetting.schema import (
    ProgressionSystem,
    WorldSetting,
    build_advance_condition,
    build_tier,
)


def _build_realm_progression() -> ProgressionSystem:
    tiers = []
    for index, realm in enumerate(REALM_ORDER):
        if index < len(REALM_ORDER) - 1:
            condition = build_advance_condition(
                "event",
                description=f"突破至{REALM_ORDER[index + 1]}",
                completion_marker=f"breakthrough_{REALM_ORDER[index + 1]}",
            )
        else:
            condition = build_advance_condition("narrative")
        tiers.append(build_tier(name=realm, advance_condition=condition))
    return {"system_name": "修为境界", "current_tier_index": 0, "tiers": tiers}


def build_xianxia_world_setting() -> WorldSetting:
    return {
        "genre_tag": "xianxia",
        "tone": "克制古典",
        "core_drive": "修仙求长生，在残酷仙途上立足并求索大道。",
        "core_conflict": "资源稀缺与弱肉强食的修行世界，处处试探与竞争。",
        "power_system": "以灵气为本，讲究灵根资质、境界修为与功法道术。",
        "progression": _build_realm_progression(),
        "protagonist": {
            "character_id": "player",
            "name": "无名修士",
            "role": "protagonist",
            "start_tier_index": 0,
            "motivation": "窥见天命真相，在仙途立足。",
            "initial_relations": {},
            "secrets": ["心底放不下想要窥见天命真相的执念。"],
        },
        "key_characters": [],
        "factions_geography": [
            {"name": "云峰入门台", "kind": "location", "description": "初入仙门的落脚处。"},
        ],
        "title": "仙途初入",
        "summary": "出身凡俗，因机缘叩开仙门，踏入修行世界。",
        "source": "preset",
        "template_ref": [],
        "incremental_facts": [],
    }
