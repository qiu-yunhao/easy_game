from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.beat_group import apply_group_results, merge_group_flags, run_actor_group
from GameState import (
    create_character_runtime_state,
    create_initial_game_state,
    create_player_state,
)
from History.GameMemory import empty_memory_state
from ResolvedActUtils import build_resolved_act_payload
from ScenePlan import empty_scene_plan


def _apply_state(on_stage):
    cast = {"player", *on_stage}
    return create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "",
            "exploration_drive": "",
            "story_outline": [],
            "current_chapter_title": "",
            "current_chapter_overview": "",
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
            "location_id": "room",
            "time_tag": "now",
            "beat": "",
            "tension": 0.2,
            "focus_character": None,
            "on_stage": list(on_stage),
            "allow_interrupt": False,
            "suppressed": [],
        },
        characters={
            actor_id: create_character_runtime_state(intent=f"{actor_id}-intent")
            for actor_id in cast
        },
        scene_plan=empty_scene_plan(),
        memory=empty_memory_state(),
        player=create_player_state(enabled=False, controlled_character=None),
    )



class FakeActorAgent:
    def __init__(self, fail_times=0, label="ok"):
        self.calls = 0
        self.fail_times = fail_times
        self.label = label

    def perform_turn(self, state, character_profiles):
        del character_profiles
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("boom")
        actor = state["runtime"]["next_act"]["actor"]
        return {"actor": actor, "content": f"{self.label}:{actor}", "history_len": len(state["history"])}


def _make_state(history_len=3):
    return {
        "runtime": {"next_act": None},
        "history": [{"turn": i} for i in range(history_len)],
        "characters": {},
    }



class MergeGroupFlagsTest(unittest.TestCase):
    def test_end_scene_only_from_highest_priority(self):
        ordered = [
            ("a", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {}}),
            ("b", {"should_end_scene": True, "should_end_chapter": True, "triggered_plot_flags": {}}),
        ]
        flags = merge_group_flags(ordered)
        self.assertFalse(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])

    def test_end_scene_from_highest_priority_wins(self):
        ordered = [
            ("a", {"should_end_scene": True, "should_end_chapter": False, "triggered_plot_flags": {}}),
            ("b", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {}}),
        ]
        flags = merge_group_flags(ordered)
        self.assertTrue(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])

    def test_plot_flags_first_non_empty_by_priority(self):
        ordered = [
            ("a", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {"secret": "revealed_by_a"}}),
            ("b", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {"secret": "revealed_by_b", "other": "x"}}),
        ]
        flags = merge_group_flags(ordered)
        self.assertEqual(flags["triggered_plot_flags"]["secret"], "revealed_by_a")
        self.assertEqual(flags["triggered_plot_flags"]["other"], "x")

    def test_empty_group(self):
        flags = merge_group_flags([])
        self.assertFalse(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])
        self.assertEqual(flags["triggered_plot_flags"], {})


class RunActorGroupTest(unittest.TestCase):
    def test_all_actors_see_same_start_history(self):
        agents = {aid: FakeActorAgent() for aid in ["a", "b", "c"]}
        state = _make_state(history_len=5)
        successes, failures = run_actor_group(
            state,
            group=["a", "b", "c"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={},
            max_retries=3,
        )
        self.assertEqual(failures, [])
        for _aid, act in successes:
            self.assertEqual(act["history_len"], 5)

    def test_success_order_matches_group_order(self):
        agents = {aid: FakeActorAgent() for aid in ["a", "b", "c"]}
        state = _make_state()
        successes, _failures = run_actor_group(
            state, group=["a", "b", "c"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        self.assertEqual([aid for aid, _ in successes], ["a", "b", "c"])

    def test_retry_then_succeed(self):
        agents = {"a": FakeActorAgent(fail_times=2)}
        state = _make_state()
        successes, failures = run_actor_group(
            state, group=["a"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        self.assertEqual(len(successes), 1)
        self.assertEqual(failures, [])
        self.assertEqual(agents["a"].calls, 3)

    def test_exhausted_retries_reported_as_failure(self):
        agents = {"a": FakeActorAgent(fail_times=99), "b": FakeActorAgent()}
        state = _make_state()
        successes, failures = run_actor_group(
            state, group=["a", "b"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        self.assertEqual([aid for aid, _ in successes], ["b"])
        self.assertEqual([aid for aid, _ in failures], ["a"])
        self.assertEqual(agents["a"].calls, 4)


class ApplyGroupResultsTest(unittest.TestCase):
    def _state(self):
        return _apply_state(["a", "b"])

    def test_both_acts_committed_to_history_in_order(self):
        state = self._state()
        acts = [
            ("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A-line", spoken_text="A-line")),
            ("b", build_resolved_act_payload(actor="b", mode="speak", target=None, content="B-line", spoken_text="B-line")),
        ]
        result = apply_group_results(state, successes=acts, failures=[])
        actors_in_history = [h["actor"] for h in result["history"] if h.get("actor") in ("a", "b")]
        self.assertEqual(actors_in_history, ["a", "b"])

    def test_end_scene_from_lower_priority_ignored(self):
        state = self._state()
        acts = [
            ("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A", spoken_text="A", should_end_scene=False)),
            ("b", build_resolved_act_payload(actor="b", mode="speak", target=None, content="B", spoken_text="B", should_end_scene=True)),
        ]
        result = apply_group_results(state, successes=acts, failures=[])
        self.assertFalse(result["runtime"]["resolved_act"]["should_end_scene"])

    def test_failures_appended_as_system_message(self):
        state = self._state()
        acts = [("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A", spoken_text="A"))]
        result = apply_group_results(state, successes=acts, failures=[("b", "timeout")])
        system_msgs = [h for h in result["history"] if h.get("message_kind") == "system"]
        self.assertTrue(any("b" in str(h.get("content", "")) for h in system_msgs))


if __name__ == "__main__":
    unittest.main()
