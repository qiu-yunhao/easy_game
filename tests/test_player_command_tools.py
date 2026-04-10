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

from GameState import create_character_runtime_state
from Persistence.Store import GameSaveStore
from web_session import SessionConfig, WebGameSession


def _build_tool_ready_session() -> WebGameSession:
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.story_initialized = True
    session.last_handoff_reason = "等待玩家输入。"
    session.state["player"]["enabled"] = True
    session.state["player"]["controlled_character"] = "player"
    session.state["plot"]["chapter_id"] = "chapter-1"
    session.state["plot"]["scene_id"] = "scene-1"
    session.state["plot"]["current_scene_index"] = 0
    session.state["plot"]["current_chapter_title"] = "入门试炼"
    session.state["plot"]["chapter_goal"] = "找到进入山门的线索"
    session.state["plot"]["cultivation_goal"] = "稳固练气初期的修为"
    session.state["scene"]["location_id"] = "山门外的石阶"
    session.state["scene"]["focus_character"] = "mentor_liu"
    session.state["scene"]["on_stage"] = ["player", "mentor_liu"]
    session.state["runtime"]["eligible_actors"] = ["player", "mentor_liu"]
    session.state["runtime"]["turn_index"] = 2
    session.state["runtime"]["next_act"] = {
        "actor": "player",
        "mode": "speak",
        "target": "mentor_liu",
        "motivation": "先确认当前处境",
        "content": "",
    }
    session.state["scene_plan"]["scene_goal"] = "先查看身上的资源与周围状况"
    session.state["director_brief"]["beat_goal"] = "确认资源后再决定下一步"
    session.character_profiles["player"]["backpack"] = [
        {"id": "iron-sword", "name": "铁剑", "quantity": 1},
        {"id": "healing-potion", "name": "治疗药水", "quantity": 3},
    ]
    session.character_profiles["mentor_liu"] = {
        "character_id": "mentor_liu",
        "name": "柳前辈",
        "story_layer": "L2",
        "agent_type": "L2",
        "background": "暂住在山门外的引路人。",
        "base_relationship": {"player": 2.0},
        "persona": ["沉稳"],
        "base_style": "言语克制",
        "spiritual_root": "",
        "realm": "筑基",
        "main_technique": "清风诀",
        "gender": "",
        "race": "",
        "secrets": [],
        "is_active": True,
        "is_offstage": False,
    }
    session.state["characters"]["mentor_liu"] = create_character_runtime_state(
        intent="观察新来的弟子",
        relationship_delta={"player": 1.5},
    )
    return session


class PlayerCommandToolTests(unittest.TestCase):
    def test_save_store_queries_inventory_relation_and_quests(self) -> None:
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()
        session = _build_tool_ready_session()
        user = store.ensure_user(username="tester", display_name="测试玩家")
        created = store.create_new_game(
            user_id=user["id"],
            slot_name="一号存档",
            session_snapshot=session.export_runtime_snapshot(),
        )
        player_id = created["player"]["id"]

        inventory = store.query_inventory(user_id=user["id"], player_id=player_id)
        relation = store.query_relation(
            user_id=user["id"],
            player_id=player_id,
            target_name="柳前辈",
        )
        quests = store.query_quests(user_id=user["id"], player_id=player_id)

        self.assertEqual([item["item_name"] for item in inventory["items"]], ["铁剑", "治疗药水"])
        self.assertEqual(relation["display_name"], "柳前辈")
        self.assertAlmostEqual(relation["score"], 3.5)
        self.assertGreaterEqual(len(quests["quests"]), 3)
        self.assertEqual(quests["quests"][0]["category"], "chapter")

    def test_web_session_intercepts_tool_requests_as_system_messages(self) -> None:
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()
        session = _build_tool_ready_session()
        user = store.ensure_user(username="tester", display_name="测试玩家")
        created = store.create_new_game(
            user_id=user["id"],
            slot_name="一号存档",
            session_snapshot=session.export_runtime_snapshot(),
        )
        session.bind_save_context(
            save_store=store,
            user_id=user["id"],
            player_id=created["player"]["id"],
        )

        state = session.apply_player_action("看看我包里有什么")

        self.assertEqual(state["history"][-1]["kind"], "system")
        self.assertEqual(state["history"][-1]["tool_name"], "query_inventory")
        self.assertIn("铁剑", state["history"][-1]["content"])
        self.assertEqual(state["player"]["last_parsed_act"]["tool_name"], "query_inventory")
        self.assertEqual(session.state["runtime"]["next_act"]["actor"], "player")


if __name__ == "__main__":
    unittest.main()
