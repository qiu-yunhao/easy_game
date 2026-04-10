from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import patch

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.builder import prepare_chapter_turn


class PrepareChapterTurnParallelTests(unittest.TestCase):
    def test_prepare_chapter_turn_parallelizes_intro_and_scene_candidates(self) -> None:
        intro_started = threading.Event()
        candidates_started = threading.Event()
        concurrent_branches: list[str] = []

        initial_state = {
            "plot": {"chapter_id": "chapter-1"},
            "scene": {"location_id": "gate", "beat": "arrival"},
            "scene_plan": {"scene_goal": ""},
            "runtime": {
                "pending_intro_kind": "chapter",
                "scene_candidates": [],
                "turn_index": 0,
            },
            "history": [],
            "director_brief": {},
        }

        def fake_chapter_expansion(state, deps):
            del deps
            return {
                **state,
                "plot": {
                    **state["plot"],
                    "chapter_goal": "reach the market",
                },
            }

        def fake_chapter_intro(state, deps):
            del deps
            intro_started.set()
            if candidates_started.wait(timeout=0.3):
                concurrent_branches.append("intro")
            return {
                **state,
                "history": [
                    *state["history"],
                    {
                        "turn": 1,
                        "mode": "event",
                        "content": "chapter intro",
                    },
                ],
                "runtime": {
                    **state["runtime"],
                    "pending_intro_kind": "",
                    "turn_index": 1,
                },
            }

        def fake_scene_candidates(state, deps):
            del deps
            candidates_started.set()
            if intro_started.wait(timeout=0.3):
                concurrent_branches.append("scene_candidates")
            return {
                **state,
                "plot": {
                    **state["plot"],
                    "scene_candidates_source": "playwright_agent",
                },
                "scene": {
                    **state["scene"],
                    "location_id": "market",
                    "beat": "survey the crowd",
                },
                "scene_plan": {
                    "scene_goal": "find a useful clue",
                },
                "runtime": {
                    **state["runtime"],
                    "scene_candidates": [{"candidate_id": "market-1"}],
                },
            }

        def fake_refresh_history(state, deps):
            del deps
            self.assertEqual(state["history"][-1]["content"], "chapter intro")
            self.assertEqual(state["scene_plan"]["scene_goal"], "find a useful clue")
            self.assertEqual(
                state["runtime"]["scene_candidates"],
                [{"candidate_id": "market-1"}],
            )
            return {
                **state,
                "memory_refreshed": True,
            }

        def fake_director(state, deps):
            del deps
            self.assertTrue(state["memory_refreshed"])
            return {
                **state,
                "director_brief": {
                    "focus_character": "market_guide",
                },
            }

        def fake_scheduler(state, deps):
            del deps
            return {
                **state,
                "runtime": {
                    **state["runtime"],
                    "next_act": {"actor": "market_guide"},
                },
            }

        with (
            patch("Graph.builder.chapter_expansion_node", side_effect=fake_chapter_expansion),
            patch("Graph.builder.chapter_intro_node", side_effect=fake_chapter_intro),
            patch("Graph.builder.scene_candidates_node", side_effect=fake_scene_candidates),
            patch("Graph.builder.refresh_history_node", side_effect=fake_refresh_history),
            patch("Graph.builder.director_node", side_effect=fake_director),
            patch("Graph.builder.scheduler_node", side_effect=fake_scheduler),
        ):
            next_state = prepare_chapter_turn(initial_state, deps=object())

        self.assertCountEqual(concurrent_branches, ["intro", "scene_candidates"])
        self.assertEqual(next_state["scene"]["location_id"], "market")
        self.assertEqual(next_state["history"][-1]["content"], "chapter intro")
        self.assertEqual(next_state["runtime"]["pending_intro_kind"], "")
        self.assertEqual(
            next_state["runtime"]["scene_candidates"],
            [{"candidate_id": "market-1"}],
        )
        self.assertEqual(next_state["runtime"]["next_act"]["actor"], "market_guide")


if __name__ == "__main__":
    unittest.main()
