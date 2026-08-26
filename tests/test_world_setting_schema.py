from __future__ import annotations

import unittest

from WorldSetting.schema import (
    ADVANCE_CONDITION_TYPES,
    build_empty_world_setting,
    build_tier,
    build_advance_condition,
)


class WorldSettingSchemaTests(unittest.TestCase):
    def test_empty_world_setting_has_locked_and_incremental_fields(self) -> None:
        ws = build_empty_world_setting()
        for key in (
            "genre_tag", "tone", "core_drive", "core_conflict",
            "power_system", "progression", "protagonist",
            "key_characters", "factions_geography",
            "title", "summary", "source", "template_ref",
        ):
            self.assertIn(key, ws)
        self.assertEqual(ws["progression"]["tiers"], [])
        self.assertEqual(ws["key_characters"], [])
        self.assertEqual(ws["template_ref"], [])

    def test_advance_condition_types_are_the_four_kinds(self) -> None:
        self.assertEqual(
            set(ADVANCE_CONDITION_TYPES),
            {"event", "threshold", "narrative", "composite"},
        )

    def test_build_tier_and_condition_shape(self) -> None:
        cond = build_advance_condition("event", description="筑基仪式", completion_marker="foundation_built")
        tier = build_tier(name="练气", advance_condition=cond)
        self.assertEqual(tier["name"], "练气")
        self.assertEqual(tier["advance_condition"]["type"], "event")
        self.assertEqual(tier["advance_condition"]["completion_marker"], "foundation_built")
