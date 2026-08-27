from __future__ import annotations

import unittest

from WorldSetting import WorldBuilderWorkflow
from WorldSetting.schema import build_advance_condition, build_tier
from WorldSetting.validation import WorldSettingError


class WorldBuilderWorkflowTests(unittest.TestCase):
    def test_empty_draft_advances_one_field_per_answer(self) -> None:
        flow = WorldBuilderWorkflow()
        self.assertEqual(flow.view()["next_field"], "genre_tag")
        self.assertEqual(flow.answer("wuxia")["next_field"], "tone")
        self.assertEqual(flow.answer("苍凉")["next_field"], "core_drive")

    def test_complete_draft_is_validated(self) -> None:
        flow = WorldBuilderWorkflow()
        answers = [
            "wuxia", "古典", "成为宗师", "正邪相争", "内功与招式",
            {"system_name": "江湖地位", "current_tier_index": 0, "tiers": [
                build_tier(name="三流", advance_condition=build_advance_condition("narrative")),
            ]},
            {"character_id": "player", "name": "无名侠客"}, [],
            [{"name": "青石镇", "kind": "location", "description": "开场"}], "江湖", "开局",
        ]
        for answer in answers:
            result = flow.answer(answer)
        self.assertEqual(result["status"], "complete")

    def test_structured_field_rejects_plain_text(self) -> None:
        flow = WorldBuilderWorkflow(genre_tag="wuxia")
        for answer in ("古典", "成为宗师", "正邪相争", "内功"):
            flow.answer(answer)
        with self.assertRaises(WorldSettingError):
            flow.answer("not a progression")


if __name__ == "__main__":
    unittest.main()
