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


class FormatSkeletonGuidanceTests(unittest.TestCase):
    def test_多节点转软指导文本(self):
        nodes = [
            {"node_id": "n1", "order_index": 0, "title": "初入江湖",
             "event_summary": "主角离乡遭遇第一场冲突", "preconditions": [], "maps_to_chapter_hint": ""},
            {"node_id": "n2", "order_index": 1, "title": "结义",
             "event_summary": "与关键盟友结拜", "preconditions": ["初入江湖"], "maps_to_chapter_hint": ""},
        ]
        text = format_skeleton_guidance(nodes)
        self.assertIn("初入江湖", text)
        self.assertIn("主角离乡遭遇第一场冲突", text)
        self.assertIn("结义", text)
        self.assertIn("参考", text)  # 软指导措辞

    def test_空列表返回空串(self):
        self.assertEqual(format_skeleton_guidance([]), "")


class FormatBeatGuidanceTests(unittest.TestCase):
    def test_多桥段转软指导文本(self):
        beats = [
            {"beat_id": "b1", "label": "伏击", "tags": ["冲突"],
             "summary": "在必经之路设伏", "dramatic_function": "制造危机", "reusable_conflict": "以少胜多"},
            {"beat_id": "b2", "label": "反转", "tags": ["悬念"],
             "summary": "盟友暴露真实身份", "dramatic_function": "情感冲击", "reusable_conflict": "信任背叛"},
        ]
        text = format_beat_guidance(beats)
        self.assertIn("伏击", text)
        self.assertIn("在必经之路设伏", text)
        self.assertIn("反转", text)
        self.assertIn("参考", text)  # 软指导措辞

    def test_空列表返回空串(self):
        self.assertEqual(format_beat_guidance([]), "")
