from __future__ import annotations

import unittest

from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state
from Memory.default_provider import DefaultActorMemoryProvider
from datatypes import ScoredDoc, VectorDoc


def _profiles():
    return {
        "A": ensure_character_profile({
            "character_id": "A", "name": "甲", "persona": [],
            "base_style": "", "base_relationship": {}, "secrets": [],
            "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
            "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
        }),
    }


def _state(*, intent: str = "", history_content: str = "曾在此地遇袭"):
    runtime = create_character_runtime_state(intent=intent)
    return {
        "scene": {"location_id": "hall", "on_stage": ["A"]},
        "characters": {"A": runtime},
        "history": [
            {"turn": 1, "actor": "A", "mode": "speak", "content": history_content,
             "on_stage": ["A"], "location_id": "hall"},
        ],
    }


class _FakeRecall:
    """记录调用参数、返回预置结果的假回忆服务。"""

    def __init__(self, results=None, *, raises=False):
        self._results = results or []
        self._raises = raises
        self.calls = []

    def query_recall(self, query, *, user_id, player_id, top_k=10):
        self.calls.append({"query": query, "user_id": user_id, "player_id": player_id, "top_k": top_k})
        if self._raises:
            raise RuntimeError("检索后端炸了")
        return self._results


def _scored(text="往事一"):
    return ScoredDoc(
        doc=VectorDoc(doc_id="u1:p2:s1:c0", doc_type="act_chunk", text=text,
                      metadata={"scene_id": "s1", "chapter_id": "c0"}),
        score=0.9,
    )


class RetrieveFillsContextTests(unittest.TestCase):
    def test_retrieved_filled_when_service_and_tenant_present(self):
        fake = _FakeRecall(results=[_scored("上次在此地遇袭")])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(len(ctx.retrieved), 1)
        self.assertEqual(ctx.retrieved[0].doc.text, "上次在此地遇袭")
        # 租户与 query 已传给 service
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["user_id"], 1)
        self.assertEqual(call["player_id"], 2)

    def test_query_combines_intent_and_recent_dialogue(self):
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        provider.build("A", _state(intent="警惕四周", history_content="曾在此地遇袭"))
        query = fake.calls[0]["query"]
        self.assertIn("警惕四周", query)
        self.assertIn("曾在此地遇袭", query)


class RetrieveGracefulDegradeTests(unittest.TestCase):
    def test_no_service_returns_empty(self):
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(ctx.retrieved, [])

    def test_missing_tenant_returns_empty_and_skips_service(self):
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
        )  # 未设租户
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(ctx.retrieved, [])
        self.assertEqual(fake.calls, [])  # 租户缺失时不该调 service

    def test_empty_query_skips_service(self):
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        # intent 空 + history 空文本 → query 为空 → 不调 service
        state = {
            "scene": {"location_id": "hall", "on_stage": ["A"]},
            "characters": {"A": create_character_runtime_state(intent="")},
            "history": [],
        }
        ctx = provider.build("A", state)
        self.assertEqual(ctx.retrieved, [])
        self.assertEqual(fake.calls, [])

    def test_service_exception_degrades_to_empty(self):
        fake = _FakeRecall(raises=True)
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))  # 不应抛
        self.assertEqual(ctx.retrieved, [])


class SetTenantTests(unittest.TestCase):
    def test_set_tenant_updates_ids_passed_to_service(self):
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
        )
        provider.set_tenant(user_id=7, player_id=8)
        provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(fake.calls[0]["user_id"], 7)
        self.assertEqual(fake.calls[0]["player_id"], 8)


if __name__ == "__main__":
    unittest.main()
