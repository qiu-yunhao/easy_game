from __future__ import annotations

import unittest

from WorldSetting.applier import apply_world_setting
from WorldSetting.schema import build_advance_condition, build_empty_world_setting, build_tier


def _wuxia_setting():
    ws = build_empty_world_setting()
    ws.update({
        "genre_tag": "wuxia", "tone": "古典", "core_drive": "成为一代宗师",
        "core_conflict": "正邪之争", "power_system": "内功招式", "source": "preset",
    })
    ws["progression"] = {
        "system_name": "江湖地位", "current_tier_index": 0,
        "tiers": [
            build_tier(name="三流", advance_condition=build_advance_condition(
                "event", completion_marker="beat_second")),
            build_tier(name="二流", advance_condition=build_advance_condition("narrative")),
        ],
    }
    ws["protagonist"] = {
        "character_id": "player", "name": "少年侠客", "start_tier_index": 0,
        "motivation": "闯荡江湖", "secrets": ["身世成谜"],
    }
    ws["key_characters"] = [
        {"character_id": "shifu", "name": "授业恩师", "role": "mentor", "start_tier_index": 1},
    ]
    ws["factions_geography"] = [
        {"name": "青石镇", "kind": "location", "description": "江湖起点。"},
    ]
    return ws


class WorldSettingApplierTests(unittest.TestCase):
    def test_maps_core_drive_and_location(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        self.assertEqual(result["opening_kwargs"]["cultivation_goal"], "成为一代宗师")
        self.assertEqual(result["opening_kwargs"]["location_id"], "青石镇")

    def test_maps_progression_to_realms(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        kw = result["opening_kwargs"]
        self.assertEqual(kw["current_player_realm"], "三流")
        self.assertEqual(kw["current_chapter_realm"], "三流")
        self.assertEqual(kw["next_chapter_realm"], "二流")

    def test_no_xianxia_hardcoding_in_output(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        blob = repr(result)
        for token in ("云峰入门台", "初入仙门", "修仙世界", "灵根"):
            self.assertNotIn(token, blob)

    def test_protagonist_profile_carries_name(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        player = result["character_profiles"]["player"]
        self.assertEqual(player["name"], "少年侠客")

    def test_key_characters_added_as_profiles(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        self.assertIn("shifu", result["character_profiles"])

    def test_last_tier_next_realm_equals_current(self) -> None:
        ws = _wuxia_setting()
        ws["progression"]["current_tier_index"] = 1
        result = apply_world_setting(ws)
        kw = result["opening_kwargs"]
        self.assertEqual(kw["current_player_realm"], "二流")
        self.assertEqual(kw["next_chapter_realm"], "二流")
