from __future__ import annotations

import unittest

from StoryTemplate.TemplateChunker import TemplateChunker, Chunk


class ChapterMarkerTests(unittest.TestCase):
    def test_chinese_numeral_chapters(self):
        text = "第一章 初入江湖\n甲行走江湖。\n第二章 风波\n乙掀起风波。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].title, "初入江湖")
        self.assertEqual(chunks[0].order_index, 0)
        self.assertIn("甲行走江湖", chunks[0].text)
        self.assertEqual(chunks[1].order_index, 1)

    def test_arabic_and_spaced_and_no_prefix(self):
        text = "第37章 甲\n内容一\n卷二\n内容二\n三十七回 乙\n内容三"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 3)

    def test_hui_marker(self):
        text = "第一百零八回 大结局\n尾声内容。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "大结局")

    def test_volume_composite_order(self):
        # 卷号作 order 高位：卷一/章二 应排在 卷二/章一 之前
        text = ("第一卷\n第二章 甲\n甲内容\n"
                "第二卷\n第一章 乙\n乙内容")
        chunks = TemplateChunker().chunk(text)
        titles = [c.title for c in chunks]
        self.assertEqual(titles.index("甲") < titles.index("乙"), True)


class BoundaryTests(unittest.TestCase):
    def test_no_marker_falls_back_to_sliding_window(self):
        text = "甲" * 4500  # 无任何标记
        chunks = TemplateChunker(chunk_size=2000).chunk(text)
        self.assertEqual(len(chunks), 3)  # 2000 + 2000 + 500
        self.assertEqual([c.order_index for c in chunks], [0, 1, 2])

    def test_inline_marker_not_matched(self):
        # 正文里出现「这一章」不应被当标题切块
        text = "第一章 开始\n他说这一章的教训很深刻，第二章内容也提到过。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 1)

    def test_overlong_title_line_treated_as_body(self):
        long_tail = "关于修炼的长篇大论" * 5  # >30 字
        text = f"第一章 {long_tail}\n正文。"
        chunks = TemplateChunker().chunk(text)
        # 标题过长 → 整行当正文，不产生独立标题块（回退滑窗，1 块）
        self.assertEqual(len(chunks), 1)

    def test_prologue_and_epilogue_ordering(self):
        text = ("楔子\n开篇引子。\n"
                "第一章 正传\n正文。\n"
                "尾声\n收束。")
        chunks = TemplateChunker().chunk(text)
        # 楔子排最前，尾声排最后
        self.assertTrue(chunks[0].text.startswith("开篇引子") or "引子" in chunks[0].text)
        self.assertIn("收束", chunks[-1].text)


if __name__ == "__main__":
    unittest.main()
