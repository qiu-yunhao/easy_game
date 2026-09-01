from __future__ import annotations

from unittest import TestCase

from WorldSetting.additions import append_world_additions
from WorldSetting.infinite_flow_preset import build_infinite_flow_world_setting
from WorldSetting.wuxia_preset import build_wuxia_world_setting
from WorldSetting.xianxia_preset import build_xianxia_world_setting
from web_session import SessionConfig, WebGameSession


class TestWriterReview(TestCase):
    def test_world_additions_only_append(self) -> None:
        result = append_world_additions(
            {"factions_geography": [{"name": "旧城", "kind": "location"}], "incremental_facts": ["旧事实"]},
            {"locations": ["旧城", "新城"], "facts": ["旧事实", "新伏笔"]},
        )
        self.assertEqual(result["incremental_facts"], ["旧事实", "新伏笔"])
        self.assertEqual([item["name"] for item in result["factions_geography"]], ["旧城", "新城"])

    def test_assistant_mode_stages_and_approves_writer_package(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))
        state = session.reset(experience_mode="assistant")
        self.assertTrue(state["writer_review_pending"])
        self.assertTrue(state["player"]["auto_mode"])

        draft = session.get_writer_review()["draft"]
        draft["world_additions"]["facts"] = ["新规则只从本章起生效。"]
        approved = session.approve_writer_review(draft)
        self.assertFalse(approved["writer_review_pending"])
        self.assertIn("新规则只从本章起生效。", approved["world_summary"]["incremental_facts"])

    def test_pending_review_rejects_player_action_before_advancing(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))
        session.reset(experience_mode="assistant")

        with self.assertRaisesRegex(RuntimeError, "编剧方案尚待审阅"):
            session.apply_player_action("绕过审阅直接行动")

    def test_presets_include_an_empty_incremental_fact_list(self) -> None:
        for build in (build_xianxia_world_setting, build_wuxia_world_setting, build_infinite_flow_world_setting):
            self.assertEqual(build()["incremental_facts"], [])
