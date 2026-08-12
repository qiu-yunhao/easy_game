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

from Graph.beat_group import merge_group_flags, run_actor_group


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


if __name__ == "__main__":
    unittest.main()
