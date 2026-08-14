from __future__ import annotations

import unittest

from Memory.scene_filter import filter_history_by_presence


def _item(turn, actor, *, on_stage, location_id):
    return {
        "turn": turn,
        "actor": actor,
        "mode": "speak",
        "content": f"line-{turn}",
        "on_stage": on_stage,
        "location_id": location_id,
    }


class SceneFilterTests(unittest.TestCase):
    def test_on_stage_granularity_keeps_only_present_rounds(self):
        # 角色 A 在场→下场→再上场;严格 on_stage 只保留其在场回合
        history = [
            _item(1, "A", on_stage=["A", "B"], location_id="hall"),
            _item(2, "B", on_stage=["B"], location_id="hall"),          # A 下场
            _item(3, "B", on_stage=["B", "A"], location_id="hall"),     # A 再上场
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="on_stage",
        )
        self.assertEqual([it["turn"] for it in kept], [1, 3])

    def test_recent_rounds_limit_applies_after_filter(self):
        history = [
            _item(t, "A", on_stage=["A"], location_id="hall") for t in range(1, 6)
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=3, granularity="on_stage",
        )
        self.assertEqual([it["turn"] for it in kept], [3, 4, 5])

    def test_location_granularity_keeps_same_location_rounds(self):
        history = [
            _item(1, "B", on_stage=["B"], location_id="hall"),   # A 不在台上但同地点
            _item(2, "B", on_stage=["B"], location_id="cave"),   # 不同地点
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="location",
        )
        self.assertEqual([it["turn"] for it in kept], [1])

    def test_missing_snapshot_is_invisible_under_on_stage(self):
        # 缺 on_stage 字段的条目,严格粒度下视为不可见(决策 A:缺省即不可见)
        history = [{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="on_stage",
        )
        self.assertEqual(kept, [])

    def test_recent_rounds_zero_returns_all_present(self):
        # recent_rounds<=0 表示不限制,返回全部在场条目(不切片)
        history = [
            _item(t, "A", on_stage=["A"], location_id="hall") for t in range(1, 4)
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=0, granularity="on_stage",
        )
        self.assertEqual([it["turn"] for it in kept], [1, 2, 3])

    def test_empty_history_returns_empty(self):
        kept = filter_history_by_presence(
            [], actor_id="A", current_location_id="hall",
            recent_rounds=3, granularity="on_stage",
        )
        self.assertEqual(kept, [])
