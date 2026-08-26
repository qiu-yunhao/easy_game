from __future__ import annotations

import unittest

from WorldSetting.schema import (
    build_advance_condition,
    build_empty_world_setting,
    build_tier,
)
from WorldSetting.validation import WorldSettingError, validate_world_setting


def _valid_setting():
    ws = build_empty_world_setting()
    ws["genre_tag"] = "wuxia"
    ws["tone"] = "古典"
    ws["core_drive"] = "成为一代宗师"
    ws["core_conflict"] = "正邪门派之争"
    ws["power_system"] = "内功与招式"
    ws["progression"] = {
        "system_name": "江湖地位",
        "current_tier_index": 0,
        "tiers": [
            build_tier(name="三流", advance_condition=build_advance_condition(
                "event", description="击败一名二流高手", completion_marker="beat_second_rate")),
            build_tier(name="二流", advance_condition=build_advance_condition("narrative")),
        ],
    }
    ws["protagonist"] = {"character_id": "player", "name": "无名", "start_tier_index": 0}
    return ws


class WorldSettingValidationTests(unittest.TestCase):
    def test_valid_setting_passes(self) -> None:
        validate_world_setting(_valid_setting())

    def test_missing_core_drive_fails(self) -> None:
        ws = _valid_setting()
        ws["core_drive"] = ""
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_empty_tiers_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"] = []
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_current_tier_index_out_of_range_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["current_tier_index"] = 5
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_illegal_condition_type_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"]["type"] = "bogus"
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_threshold_condition_requires_counter_and_target(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"] = build_advance_condition("threshold")
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_composite_requires_valid_sub_conditions(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"] = build_advance_condition(
            "composite", op="AND", sub_conditions=[build_advance_condition("bogus")]
        )
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)
