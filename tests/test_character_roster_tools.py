from __future__ import annotations

import json
import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from CharacterRosterTools import CharacterRosterToolRuntime
from GameState import create_character_runtime_state
from Persistence.Store import GameSaveStore
from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter
from session_bootstrap import build_default_character_profiles, build_default_scene_config, build_default_state
from web_session import SessionConfig, WebGameSession


def _extract_payload(instruction: str) -> dict[str, object]:
    _, payload = instruction.split("\n\n", 1)
    return json.loads(payload)


def _build_roster_session() -> WebGameSession:
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.story_initialized = True
    session.state["player"]["enabled"] = True
    session.state["player"]["controlled_character"] = "player"
    session.state["scene"]["location_id"] = "云岚山门"
    session.state["scene"]["focus_character"] = "arch_rival"
    session.state["scene"]["on_stage"] = ["player", "arch_rival", "mentor_liu", "herb_vendor"]
    session.state["runtime"]["eligible_actors"] = ["player", "arch_rival", "mentor_liu", "herb_vendor"]
    session.state["runtime"]["turn_index"] = 3
    session.state["plot"]["chapter_id"] = "chapter-2"
    session.state["plot"]["current_chapter_title"] = "山门争衡"
    session.state["plot"]["chapter_goal"] = "先看清宗门内外的人心与站位"
    session.state["plot"]["story_outline"] = [
        {
            "chapter_id": "chapter-2",
            "title": "山门争衡",
            "main_goal": "先看清宗门内外的人心与站位",
            "summary": "门前试探正在不断加重。",
            "exploration_hooks": [],
            "key_locations": ["云岚山门"],
            "realm_stage": "练气",
            "next_realm": "筑基",
        }
    ]

    session.character_profiles["arch_rival"] = {
        "character_id": "arch_rival",
        "name": "顾长渊",
        "story_layer": "L1",
        "agent_type": "L1",
        "background": "宗门里的年轻强者。",
        "story_role": "长期对手",
        "base_relationship": {"player": -2.0},
        "persona": ["克制", "锋利"],
        "base_style": "沉静而带压迫感",
        "spiritual_root": "金灵根",
        "realm": "筑基初期",
        "main_technique": "庚金剑诀",
        "gender": "",
        "race": "",
        "secrets": [],
        "is_active": True,
        "is_offstage": False,
    }
    session.character_profiles["mentor_liu"] = {
        "character_id": "mentor_liu",
        "name": "柳前辈",
        "story_layer": "L1",
        "agent_type": "L1",
        "background": "暂住在山门外的引路人。",
        "story_role": "阶段引路者",
        "base_relationship": {"player": 2.0},
        "persona": ["沉稳"],
        "base_style": "言语克制",
        "spiritual_root": "木灵根",
        "realm": "筑基",
        "main_technique": "清风诀",
        "gender": "",
        "race": "",
        "occupation": "引路人",
        "secrets": [],
        "is_active": True,
        "is_offstage": False,
    }
    session.character_profiles["herb_vendor"] = {
        "character_id": "herb_vendor",
        "name": "药铺掌柜",
        "story_layer": "actor",
        "agent_type": "actor",
        "background": "常年在山门外兜售灵药。",
        "story_role": "提供丹药与消息的功能角色",
        "base_relationship": {"player": 0.5},
        "persona": ["精明", "圆滑"],
        "base_style": "说话像在算账",
        "spiritual_root": "",
        "realm": "练气三层",
        "main_technique": "识药诀",
        "gender": "",
        "race": "",
        "occupation": "药铺掌柜",
        "secrets": [],
        "is_active": True,
        "is_offstage": False,
    }
    session.state["characters"]["arch_rival"] = create_character_runtime_state(
        intent="压住来者气势",
        relationship_delta={"player": -1.0},
    )
    session.state["characters"]["mentor_liu"] = create_character_runtime_state(
        intent="观察争执走向",
        relationship_delta={"player": 1.5},
    )
    session.state["characters"]["herb_vendor"] = create_character_runtime_state(
        intent="看看有没有生意可做",
        relationship_delta={"player": 0.25},
    )
    return session


class CharacterRosterToolTests(unittest.TestCase):
    def test_save_store_query_character_roster_returns_layer_summary_and_filter(self) -> None:
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()
        session = _build_roster_session()
        user = store.ensure_user(username="tester", display_name="测试玩家")
        created = store.create_new_game(
            user_id=user["id"],
            slot_name="山门档",
            session_snapshot=session.export_runtime_snapshot(),
        )
        player_id = created["player"]["id"]

        roster = store.query_character_roster(
            user_id=user["id"],
            player_id=player_id,
            layer_filter="all",
        )
        actor_only = store.query_character_roster(
            user_id=user["id"],
            player_id=player_id,
            layer_filter="ActorAgent",
        )

        self.assertEqual(roster["summary"]["total_L1"], 2)
        self.assertEqual(roster["summary"]["total_L2"], 0)
        self.assertEqual(roster["summary"]["total_ActorAgent"], 1)
        self.assertEqual(roster["decision_hints"]["L1"]["max_count"], 6)
        self.assertTrue(roster["decision_hints"]["L1"]["allowed"])
        self.assertEqual([item["layer"] for item in actor_only["characters"]], ["ActorAgent"])
        self.assertEqual(actor_only["characters"][0]["display_name"], "药铺掌柜")
        self.assertTrue(actor_only["characters"][0]["linked_to_player"])

    def test_character_roster_runtime_falls_back_to_runtime_profiles(self) -> None:
        profiles = _build_roster_session().character_profiles
        runtime = CharacterRosterToolRuntime(
            resolve_store=lambda: None,
            resolve_context=lambda: {"user_id": None, "player_id": None},
            resolve_profiles=lambda: profiles,
        )

        roster = runtime.query_character_roster({"layer_filter": "L1"})

        self.assertEqual(roster["source"], "runtime_fallback")
        self.assertEqual(roster["summary"]["total_L1"], 2)
        self.assertEqual(roster["summary"]["filtered_total"], 2)
        self.assertEqual(roster["characters"][0]["layer"], "L1")

    def test_playwright_formatter_includes_character_roster_snapshot_payload(self) -> None:
        profiles = build_default_character_profiles(
            {
                "name": "沈云烟",
                "background": "带着未解的旧缘来到山门前。",
            }
        )
        state = build_default_state(
            player_character="player",
            character_profiles=profiles,
        )
        formatter = PlaywrightFormatter()

        instruction = formatter.build_story_outline_brief_instruction(
            game_state=state,
            scene_config=build_default_scene_config("xianxia_default"),
            character_profiles=profiles,
            desired_chapter_count=3,
            character_roster_snapshot={
                "summary": {
                    "total_L1": 2,
                    "max_L1": 6,
                    "total_L2": 4,
                    "max_L2": 15,
                    "total_ActorAgent": 5,
                },
                "characters": [],
                "decision_hints": {},
            },
        )
        payload = _extract_payload(instruction)

        self.assertIn("loaded_tool_skills", payload)
        self.assertEqual(
            [skill["skill_id"] for skill in payload["loaded_tool_skills"]],
            ["character_status_skill", "character_roster_skill"],
        )
        self.assertIn("available_tools", payload)
        self.assertEqual(
            [tool["name"] for tool in payload["available_tools"]],
            ["query_player_status", "query_character_roster"],
        )
        self.assertIn("character_status_snapshot", payload)
        self.assertIn("character_roster_snapshot", payload)
        self.assertEqual(payload["character_roster_snapshot"]["summary"]["total_L2"], 4)
        self.assertEqual(payload["character_status_snapshot"]["player_profile"]["character_id"], "player")
        self.assertNotIn("background", payload["character_status_snapshot"]["player_profile"])
        self.assertNotIn("scene", payload["character_status_snapshot"])
        self.assertNotIn("story_initialized", payload["character_status_snapshot"])

    def test_playwright_premise_skips_story_tools_for_player_only_opening(self) -> None:
        profiles = build_default_character_profiles()
        state = build_default_state(
            player_character="player",
            character_profiles=profiles,
        )
        formatter = PlaywrightFormatter()

        instruction = formatter.build_story_premise_instruction(
            game_state=state,
            scene_config=build_default_scene_config("xianxia_default"),
            character_profiles=profiles,
        )
        payload = _extract_payload(instruction)

        self.assertEqual(payload["loaded_tool_skills"], [])
        self.assertEqual(payload["available_tools"], [])

    def test_playwright_scene_candidates_load_scene_memory_and_roster_tools(self) -> None:
        session = _build_roster_session()
        session.state["history"] = [
            {
                "turn": 1,
                "actor": "player",
                "mode": "speak",
                "content": "我先看清山门前都有哪些人。",
            },
            {
                "turn": 2,
                "actor": "arch_rival",
                "mode": "speak",
                "content": "顾长渊先一步施压试探。",
            },
        ]
        session.state["memory"]["scene_memory"]["summary"] = "山门前的试探已经让场上气压明显抬高。"
        session.state["memory"]["playwright_memory"]["active_conflicts"] = ["顾长渊与玩家的初次对峙"]

        formatter = PlaywrightFormatter()
        instruction = formatter.build_scene_candidates_instruction(
            game_state=session.state,
            scene_config=build_default_scene_config("xianxia_default"),
            character_profiles=session.character_profiles,
            character_roster_snapshot={
                "summary": {
                    "total_L1": 1,
                    "max_L1": 6,
                    "total_L2": 1,
                    "max_L2": 15,
                    "total_ActorAgent": 1,
                },
                "characters": [],
                "decision_hints": {},
            },
        )
        payload = _extract_payload(instruction)

        self.assertEqual(
            [skill["skill_id"] for skill in payload["loaded_tool_skills"]],
            ["scene_skill", "memory_skill", "character_roster_skill"],
        )
        self.assertEqual(
            [tool["name"] for tool in payload["available_tools"]],
            ["query_scene_context", "query_story_memory", "query_character_roster"],
        )
        self.assertIn("scene_context_snapshot", payload)
        self.assertIn("story_memory_snapshot", payload)
        self.assertEqual(payload["scene_context_snapshot"]["scene"]["location_id"], "云岚山门")
        self.assertTrue(payload["story_memory_snapshot"]["scene_memory"]["summary"])

    def test_playwright_chapter_expansion_loads_status_tool(self) -> None:
        profiles = build_default_character_profiles(
            {
                "name": "沈云烟",
                "background": "带着未解的旧缘来到山门前。",
                "realm": "练气六层",
                "spiritual_root": "木火双灵根",
                "main_technique": "青岚引气诀",
            }
        )
        state = build_default_state(
            player_character="player",
            character_profiles=profiles,
        )
        state["plot"]["current_chapter_realm"] = "练气"
        state["plot"]["next_chapter_realm"] = "筑基"
        state["plot"]["chapter_transition_requirement"] = "玩家修为达到筑基要求后可收束本章并转入下一章。"
        formatter = PlaywrightFormatter()

        instruction = formatter.build_chapter_expansion_instruction(
            game_state=state,
            scene_config=build_default_scene_config("xianxia_default"),
            character_profiles=profiles,
        )
        payload = _extract_payload(instruction)

        self.assertEqual([skill["skill_id"] for skill in payload["loaded_tool_skills"]], ["character_status_skill"])
        self.assertEqual([tool["name"] for tool in payload["available_tools"]], ["query_player_status"])
        self.assertEqual(payload["character_status_snapshot"]["attributes"]["realm"], "练气六层")
        self.assertEqual(payload["character_status_snapshot"]["attributes"]["next_chapter_realm"], "筑基")


if __name__ == "__main__":
    unittest.main()
