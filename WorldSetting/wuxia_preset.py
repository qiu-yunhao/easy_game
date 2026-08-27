from __future__ import annotations

from WorldSetting.schema import WorldSetting, build_advance_condition, build_tier


def build_wuxia_world_setting() -> WorldSetting:
    return {
        "genre_tag": "wuxia", "tone": "古典江湖", "core_drive": "在江湖风波中守住本心，成为一代宗师。",
        "core_conflict": "门派恩怨与正邪之争交织，人人都要为自己的选择付出代价。",
        "power_system": "内功、招式、根骨与江湖声望。",
        "progression": {"system_name": "江湖地位", "current_tier_index": 0, "tiers": [
            build_tier(name="三流", advance_condition=build_advance_condition("event", description="在江湖立足并击败强敌", completion_marker="beat_second_rate")),
            build_tier(name="二流", advance_condition=build_advance_condition("event", description="解开一桩门派恩怨", completion_marker="beat_first_rate")),
            build_tier(name="一流", advance_condition=build_advance_condition("narrative")),
            build_tier(name="宗师", advance_condition=build_advance_condition("narrative")),
        ]},
        "protagonist": {"character_id": "player", "name": "无名侠客", "role": "protagonist", "start_tier_index": 0, "motivation": "查明师门旧案", "initial_relations": {}, "secrets": ["随身玉佩牵着一段旧案。"]},
        "key_characters": [{"character_id": "mentor", "name": "沈砚", "role": "mentor", "start_tier_index": 1, "motivation": "守住门派最后的传承"}],
        "factions_geography": [{"name": "青石镇", "kind": "location", "description": "江湖起点，商旅与消息交汇。"}, {"name": "听雨楼", "kind": "faction", "description": "表面经营酒楼，暗中搜罗江湖秘闻。"}],
        "title": "青石江湖", "summary": "一名无名侠客从小镇出发，踏入纠缠的江湖。", "source": "preset", "template_ref": [],
    }
