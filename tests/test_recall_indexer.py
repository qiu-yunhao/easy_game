from __future__ import annotations

import unittest

from Recall.domain.documents import RecallDoc
from Recall.indexing.scene_indexer import (
    build_act_chunk_docs,
    build_scene_docs,
    build_scene_summary_doc,
)


def _scene_memory(**overrides):
    base = {
        "turn_range": "10-15",
        "summary": "主角在酒馆遇到神秘商人。",
        "key_events": ["商人透露了地图线索", "主角付了定金"],
        "revealed_facts": [],
        "active_conflicts": [],
        "open_loops": [],
        "recent_speakers": [],
        "response_pressure": [],
        "tension_trend": "stable",
        "focus_suggestion": None,
        "compressed_blocks": [
            {
                "kind": "summary",
                "bucket": "high",
                "turn_start": 10,
                "turn_end": 12,
                "raw_items": [],
                "summary": "",
                "key_points": [],
                "actors": [],
                "avg_score": 0.4,
                "max_score": 0.8,
            },
            {
                "kind": "raw",
                "bucket": "mid",
                "turn_start": 13,
                "turn_end": 15,
                "raw_items": [],
                "summary": "",
                "key_points": [],
                "actors": [],
                "avg_score": 0.3,
                "max_score": 0.5,
            },
        ],
    }
    base.update(overrides)
    return base


def _history(n_start: int, n_end: int, actor: str = "merchant"):
    return [
        {
            "turn": t,
            "actor": actor,
            "mode": "dialogue",
            "content": f"line-{t}",
            "importance_score": 0.2 * (t - n_start + 1),
        }
        for t in range(n_start, n_end + 1)
    ]


class BuildSceneSummaryDocTests(unittest.TestCase):
    def test_text_combines_summary_and_key_events(self):
        doc = build_scene_summary_doc(
            _scene_memory(),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertEqual(doc.doc_type, "scene_summary")
        self.assertIn("主角在酒馆遇到神秘商人。", doc.text)
        self.assertIn("商人透露了地图线索", doc.text)
        self.assertIn("主角付了定金", doc.text)

    def test_importance_is_max_of_block_max_scores(self):
        doc = build_scene_summary_doc(
            _scene_memory(),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertAlmostEqual(doc.importance, 0.8)

    def test_turn_range_parsed(self):
        doc = build_scene_summary_doc(
            _scene_memory(turn_range="10-15"),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertEqual(doc.turn_start, 10)
        self.assertEqual(doc.turn_end, 15)

    def test_handles_missing_blocks_and_bad_turn_range(self):
        doc = build_scene_summary_doc(
            _scene_memory(compressed_blocks=[], turn_range=""),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertEqual(doc.importance, 0.0)
        self.assertEqual((doc.turn_start, doc.turn_end), (0, 0))

    def test_doc_id_is_stable(self):
        kwargs = dict(scene_id="s1", chapter_id="c1", user_id=7, player_id=3)
        a = build_scene_summary_doc(_scene_memory(), **kwargs)
        b = build_scene_summary_doc(_scene_memory(), **kwargs)
        self.assertEqual(a.doc_id, b.doc_id)

    def test_doc_id_includes_tenant_keys(self):
        base = _scene_memory()
        a = build_scene_summary_doc(base, scene_id="s1", chapter_id="c1", user_id=7, player_id=3)
        b = build_scene_summary_doc(base, scene_id="s1", chapter_id="c1", user_id=9, player_id=3)
        c = build_scene_summary_doc(base, scene_id="s1", chapter_id="c1", user_id=7, player_id=5)
        # Same scene_id across different tenants must NOT collide.
        self.assertNotEqual(a.doc_id, b.doc_id)
        self.assertNotEqual(a.doc_id, c.doc_id)

    def test_empty_summary_and_events_returns_none(self):
        doc = build_scene_summary_doc(
            _scene_memory(summary="", key_events=[]),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertIsNone(doc)

    def test_single_turn_range_parsed(self):
        doc = build_scene_summary_doc(
            _scene_memory(turn_range="12"),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertEqual((doc.turn_start, doc.turn_end), (12, 12))


class BuildActChunkDocsTests(unittest.TestCase):
    def test_chunks_group_by_size(self):
        docs = build_act_chunk_docs(
            _history(1, 10),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
            chunk_size=4,
        )
        self.assertEqual(len(docs), 3)  # 4 + 4 + 2
        self.assertTrue(all(d.doc_type == "act_chunk" for d in docs))

    def test_chunk_turn_bounds(self):
        docs = build_act_chunk_docs(
            _history(1, 6),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
            chunk_size=4,
        )
        self.assertEqual((docs[0].turn_start, docs[0].turn_end), (1, 4))
        self.assertEqual((docs[1].turn_start, docs[1].turn_end), (5, 6))

    def test_chunk_text_includes_actor_and_content(self):
        docs = build_act_chunk_docs(
            _history(1, 2, actor="hero"),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
            chunk_size=4,
        )
        self.assertIn("hero", docs[0].text)
        self.assertIn("line-1", docs[0].text)
        self.assertIn("line-2", docs[0].text)

    def test_chunk_importance_is_max_of_scores(self):
        docs = build_act_chunk_docs(
            _history(1, 2),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
            chunk_size=4,
        )
        # scores: 0.2, 0.4 -> max 0.4
        self.assertAlmostEqual(docs[0].importance, 0.4)

    def test_empty_history_yields_no_docs(self):
        docs = build_act_chunk_docs(
            [],
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        self.assertEqual(docs, [])

    def test_doc_ids_unique_and_stable(self):
        kwargs = dict(scene_id="s1", chapter_id="c1", user_id=7, player_id=3, chunk_size=4)
        first = build_act_chunk_docs(_history(1, 10), **kwargs)
        second = build_act_chunk_docs(_history(1, 10), **kwargs)
        self.assertEqual([d.doc_id for d in first], [d.doc_id for d in second])
        self.assertEqual(len({d.doc_id for d in first}), len(first))


class BuildSceneDocsTests(unittest.TestCase):
    def test_combines_summary_and_chunks(self):
        docs = build_scene_docs(
            history=_history(10, 15),
            scene_memory=_scene_memory(),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
            chunk_size=4,
        )
        types = [d.doc_type for d in docs]
        self.assertEqual(types.count("scene_summary"), 1)
        self.assertEqual(types.count("act_chunk"), 2)  # 6 items / 4

    def test_all_docs_carry_scene_metadata(self):
        docs = build_scene_docs(
            history=_history(10, 12),
            scene_memory=_scene_memory(),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        for d in docs:
            self.assertEqual(d.scene_id, "s1")
            self.assertEqual(d.chapter_id, "c1")
            self.assertEqual(d.user_id, 7)
            self.assertEqual(d.player_id, 3)
            self.assertIsInstance(d, RecallDoc)

    def test_empty_summary_omits_summary_doc(self):
        docs = build_scene_docs(
            history=_history(10, 12),
            scene_memory=_scene_memory(summary="", key_events=[]),
            scene_id="s1",
            chapter_id="c1",
            user_id=7,
            player_id=3,
        )
        types = [d.doc_type for d in docs]
        self.assertNotIn("scene_summary", types)
        self.assertTrue(all(t == "act_chunk" for t in types))


if __name__ == "__main__":
    unittest.main()
