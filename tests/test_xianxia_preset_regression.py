from __future__ import annotations

import unittest

from Cultivation.realms import REALM_ORDER
from WorldSetting.validation import validate_world_setting
from WorldSetting.xianxia_preset import build_xianxia_world_setting

import sys
import types

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from session_bootstrap import build_default_state  # noqa: E402


class XianxiaPresetTests(unittest.TestCase):
    def test_preset_is_valid(self) -> None:
        validate_world_setting(build_xianxia_world_setting())

    def test_preset_tiers_follow_realm_order(self) -> None:
        ws = build_xianxia_world_setting()
        tier_names = [t["name"] for t in ws["progression"]["tiers"]]
        self.assertEqual(tier_names, list(REALM_ORDER))

    def test_preset_metadata(self) -> None:
        ws = build_xianxia_world_setting()
        self.assertEqual(ws["genre_tag"], "xianxia")
        self.assertEqual(ws["source"], "preset")
        self.assertIn("长生", ws["core_drive"])
        self.assertEqual(ws["progression"]["current_tier_index"], 0)

    def test_each_tier_has_event_condition_except_last(self) -> None:
        ws = build_xianxia_world_setting()
        tiers = ws["progression"]["tiers"]
        for tier in tiers[:-1]:
            self.assertEqual(tier["advance_condition"]["type"], "event")
        self.assertEqual(tiers[-1]["advance_condition"]["type"], "narrative")


class DefaultStateRegressionTests(unittest.TestCase):
    def test_default_state_opening_unchanged(self) -> None:
        state = build_default_state()
        self.assertEqual(state["scene"]["location_id"], "云峰入门台")
        self.assertEqual(state["scene"]["beat"], "初入仙门")
        self.assertEqual(state["plot"]["current_player_realm"], "练气一层")
        self.assertIn("修仙", state["plot"]["cultivation_goal"])
