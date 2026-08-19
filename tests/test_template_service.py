from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace

from dotenv import load_dotenv

from StoryTemplate.factory import build_story_template_service


class _ScriptedClient:
    """按 response schema 名路由返回:map 阶段回 chunk_signal,reduce 回各自结构。"""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        schema = kwargs.get("response_format", {})
        name = ""
        if isinstance(schema, dict):
            name = schema.get("json_schema", {}).get("name", "")
        payload = self._route(name)
        msg = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    def _route(self, name):
        if name == "chunk_signal":
            return {"style_tone_tags": ["古雅"], "style_devices": ["白描"],
                    "characters": [{"name": "韦小宝", "behavior": "耍滑"}],
                    "is_event": True, "event_summary": "韦小宝闯宫"}
        if name == "style_bible":
            return {"narrative_voice": "第三人称", "tone_tags": ["古雅", "诙谐"],
                    "prose_rhythm": "长短交错", "signature_devices": ["白描"],
                    "world_premise": "江湖庙堂", "cultivation_system": "无",
                    "factions": ["天地会"], "key_locations": ["皇宫"],
                    "world_rules": [], "lexicon": ["韦小宝"]}
        if name == "character_archetypes":
            return {"characters": [{"name": "韦小宝", "role_summary": "市井混混",
                    "persona": ["机灵"], "speech_style": "俚俗", "secrets": [],
                    "signature_relations": ["亦友亦敌"], "suggested_layer": "player"}]}
        if name == "plot_beats":
            return {"beats": [{"label": "闯宫", "tags": ["冒险", "宫廷"],
                    "summary": "小人物混入权力中心", "dramatic_function": "转折",
                    "reusable_conflict": "身份错位"}]}
        if name == "plot_skeleton":
            return {"nodes": [{"title": "入宫", "event_summary": "混入皇宫",
                    "preconditions": [], "maps_to_chapter_hint": "1"}]}
        return {}


def _urls():
    load_dotenv()
    return os.environ["MYSQL_URL"], os.environ["PG_URL"]


class ServiceEndToEndTests(unittest.TestCase):
    def test_import_and_retrieve(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        novel = ("第一回 初入皇宫\n韦小宝凭机灵混入皇宫，结识小玄子。\n"
                 "第二回 天地会\n韦小宝身陷天地会与朝廷之间。")
        tid = service.import_novel(
            source_title="鹿鼎记极短版", text=novel,
        )
        self.assertIsInstance(tid, int)

        sb = service.get_style_bible(tid)
        self.assertIn("古雅", sb["tone_tags"])
        self.assertEqual(sb["factions"], ["天地会"])

        beats = service.suggest_plot_beats(tid, query="宫廷", top_k=5)
        self.assertTrue(any("闯宫" == b["label"] for b in beats))

        nodes = service.next_skeleton_nodes(tid, chapter_hint="1")
        self.assertTrue(nodes)
        self.assertEqual(nodes[0]["title"], "入宫")

        passages = service.search_style_passages(tid, query="韦小宝混入皇宫", top_k=3)
        self.assertTrue(passages)
        self.assertTrue(any("皇宫" in p or "韦小宝" in p for p in passages))

    def test_list_templates_and_detail(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        tid = service.import_novel(
            source_title="列表用例", text="第一回 甲\n甲混入皇宫。",
        )
        rows = service.list_templates()
        self.assertTrue(any(r["template_id"] == tid for r in rows))

        detail = service.get_template_detail(tid)
        self.assertIn("style_bible", detail)
        self.assertIn("beats", detail)
        self.assertIn("skeleton", detail)
        self.assertIn("古雅", detail["style_bible"]["tone_tags"])

    def test_tenant_isolation_on_passages(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        tid = service.import_novel(source_title="租户A",
                                   text="第一回 甲\n甲的独特往事内容。")
        # 用不存在的模板 id 检索 → 空（template_id 前缀隔离）
        empty = service.search_style_passages(tid + 999999, query="甲", top_k=3)
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
