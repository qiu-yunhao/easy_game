from __future__ import annotations

import unittest

from Actor.ActorFormatter import _build_actor_payload, _format_recalled
from CharacterProfile import ensure_character_profile
from Memory.context import ActorMemoryContext, LongTermView
from datatypes import ScoredDoc, VectorDoc


def _scored(text="上次在此地遇袭", *, scene_id="s1", chapter_id="c0", score=0.9):
    return ScoredDoc(
        doc=VectorDoc(
            doc_id="u1:p2:s1:c0", doc_type="act_chunk", text=text,
            metadata={"scene_id": scene_id, "chapter_id": chapter_id},
        ),
        score=score,
    )


def _ctx(retrieved):
    return ActorMemoryContext(
        actor_id="A",
        persona=ensure_character_profile({
            "character_id": "A", "name": "甲", "persona": [],
            "base_style": "", "base_relationship": {}, "secrets": [],
            "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
            "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
        }),
        short_term=[],
        long_term=LongTermView(consolidated=[], long_term=[], pinned=[]),
        retrieved=retrieved,
    )


def _state():
    return {
        "plot": {
            "chapter_id": "c0", "scene_id": "s1", "chapter_goal": "",
            "plot_flags": {},
        },
        "runtime": {"next_act": None},
        "characters": {"A": {"intent": "", "memory": {}}},
        "scene_plan": {},
        "scene": {"location_id": "hall", "on_stage": ["A"]},
        "director_brief": {},
    }


class FormatRecalledTests(unittest.TestCase):
    def test_empty_retrieved_returns_empty_list(self):
        self.assertEqual(_format_recalled([]), [])

    def test_scored_docs_compressed_to_prompt_dicts(self):
        out = _format_recalled([_scored("往事一", scene_id="sA", chapter_id="cB", score=0.7)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], {
            "scene_id": "sA", "chapter_id": "cB", "text": "往事一", "score": 0.7,
        })


class PayloadIncludesRecalledTests(unittest.TestCase):
    def test_payload_carries_recalled_memories(self):
        payload = _build_actor_payload(_state(), _ctx([_scored("上次在此地遇袭")]))
        self.assertIn("recalled_memories", payload)
        self.assertEqual(len(payload["recalled_memories"]), 1)
        self.assertEqual(payload["recalled_memories"][0]["text"], "上次在此地遇袭")

    def test_payload_recalled_empty_when_no_retrieval(self):
        payload = _build_actor_payload(_state(), _ctx([]))
        self.assertEqual(payload["recalled_memories"], [])


if __name__ == "__main__":
    unittest.main()
