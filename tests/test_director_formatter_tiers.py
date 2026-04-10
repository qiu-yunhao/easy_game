from __future__ import annotations

import json
import unittest

from Director.DirectorFormatter import DirectorFormatter
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state
from History.GameMemory import empty_memory_state
from ScenePlan import empty_scene_plan


def _extract_payload(instruction: str) -> dict[str, object]:
    _, payload = instruction.split("\n\n", 1)
    return json.loads(payload)


class DirectorFormatterTierTests(unittest.TestCase):
    def test_build_instruction_includes_l1_l2_stage_contract_and_grouping(self) -> None:
        state = create_initial_game_state(
            plot={
                "chapter_id": "chapter-1",
                "scene_id": "scene-1",
                "current_scene_index": 0,
                "chapter_goal": "查清宗门内鬼",
                "current_chapter_hooks": [],
                "plot_flags": {},
                "story_premise": "山门之内暗流涌动。",
                "exploration_drive": "主角需要辨明谁在操控局势。",
                "story_outline": [],
                "current_chapter_title": "风起青霄",
                "current_chapter_overview": "旧案复起，宗门内外都有人心浮动。",
                "active_outline_chapter_id": "",
                "story_premise_source": "",
                "story_outline_source": "",
                "chapter_expansion_source": "",
                "story_foundation_source": "",
                "chapter_focus_source": "",
                "scene_candidates_source": "",
                "current_chapter_index": 0,
                "cultivation_goal": "",
                "current_player_realm": "",
                "current_chapter_realm": "",
                "next_chapter_realm": "",
                "chapter_transition_requirement": "",
                "completed_chapters": [],
            },
            scene={
                "location_id": "宗门议事堂",
                "time_tag": "夜",
                "beat": "试探与对峙并起",
                "tension": 0.62,
                "focus_character": "l1_rival",
                "on_stage": ["player", "l1_rival", "l2_guard"],
                "allow_interrupt": True,
                "suppressed": [],
            },
            characters={
                "player": create_character_runtime_state(intent="保持警惕"),
                "l1_rival": create_character_runtime_state(intent="逼主角先表态"),
                "l2_guard": create_character_runtime_state(intent="维护秩序并观察风向"),
                "l2_scribe": create_character_runtime_state(intent="在需要时补充案卷信息"),
            },
            scene_plan={
                **empty_scene_plan(),
                "scene_goal": "逼出一个会改变关系站位的表态",
            },
            memory=empty_memory_state(),
            player=create_player_state(controlled_character="player"),
        )
        character_profiles = {
            "player": {
                "character_id": "player",
                "name": "沈云烟",
                "agent_type": "actor",
                "persona": ["谨慎"],
                "base_style": "先看局势再出手",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "杂灵根",
                "realm": "练气一层",
                "main_technique": "基础吐纳术",
            },
            "l1_rival": {
                "character_id": "l1_rival",
                "name": "顾长渊",
                "agent_type": "L1",
                "story_role": "宗门新秀，也是主角的核心对手。",
                "persona": ["克制", "锋利"],
                "base_style": "少言但压迫感强",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "金灵根",
                "realm": "筑基初期",
                "main_technique": "庚金剑诀",
                "l1_profile": {
                    "core_conflict": "想守住家族荣耀，又厌恶被家族安排。",
                    "outer_goal": "逼出主角立场",
                    "inner_need": "证明自己的选择并非受人摆布",
                    "contradiction_axes": ["责任 / 自由"],
                    "relationship_pressure": ["家族长老的期待"],
                },
            },
            "l2_guard": {
                "character_id": "l2_guard",
                "name": "执堂护卫",
                "agent_type": "L2",
                "story_role": "议事堂中维持秩序的护卫。",
                "persona": ["谨慎", "守礼"],
                "base_style": "答话简洁",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "杂灵根",
                "realm": "练气四层",
                "main_technique": "护堂枪术",
                "l2_profile": {
                    "core_drive": "保住差事",
                    "judgement_preference": ["服从权威"],
                    "behavior_rule": ["先稳住秩序", "再看谁占上风"],
                    "speech_style": ["简洁克制"],
                    "personality_tags": ["谨慎", "现实"],
                },
            },
            "l2_scribe": {
                "character_id": "l2_scribe",
                "name": "执卷书吏",
                "agent_type": "L2",
                "story_role": "负责誊录案卷与补充旧档。",
                "persona": ["细致"],
                "base_style": "说话慢而稳",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "杂灵根",
                "realm": "练气二层",
                "main_technique": "静心抄录诀",
                "l2_profile": {
                    "core_drive": "别在自己手里出差错",
                    "judgement_preference": ["先看证据"],
                    "behavior_rule": ["先核对旧档"],
                    "speech_style": ["谨慎说明"],
                    "personality_tags": ["细致", "低调"],
                },
                "planned_chapter_ids": ["chapter-1"],
            },
        }

        instruction = DirectorFormatter().build_instruction(
            state=state,
            character_profiles=character_profiles,
            character_roster_snapshot={
                "summary": {
                    "total_L1": 1,
                    "max_L1": 6,
                    "total_L2": 2,
                    "max_L2": 15,
                    "total_ActorAgent": 3,
                },
                "characters": [],
                "decision_hints": {},
            },
        )
        payload = _extract_payload(instruction)

        self.assertIn("tiered_directing_contract", payload)
        self.assertIn("conflict_transition_profile", payload)
        self.assertIn("loaded_tool_skills", payload)
        self.assertEqual(
            [skill["skill_id"] for skill in payload["loaded_tool_skills"]],
            ["scene_skill", "character_roster_skill"],
        )
        self.assertIn("available_tools", payload)
        self.assertEqual(
            [tool["name"] for tool in payload["available_tools"]],
            ["query_scene_context", "query_character_roster"],
        )
        self.assertIn("scene_context_snapshot", payload)
        self.assertIn("character_roster_snapshot", payload)
        self.assertEqual(payload["character_roster_snapshot"]["summary"]["total_L1"], 1)
        self.assertEqual(payload["stage_tiers"]["on_stage_l1"], ["l1_rival"])
        self.assertEqual(payload["stage_tiers"]["on_stage_l2"], ["l2_guard"])
        self.assertIn("l2_scribe", payload["stage_tiers"]["available_l2_candidates"])
        self.assertEqual(payload["scene_context_snapshot"]["scene"]["on_stage"], ["player", "l1_rival", "l2_guard"])

        on_stage_profiles = {item["character_id"]: item for item in payload["characters_on_stage"]}
        self.assertEqual(on_stage_profiles["l1_rival"]["agent_type"], "L1")
        self.assertIn("l1_profile", on_stage_profiles["l1_rival"])
        self.assertEqual(on_stage_profiles["l2_guard"]["agent_type"], "L2")
        self.assertIn("l2_profile", on_stage_profiles["l2_guard"])
        self.assertIn("scene_support_bias", on_stage_profiles["l2_guard"])

        available_profiles = {item["character_id"]: item for item in payload["available_stage_candidates"]}
        self.assertEqual(available_profiles["l2_scribe"]["agent_type"], "L2")
        self.assertIn("planned_chapter_ids", available_profiles["l2_scribe"])
        self.assertTrue(payload["tiered_directing_contract"]["selection_order"])


if __name__ == "__main__":
    unittest.main()
