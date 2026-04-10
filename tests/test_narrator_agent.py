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

from Narrator.NarratorAgent import NarratorAgent
from Narrator.NarratorRuntime import build_heuristic_narrated_segments


class StubNarratorAgent(NarratorAgent):
    def __init__(self, response: dict[str, object]) -> None:
        super().__init__(client=object(), model="stub-model")
        self._response = response

    def command(self, instruction, history=None, response_format=None):
        del instruction, history, response_format
        return self._response


class NarratorAgentTests(unittest.TestCase):
    def test_narrate_action_batch_falls_back_for_out_of_batch_turns(self) -> None:
        agent = StubNarratorAgent(
            {
                "segments": [
                    {
                        "history_turn": 99,
                        "actor": "intruder",
                        "narrated_text": "这是一条不属于当前批次的旁白。",
                    },
                    {
                        "history_turn": 1,
                        "actor": "npc_a",
                        "narrated_text": "阿青抬眸望去，轻声道：“你好。”",
                    },
                ]
            }
        )
        batch = [
            {
                "history_turn": 1,
                "actor": "npc_a",
                "target": None,
                "mode": "speak",
                "raw_content": "你好。",
                "raw_spoken_text": "你好。",
                "raw_nonverbal_action": "",
            },
            {
                "history_turn": 2,
                "actor": "npc_b",
                "target": "npc_a",
                "mode": "action",
                "raw_content": "拱手致意",
                "raw_spoken_text": "",
                "raw_nonverbal_action": "拱手致意",
            },
        ]
        segments = agent.narrate_action_batch(
            state={
                "scene": {},
                "scene_plan": {},
                "director_brief": {},
                "history": [],
            },
            character_profiles={
                "npc_a": {"name": "阿青"},
                "npc_b": {"name": "白松"},
            },
            batch=batch,
            style_preset="epic",
        )

        self.assertEqual([item["history_turn"] for item in segments], [1, 2])
        self.assertEqual(segments[0]["narrated_text"], "阿青抬眸望去，轻声道：“你好。”")
        self.assertEqual(segments[1]["actor"], "npc_b")
        self.assertEqual(segments[1]["narrated_text"], "白松朝着阿青拱手致意。")

    def test_build_heuristic_narrated_segments_uses_readable_fallback_text(self) -> None:
        segments = build_heuristic_narrated_segments(
            [
                {
                    "history_turn": 1,
                    "actor": "npc_a",
                    "target": "npc_b",
                    "mode": "speak",
                    "raw_content": "拱手一礼",
                    "raw_spoken_text": "请。",
                    "raw_nonverbal_action": "拱手一礼",
                },
                {
                    "history_turn": 2,
                    "actor": "npc_b",
                    "target": None,
                    "mode": "action",
                    "raw_content": "",
                    "raw_spoken_text": "",
                    "raw_nonverbal_action": "",
                },
            ],
            {
                "npc_a": {"name": "阿青"},
                "npc_b": {"name": "白松"},
            },
        )

        self.assertEqual(
            segments[0]["narrated_text"],
            "阿青朝着白松拱手一礼，开口道：“请。”",
        )
        self.assertEqual(
            segments[1]["narrated_text"],
            "与此同时，白松敛住气息，静静观察四周。",
        )


if __name__ == "__main__":
    unittest.main()
