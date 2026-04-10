from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.builder import prepare_story_setup
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
    build_graph_dependencies,
)


class _TrackingPlaywright:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def plan_story_premise(self, **kwargs):
        del kwargs
        self._events.append("playwright:premise")
        return {
            "story_premise": "沈云烟初入山门，在修行与尘缘之间寻找自己的道。",
            "exploration_drive": "她要在宗门诸峰间探路修行，结识同道，逐步摸清自己的仙途。",
        }

    def plan_story_outline_brief(self, **kwargs):
        character_profiles = kwargs["character_profiles"]
        desired_chapter_count = int(kwargs["desired_chapter_count"])
        has_supporting_cast = "sect_elder_qingyuan" in character_profiles
        self._events.append(
            "playwright:outline_revised" if has_supporting_cast else "playwright:outline_draft"
        )

        first_title = "与青源长老结缘" if has_supporting_cast else "初入仙门"
        first_goal = "接引入门并确定修行方向" if has_supporting_cast else "独自摸索宗门规矩"
        first_summary = (
            "青源长老会在开篇引导沈云烟进入正轨，并把后续修行线索带入主线。"
            if has_supporting_cast
            else "沈云烟先独自安顿下来，主线中的关键引路人尚未明朗。"
        )

        outline = [
            {
                "chapter_id": "opening-arc-1",
                "title": first_title,
                "main_goal": first_goal,
                "summary": first_summary,
                "exploration_hooks": ["拜见执事", "辨认各峰方位"],
                "key_locations": ["云峰入门台", "宗门大殿"],
                "realm_stage": "练气一层",
                "next_realm": "练气二层",
            }
        ]
        for index in range(1, desired_chapter_count):
            outline.append(
                {
                    "chapter_id": f"opening-arc-{index + 1}",
                    "title": f"后续章节 {index + 1}",
                    "main_goal": f"推进修行见闻 {index + 1}",
                    "summary": f"围绕修行与探索继续展开第 {index + 1} 段历程。",
                    "exploration_hooks": [f"探索线索 {index + 1}"],
                    "key_locations": [f"外门区域 {index + 1}"],
                    "realm_stage": "练气一层",
                    "next_realm": "练气二层",
                }
            )
        return outline


class _TrackingActorCreateAgent:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def sync_supporting_cast(self, **kwargs):
        game_state = kwargs["game_state"]
        draft_title = str(game_state["plot"]["story_outline"][0]["title"])
        self._events.append(f"actor_create:{draft_title}")
        return {
            "sect_elder_qingyuan": {
                "character_id": "sect_elder_qingyuan",
                "name": "青源长老",
                "story_role": "负责接引新入门弟子的外门长老",
                "background": "常年坐镇宗门大殿，专司为新弟子解惑授引。",
                "base_style": "说话平和，却总能点中修行要害。",
                "persona": ["沉稳", "通达", "善于引导"],
                "planned_chapter_ids": ["opening-arc-1"],
                "profile_source": "actor_create_agent",
            }
        }


class StoryAuthoringSubgraphTests(unittest.TestCase):
    def test_prepare_story_setup_runs_draft_cast_and_revision_in_order(self) -> None:
        events: list[str] = []
        profiles = build_default_character_profiles()
        scene_config = build_default_scene_config()
        deps = build_graph_dependencies(
            "heuristic",
            character_profiles=profiles,
            scene_config=scene_config,
        )
        deps.playwright_agent = _TrackingPlaywright(events)
        deps.actor_create_agent = _TrackingActorCreateAgent(events)

        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )

        next_state = prepare_story_setup(state, deps)

        self.assertEqual(
            events,
            [
                "playwright:premise",
                "playwright:outline_draft",
                "actor_create:初入仙门",
                "playwright:outline_revised",
            ],
        )
        self.assertIn("sect_elder_qingyuan", deps.character_profiles)
        self.assertIn("sect_elder_qingyuan", next_state["characters"])
        self.assertEqual(deps.character_profiles["sect_elder_qingyuan"]["agent_type"], "L2")
        self.assertIn("l2_profile", deps.character_profiles["sect_elder_qingyuan"])
        self.assertTrue(
            deps.character_profiles["sect_elder_qingyuan"]["l2_profile"]["core_drive"]
        )
        self.assertEqual(next_state["plot"]["story_outline_source"], "playwright_agent_cast_revised")
        self.assertEqual(next_state["plot"]["story_outline"][0]["title"], "与青源长老结缘")
        self.assertTrue(next_state["history"])


if __name__ == "__main__":
    unittest.main()
