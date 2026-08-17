from __future__ import annotations

import unittest

from Recall.service.scene_extraction import extract_current_scene


def _state(**overrides):
    base = {
        "plot": {"scene_id": "c1-scene-1", "chapter_id": "c1"},
        "memory": {
            "scene_memory": {
                "turn_range": "10-12",
                "summary": "主角在酒馆遇到商人。",
                "key_events": ["达成交易"],
                "compressed_blocks": [{"max_score": 0.9}],
            }
        },
        "history": [
            {"turn": 8, "actor": "hero", "content": "前一幕的台词"},
            {"turn": 10, "actor": "hero", "content": "line-10"},
            {"turn": 11, "actor": "merchant", "content": "line-11"},
            {"turn": 12, "actor": "hero", "content": "line-12"},
            {"turn": 13, "actor": "hero", "content": "下一幕的台词"},
        ],
    }
    # 允许覆盖顶层键。
    for k, v in overrides.items():
        base[k] = v
    return base


class ExtractCurrentSceneTests(unittest.TestCase):
    def test_returns_scene_id_and_chapter_id(self):
        result = extract_current_scene(_state())
        self.assertEqual(result["scene_id"], "c1-scene-1")
        self.assertEqual(result["chapter_id"], "c1")

    def test_scene_memory_passed_through(self):
        result = extract_current_scene(_state())
        self.assertEqual(result["scene_memory"]["summary"], "主角在酒馆遇到商人。")

    def test_history_sliced_by_turn_range(self):
        result = extract_current_scene(_state())
        turns = [h["turn"] for h in result["history"]]
        # 只保留 turn 落在 [10, 12] 的条目，剔除前后幕。
        self.assertEqual(turns, [10, 11, 12])

    def test_single_turn_range(self):
        state = _state(
            memory={"scene_memory": {"turn_range": "11", "summary": "s", "key_events": []}}
        )
        result = extract_current_scene(state)
        self.assertEqual([h["turn"] for h in result["history"]], [11])

    def test_missing_scene_id_returns_none(self):
        state = _state(plot={"scene_id": "", "chapter_id": "c1"})
        self.assertIsNone(extract_current_scene(state))

    def test_empty_scene_memory_returns_none(self):
        # 无 summary、无 key_events、无 history 落区间 → 无可索引内容。
        state = _state(
            memory={"scene_memory": {"turn_range": "0-0", "summary": "", "key_events": []}},
            history=[{"turn": 20, "actor": "x", "content": "无关"}],
        )
        self.assertIsNone(extract_current_scene(state))

    def test_bad_turn_range_but_has_summary_still_extracts(self):
        # turn_range 脏 → history 切空，但摘要有内容，仍应产出（供 scene_summary 文档）。
        state = _state(
            memory={
                "scene_memory": {"turn_range": "", "summary": "有摘要", "key_events": []}
            },
            history=[{"turn": 5, "actor": "x", "content": "落区间外"}],
        )
        result = extract_current_scene(state)
        self.assertIsNotNone(result)
        self.assertEqual(result["history"], [])
        self.assertEqual(result["scene_memory"]["summary"], "有摘要")


if __name__ == "__main__":
    unittest.main()
