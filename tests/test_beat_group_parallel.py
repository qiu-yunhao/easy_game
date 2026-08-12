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

from Graph.beat_group import merge_group_flags


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


if __name__ == "__main__":
    unittest.main()
