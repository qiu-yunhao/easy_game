from __future__ import annotations

import os
import unittest
import uuid

from db import Database
from StoryTemplate.TemplateRepository import TemplateRepository
from StoryTemplate.TemplateSchema import empty_style_bible


def _mysql_url() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    return os.environ["MYSQL_URL"]


class RepositoryRealMysqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = TemplateRepository(Database(_mysql_url()))
        cls.repo.create_all()

    def _sample(self):
        # beat_id/node_id 是全局主键（不按 template_id 隔离），真实产物用 uuid 保证唯一；
        # 测试对持久化真库多次运行，故也用 uuid 后缀避免主键碰撞。
        suffix = uuid.uuid4().hex[:8]
        sb = empty_style_bible()
        sb["narrative_voice"] = "第三人称"
        sb["tone_tags"] = ["古雅", "诙谐"]
        sb["factions"] = ["天地会"]
        chars = [{
            "name": "韦小宝", "role_summary": "市井混混", "persona": ["机灵", "圆滑"],
            "speech_style": "俚俗", "secrets": ["身世成谜"],
            "signature_relations": ["亦友亦敌"], "suggested_layer": "player",
        }]
        beats = [{
            "beat_id": f"b1_{suffix}", "label": "拜师", "tags": ["成长"], "summary": "弟子拜门",
            "dramatic_function": "铺垫", "reusable_conflict": "身份认同",
        }]
        skeleton = [
            {"node_id": f"n2_{suffix}", "order_index": 1, "title": "发展", "event_summary": "承",
             "preconditions": ["开端"], "maps_to_chapter_hint": "2"},
            {"node_id": f"n1_{suffix}", "order_index": 0, "title": "开端", "event_summary": "起",
             "preconditions": [], "maps_to_chapter_hint": "1"},
        ]
        return sb, chars, beats, skeleton

    def test_save_and_read_back_roundtrip(self):
        sb, chars, beats, skeleton = self._sample()
        tid = self.repo.save_template(
            user_id=1, source_title="鹿鼎记测试",
            style_bible=sb, characters=chars, beats=beats, skeleton=skeleton,
        )
        self.assertIsInstance(tid, int)

        got_sb = self.repo.get_style_bible(tid)
        self.assertEqual(got_sb["narrative_voice"], "第三人称")
        self.assertEqual(got_sb["tone_tags"], ["古雅", "诙谐"])

        got_chars = self.repo.get_characters(tid)
        self.assertEqual(got_chars[0]["name"], "韦小宝")
        self.assertEqual(got_chars[0]["persona"], ["机灵", "圆滑"])

        got_beats = self.repo.get_beats(tid)
        self.assertEqual(got_beats[0]["label"], "拜师")

        got_skel = self.repo.get_skeleton(tid)
        # 按 order_index 升序读回
        self.assertEqual([n["order_index"] for n in got_skel], [0, 1])
        self.assertEqual(got_skel[0]["title"], "开端")

    def test_list_templates_returns_saved_with_beat_count(self):
        sb, chars, beats, skeleton = self._sample()
        source_title = "鹿鼎记列表测试"
        tid = self.repo.save_template(
            user_id=1, source_title=source_title,
            style_bible=sb, characters=chars, beats=beats, skeleton=skeleton,
        )
        rows = self.repo.list_templates()
        match = [r for r in rows if r["template_id"] == tid]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["source_title"], source_title)
        self.assertEqual(match[0]["beat_count"], len(beats))
        self.assertIn("created_at", match[0])


if __name__ == "__main__":
    unittest.main()
