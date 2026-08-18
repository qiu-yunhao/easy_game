from __future__ import annotations

import unittest

from PlayerWriter.StoryTemplateGuidance import (
    build_template_query,
    format_beat_guidance,
    format_skeleton_guidance,
)


def _state(chapter_goal="", outline=None, chapter_id="ch-1"):
    return {
        "plot": {
            "chapter_id": chapter_id,
            "chapter_goal": chapter_goal,
            "current_chapter_index": 0,
            "story_outline": outline or [],
        }
    }


class BuildTemplateQueryTests(unittest.TestCase):
    def test_有history时拼章节目标与最近剧情(self):
        state = _state(
            chapter_goal="夺回赤霞令",
            outline=[{"chapter_id": "ch-1", "title": "客栈风云", "main_goal": "查明黑衣人来历"}],
        )
        history = [
            {"speaker": "玩家", "content": "我推门走进客栈。"},
            {"speaker": "黑衣人", "content": "交出赤霞令！"},
        ]
        query = build_template_query(state, history)
        self.assertIn("夺回赤霞令", query)
        self.assertIn("客栈风云", query)
        self.assertIn("查明黑衣人来历", query)
        self.assertIn("交出赤霞令", query)

    def test_history为空时只用章节目标(self):
        state = _state(
            chapter_goal="夺回赤霞令",
            outline=[{"chapter_id": "ch-1", "title": "客栈风云", "main_goal": "查明黑衣人来历"}],
        )
        query = build_template_query(state, None)
        self.assertIn("夺回赤霞令", query)
        self.assertIn("客栈风云", query)
        self.assertNotIn("交出赤霞令", query)

    def test_无outline时仅章节目标不报错(self):
        state = _state(chapter_goal="夺回赤霞令", outline=[])
        query = build_template_query(state, [])
        self.assertIn("夺回赤霞令", query)

    def test_只取最近三条history(self):
        state = _state(chapter_goal="目标")
        history = [{"speaker": "x", "content": f"句子{i}"} for i in range(5)]
        query = build_template_query(state, history)
        self.assertIn("句子4", query)
        self.assertIn("句子2", query)
        self.assertNotIn("句子1", query)
