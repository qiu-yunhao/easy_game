from __future__ import annotations

import unittest

from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state
from Memory.default_provider import DefaultActorMemoryProvider
from datatypes import ScoredDoc, VectorDoc


def _profiles():
    # A 是 L1 主角:唯一有资格获得长期召回的角色(spec 4.2)。
    return {
        "A": ensure_character_profile({
            "character_id": "A", "name": "甲", "persona": [],
            "base_style": "", "base_relationship": {}, "secrets": [],
            "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
            "agent_type": "L1", "story_layer": "core", "storage_mode": "inline",
        }),
    }


def _state(*, intent: str = "", history_content: str = "曾在此地遇袭"):
    runtime = create_character_runtime_state(intent=intent)
    return {
        "scene": {"location_id": "hall", "on_stage": ["A"]},
        "characters": {"A": runtime},
        # 新契约:retrieve 读 runtime.turn_index 计算召回窗口。用 100 让窗口数学被真正验证。
        "runtime": {"turn_index": 100},
        "history": [
            {"turn": 1, "actor": "A", "mode": "speak", "content": history_content,
             "on_stage": ["A"], "location_id": "hall"},
        ],
    }


class _FakeRecall:
    """记录调用参数、返回预置结果的假回忆服务(新契约:recall_memory_blocks)。"""

    def __init__(self, results=None, *, raises=False):
        self._results = results or []
        self._raises = raises
        self.calls = []

    def recall_memory_blocks(self, query, *, user_id, player_id, actor_id, window_start, top_k=5):
        self.calls.append({
            "query": query, "user_id": user_id, "player_id": player_id,
            "actor_id": actor_id, "window_start": window_start, "top_k": top_k,
        })
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
            user_id=1, player_id=2, summary_horizon_turns=45,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(len(ctx.retrieved), 1)
        self.assertEqual(ctx.retrieved[0].doc.text, "上次在此地遇袭")
        # 租户、actor 与召回窗口已传给 service。
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["user_id"], 1)
        self.assertEqual(call["player_id"], 2)
        self.assertEqual(call["actor_id"], "A")
        # window_start = max(0, turn_index - horizon + 1) = max(0, 100-45+1) = 56。
        self.assertEqual(call["window_start"], max(0, 100 - 45 + 1))
        self.assertEqual(call["window_start"], 56)

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
        # 无 service:即使 L1 也降级为空。
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(ctx.retrieved, [])

    def test_missing_tenant_returns_empty_and_skips_service(self):
        # 缺租户:L1 有资格,但 user_id/player_id 缺失时不该调 service。
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
        )  # 未设租户
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(ctx.retrieved, [])
        self.assertEqual(fake.calls, [])  # 租户缺失时不该调 service

    def test_empty_query_skips_service(self):
        # 空 query:L1 且有租户,但检索词为空时不该调 service。
        fake = _FakeRecall(results=[_scored()])
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        # intent 空 + history 空文本 → query 为空 → 不调 service
        state = {
            "scene": {"location_id": "hall", "on_stage": ["A"]},
            "characters": {"A": create_character_runtime_state(intent="")},
            "runtime": {"turn_index": 100},
            "history": [],
        }
        ctx = provider.build("A", state)
        self.assertEqual(ctx.retrieved, [])
        self.assertEqual(fake.calls, [])

    def test_service_exception_degrades_to_empty(self):
        # service 抛异常:吞掉并降级为空,不打断对话链路。
        fake = _FakeRecall(raises=True)
        provider = DefaultActorMemoryProvider(
            character_profiles=_profiles(), recall_service=fake,
            user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))  # 不应抛
        self.assertEqual(ctx.retrieved, [])
        # 确认确实是"抛异常被吞"这条路径:service 被调过一次。
        self.assertEqual(len(fake.calls), 1)


class NpcActorGateTests(unittest.TestCase):
    def test_npc_actor_gets_no_recall(self):
        # 非 L1(agent_type="actor")的 NPC:直接短路,service 从不被调用。
        fake = _FakeRecall(results=[_scored()])
        profiles = {
            "A": ensure_character_profile({
                "character_id": "A", "name": "甲", "persona": [],
                "base_style": "", "base_relationship": {}, "secrets": [],
                "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
                "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
            }),
        }
        provider = DefaultActorMemoryProvider(
            character_profiles=profiles, recall_service=fake,
            user_id=1, player_id=2,
        )
        ctx = provider.build("A", _state(intent="警惕四周"))
        self.assertEqual(ctx.retrieved, [])
        self.assertEqual(fake.calls, [])


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
