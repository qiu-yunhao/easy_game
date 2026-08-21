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

from Persistence.Store import GameSaveStore
from web_session import SessionConfig, WebGameSession


def _build_session_with_story_character() -> WebGameSession:
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.story_initialized = True
    session.last_handoff_reason = "刘执事已经现身，等待玩家回应。"

    session.character_profiles["player"]["backpack"] = [
        {"id": "spirit-stone", "name": "灵石", "quantity": 12},
    ]
    session.character_profiles["mentor_liu"] = {
        "character_id": "mentor_liu",
        "name": "刘执事",
        "story_role": "登场执事",
        "agent_type": "L1",
        "story_layer": "L1",
        "background": "负责看守云峰入门台的执事。",
        "spiritual_root": "金灵根",
        "realm": "筑基初期",
        "main_technique": "云峰镇守诀",
        "persona": ["谨慎", "克制"],
        "base_style": "说话平稳，观察细致。",
        "base_relationship": {"player": 1.5},
        "secrets": [],
        "profile_source": "actor_create_agent",
        "is_active": True,
        "is_offstage": False,
    }
    session.character_profiles["old_zhang_blacksmith"] = {
        "character_id": "old_zhang_blacksmith",
        "name": "老张",
        "occupation": "铁匠",
        "story_role": "山下集市里的铁匠",
        "agent_type": "actor",
        "story_layer": "actor",
        "storage_mode": "shared_template",
        "background": "常年在集市打铁，只在需要时提供器具与消息。",
        "spiritual_root": "杂灵根",
        "realm": "练气一层",
        "main_technique": "炉火锻器术",
        "persona": ["实在", "寡言"],
        "base_style": "说话直来直往。",
        "base_relationship": {"player": 0.5},
        "secrets": [],
        "profile_source": "actor_create_agent",
        "is_active": True,
        "is_offstage": False,
    }

    session.state["plot"]["plot_flags"] = {"gate_open": "yes", "amulet_taken": "no"}
    session.state["plot"]["scene_id"] = "gatehouse-node"
    session.state["scene"]["location_id"] = "云峰山门"
    session.state["scene"]["on_stage"] = ["player", "mentor_liu"]
    session.state["scene"]["focus_character"] = "mentor_liu"
    session.state["runtime"]["eligible_actors"] = ["player", "mentor_liu"]
    session.state["runtime"]["turn_index"] = 3
    session.state["characters"]["mentor_liu"] = {
        "emotion": {"calm": 0.8},
        "intent": "审视玩家的来意。",
        "known_facts": ["玩家刚抵达云峰山门。"],
        "relationship_delta": {"player": 3.0},
        "last_turn": 3,
        "memory": {
            "long_term_memory": [],
            "short_term_memory": [],
            "player_memory": {
                "overall_impression": "这个新人暂时可控。",
                "relation_state": {"player": 3.0},
                "key_events": [],
            },
        },
        "dialogue_flags": ["greeting.unlocked"],
        "life_status": "alive",
    }
    session.state["characters"]["old_zhang_blacksmith"] = {
        "emotion": {"steady": 0.5},
        "intent": "继续打铁，同时留意往来修士。",
        "known_facts": ["玩家曾在集市向他打听过铁器材料。"],
        "relationship_delta": {"player": 0.5},
        "last_turn": 2,
        "memory": {
            "long_term_memory": [],
            "short_term_memory": [],
            "player_memory": {
                "overall_impression": "这个年轻修士还算实在。",
                "relation_state": {"player": 0.5},
                "key_events": [],
            },
        },
        "life_status": "alive",
    }
    session.state["history"] = [
        {
            "turn": 1,
            "actor": None,
            "mode": "event",
            "content": "晨雾尚未散尽，云峰山门前已有零星人影。",
        },
        {
            "turn": 2,
            "actor": "mentor_liu",
            "mode": "speak",
            "content": "来者止步，先报上姓名。",
            "spoken_text": "来者止步，先报上姓名。",
            "nonverbal_action": "刘执事按刀立于石阶前。",
        },
        {
            "turn": 3,
            "actor": "old_zhang_blacksmith",
            "mode": "speak",
            "content": "若要修补兵刃，晚些时候来集市寻我。",
            "spoken_text": "若要修补兵刃，晚些时候来集市寻我。",
            "nonverbal_action": "老张把淬火后的铁胚搁在铁砧边。",
        },
    ]
    session.state["memory"]["scene_memory"]["summary"] = "玩家在山门前遇到了第一位执事，也与山下铁匠打过照面。"
    return session


class PersistenceSaveLoadTests(unittest.TestCase):
    def test_web_session_snapshot_round_trip_restores_runtime_state(self) -> None:
        source_session = _build_session_with_story_character()

        snapshot = source_session.export_runtime_snapshot()

        restored_session = WebGameSession(SessionConfig(mode="heuristic"))
        restored_state = restored_session.load_runtime_snapshot(snapshot)

        self.assertTrue(restored_session.story_initialized)
        self.assertEqual(restored_session.last_handoff_reason, "刘执事已经现身，等待玩家回应。")
        self.assertIn("mentor_liu", restored_session.character_profiles)
        self.assertEqual(restored_session.character_profiles["mentor_liu"]["name"], "刘执事")
        self.assertEqual(restored_session.state["plot"]["plot_flags"]["gate_open"], "yes")
        self.assertEqual(restored_session.state["scene"]["on_stage"], ["player", "mentor_liu"])
        self.assertEqual(
            restored_state["history"][-1]["speaker"],
            "老张",
        )

    def test_save_store_persists_story_instances_and_shared_actor_interactions(self) -> None:
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()

        user = store.ensure_user(username="tester", display_name="测试玩家")
        session = _build_session_with_story_character()
        snapshot = session.export_runtime_snapshot()

        created = store.create_new_game(
            user_id=user["id"],
            slot_name="第一存档",
            session_snapshot=snapshot,
            starter_story_templates=[
                {
                    "template_key": "starter_guard",
                    "display_name": "山门守卫",
                    "starter_enabled": True,
                    "template_kind": "L1",
                    "default_profile_json": {
                        "character_id": "starter_guard",
                        "name": "山门守卫",
                        "story_role": "初始守卫模板",
                        "agent_type": "L1",
                        "story_layer": "L1",
                    },
                    "default_runtime_json": {
                        "life_status": "alive",
                    },
                    "default_dialogue_flags_json": ["guard.intro"],
                }
            ],
            save_label="开局存档",
        )

        player = created["player"]
        saved = store.save_player_session(
            user_id=user["id"],
            player_id=player["id"],
            session_snapshot=snapshot,
            save_kind="manual",
            save_label="手动存档",
        )
        loaded = store.load_player_session(user_id=user["id"], player_id=player["id"])
        players = store.list_players_for_user(user["id"])

        self.assertEqual(saved["player"]["id"], player["id"])
        self.assertEqual(players[0]["slot_name"], "第一存档")
        self.assertEqual(loaded["player"]["current_story_node_id"], "gatehouse-node")
        self.assertEqual(loaded["world_state"]["plot"]["plot_flags"]["gate_open"], "yes")
        self.assertEqual(
            loaded["snapshot"]["character_profiles"]["mentor_liu"]["name"],
            "刘执事",
        )

        story_characters = {
            row["actor_character_id"]: row
            for row in loaded["story_characters"]
        }
        self.assertIn("starter_guard", story_characters)
        self.assertIn("mentor_liu", story_characters)
        self.assertFalse(story_characters["starter_guard"]["has_met"])
        self.assertTrue(story_characters["mentor_liu"]["has_met"])
        self.assertAlmostEqual(story_characters["mentor_liu"]["affection_score"], 4.5)
        self.assertEqual(story_characters["mentor_liu"]["dialogue_flags_json"], ["greeting.unlocked"])
        self.assertEqual(story_characters["mentor_liu"]["agent_layer"], "L1")

        self.assertEqual(len(loaded["actor_interactions"]), 1)
        self.assertEqual(loaded["actor_interactions"][0]["met_count"], 1)
        self.assertAlmostEqual(loaded["actor_interactions"][0]["favor_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
