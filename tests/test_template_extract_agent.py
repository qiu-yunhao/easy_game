from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from StoryTemplate.TemplateChunker import Chunk
from StoryTemplate.TemplateExtractAgent import TemplateExtractAgent


class _FakeClient:
    """按调用序返回预置 JSON 内容，模拟 OpenAI client。"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self._i = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        payload = self._payloads[min(self._i, len(self._payloads) - 1)]
        self._i += 1
        msg = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _agent(payloads):
    return TemplateExtractAgent(client=_FakeClient(payloads), model="fake", base_url="http://x", api_key="k")


class MapChunksTests(unittest.TestCase):
    def test_map_chunks_transfers_order_and_flags(self):
        signal = {
            "style_tone_tags": ["古雅"], "style_devices": ["白描"],
            "characters": [{"name": "甲", "behavior": "拔剑"}],
            "is_event": True, "event_summary": "甲遇袭",
        }
        agent = _agent([signal, signal])
        chunks = [
            Chunk(chunk_id="ch_0", order_index=0, text="甲遇袭。", title="一"),
            Chunk(chunk_id="ch_1", order_index=1, text="乙旁观。", title="二"),
        ]
        signals = agent.map_chunks(chunks)
        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0]["chunk_id"], "ch_0")
        self.assertEqual(signals[1]["order_index"], 1)
        self.assertTrue(signals[0]["is_event"])


class ReduceTests(unittest.TestCase):
    def test_reduce_style_returns_style_bible(self):
        sb = {
            "narrative_voice": "第三人称", "tone_tags": ["古雅"], "prose_rhythm": "长句",
            "signature_devices": ["白描"], "world_premise": "江湖", "cultivation_system": "无",
            "factions": ["天地会"], "key_locations": ["扬州"], "world_rules": [], "lexicon": [],
        }
        agent = _agent([sb])
        result = agent.reduce_style([])
        self.assertEqual(result["narrative_voice"], "第三人称")
        self.assertEqual(result["factions"], ["天地会"])

    def test_reduce_beats_assigns_beat_ids(self):
        agent = _agent([{"beats": [
            {"label": "拜师", "tags": ["成长"], "summary": "弟子拜入门派",
             "dramatic_function": "铺垫", "reusable_conflict": "身份认同"},
        ]}])
        beats = agent.reduce_beats(["某人拜入宗门"])
        self.assertEqual(len(beats), 1)
        self.assertTrue(beats[0]["beat_id"])
        self.assertEqual(beats[0]["label"], "拜师")

    def test_reduce_skeleton_sorts_and_ids(self):
        agent = _agent([{"nodes": [
            {"title": "开端", "event_summary": "起", "preconditions": [], "maps_to_chapter_hint": "1"},
            {"title": "发展", "event_summary": "承", "preconditions": ["开端"], "maps_to_chapter_hint": "2"},
        ]}])
        # 事件信号乱序传入，验证按 order_index 排
        from StoryTemplate.TemplateChunker import Chunk  # noqa
        sig = lambda oi, s: {"chunk_id": f"c{oi}", "order_index": oi, "style_tone_tags": [],
                             "style_devices": [], "characters": [], "is_event": True, "event_summary": s}
        nodes = agent.reduce_skeleton([sig(2, "承"), sig(1, "起")])
        self.assertEqual([n["order_index"] for n in nodes], [0, 1])
        self.assertTrue(all(n["node_id"] for n in nodes))


if __name__ == "__main__":
    unittest.main()
