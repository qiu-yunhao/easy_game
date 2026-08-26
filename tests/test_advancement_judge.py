from __future__ import annotations

import unittest

from WorldSetting.advancement import can_advance
from WorldSetting.schema import build_advance_condition


class AdvancementJudgeTests(unittest.TestCase):
    def test_event_condition_met_when_marker_present(self) -> None:
        cond = build_advance_condition("event", completion_marker="foundation_built")
        self.assertTrue(can_advance(cond, {"completed_markers": ["foundation_built"]}))
        self.assertFalse(can_advance(cond, {"completed_markers": []}))

    def test_threshold_condition_met_when_counter_reaches_target(self) -> None:
        cond = build_advance_condition("threshold", counter_key="cleared_rounds", target_value=3)
        self.assertTrue(can_advance(cond, {"counters": {"cleared_rounds": 3}}))
        self.assertTrue(can_advance(cond, {"counters": {"cleared_rounds": 5}}))
        self.assertFalse(can_advance(cond, {"counters": {"cleared_rounds": 2}}))

    def test_narrative_condition_defers_to_narrative_layer(self) -> None:
        cond = build_advance_condition("narrative")
        self.assertIsNone(can_advance(cond, {}))

    def test_composite_and(self) -> None:
        cond = build_advance_condition("composite", op="AND", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("threshold", counter_key="c", target_value=2),
        ])
        state = {"completed_markers": ["m1"], "counters": {"c": 2}}
        self.assertTrue(can_advance(cond, state))
        self.assertFalse(can_advance(cond, {"completed_markers": ["m1"], "counters": {"c": 1}}))

    def test_composite_or(self) -> None:
        cond = build_advance_condition("composite", op="OR", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("event", completion_marker="m2"),
        ])
        self.assertTrue(can_advance(cond, {"completed_markers": ["m2"]}))
        self.assertFalse(can_advance(cond, {"completed_markers": []}))

    def test_composite_with_narrative_child_treats_narrative_as_not_yet(self) -> None:
        cond = build_advance_condition("composite", op="AND", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("narrative"),
        ])
        self.assertFalse(can_advance(cond, {"completed_markers": ["m1"]}))
