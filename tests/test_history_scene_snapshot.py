from __future__ import annotations

import sys
import types
import unittest

# web_session 依赖 openai;在无 SDK 的测试环境下打桩,避免导入失败。
_openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - 本地测试的导入垫片
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


_openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", _openai_stub)

from Actor.ActorRuntime import apply_resolved_act
from CharacterProfile import ensure_character_profile
from GameState import (
    create_character_runtime_state,
    create_initial_game_state,
    create_player_state,
)
from ResolvedActUtils import build_resolved_act_payload


def _minimal_plot():
    # apply_resolved_act 会读 state["plot"];给足必填键的最小合法 plot。
    return {
        "chapter_id": "chapter-1", "scene_id": "scene-1", "current_scene_index": 0,
        "chapter_goal": "", "current_chapter_hooks": [], "plot_flags": {},
        "story_premise": "", "exploration_drive": "", "story_outline": [],
        "current_chapter_title": "", "current_chapter_overview": "",
        "active_outline_chapter_id": "", "story_premise_source": "",
        "story_outline_source": "", "chapter_expansion_source": "",
        "story_foundation_source": "", "chapter_focus_source": "",
        "scene_candidates_source": "", "current_chapter_index": 0,
        "cultivation_goal": "", "current_player_realm": "",
        "current_chapter_realm": "", "next_chapter_realm": "",
        "chapter_transition_requirement": "", "completed_chapters": [],
    }


class HistorySceneSnapshotTests(unittest.TestCase):
    def test_apply_resolved_act_records_on_stage_and_location(self):
        profiles = {
            "A": ensure_character_profile({
                "character_id": "A", "name": "甲", "persona": [],
                "base_style": "", "base_relationship": {}, "secrets": [],
                "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
                "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
            }),
        }
        state = create_initial_game_state(
            plot=_minimal_plot(),
            scene={
                "location_id": "hall", "time_tag": "morning", "beat": "",
                "tension": 0.0, "focus_character": "A",
                "on_stage": ["A", "B"], "allow_interrupt": True, "suppressed": [],
            },
            characters={"A": create_character_runtime_state()},
            player=create_player_state(controlled_character="player"),
        )
        resolved = build_resolved_act_payload(
            actor="A", mode="speak", target=None, content="你好",
        )
        state["runtime"]["resolved_act"] = resolved

        next_state = apply_resolved_act(state, character_profiles=profiles)

        last = next_state["history"][-1]
        self.assertEqual(last["on_stage"], ["A", "B"])
        self.assertEqual(last["location_id"], "hall")

    def test_append_tool_message_records_on_stage_and_location(self):
        # 第四处写点:web_session 工具事件(actor=None 的系统事件)也须补记在场快照,
        # 否则严格 on_stage 过滤下这条工具事件记忆将永久不可见,与其余三处写点不一致。
        from web_session import SessionConfig, WebGameSession

        session = WebGameSession(SessionConfig(mode="heuristic"))
        session.state["scene"]["on_stage"] = ["A", "B"]
        session.state["scene"]["location_id"] = "hall"

        session._append_tool_message_unlocked(
            raw_input="查看背包",
            parsed_act={"actor": "player", "mode": "tool"},
            result={"text": "背包里有一把铁剑。", "tool_name": "inventory", "payload": {}},
        )

        last = session.state["history"][-1]
        self.assertEqual(last["on_stage"], ["A", "B"])
        self.assertEqual(last["location_id"], "hall")
