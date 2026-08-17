from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from PlayerControl.PlayerCommandTools import (
    PLAYER_TOOL_NAMES,
    PlayerCommandToolRuntime,
    infer_player_tool_call,
    looks_like_tool_request,
)


class FakeRecallService:
    """记录 query_recall 调用并返回预置结果，供断言执行器编排。"""

    def __init__(self, results=None):
        self.results = results or []
        self.calls: list[tuple[str, int, int]] = []

    def query_recall(self, query, *, user_id, player_id, top_k=10, coarse_k=5):
        self.calls.append((query, user_id, player_id))
        return list(self.results)


def _scored(scene_id, text, score):
    doc = VectorDoc(
        doc_id=f"u7:p3:{scene_id}:act_chunk:0",
        doc_type="act_chunk",
        text=text,
        metadata={"scene_id": scene_id, "chapter_id": "c1"},
    )
    return ScoredDoc(doc=doc, score=score, factors={})


def _runtime(*, recall_service, user_id=7, player_id=3):
    """装配一个只关注回忆工具的执行器；存档存储用哨兵占位（本工具不碰它）。"""
    return PlayerCommandToolRuntime(
        resolve_store=lambda: object(),
        resolve_context=lambda: {"user_id": user_id, "player_id": player_id},
        export_session_snapshot=lambda: {},
        load_session_snapshot=lambda snap: {},
        activate_context=lambda u, p: None,
        resolve_recall_service=lambda: recall_service,
    )


class QueryRecallRegistrationTests(unittest.TestCase):
    def test_tool_registered_in_player_tool_names(self):
        self.assertIn("query_recall", PLAYER_TOOL_NAMES)

    def test_recall_keyword_matches_tool(self):
        self.assertTrue(looks_like_tool_request("我之前经历过什么"))
        call = infer_player_tool_call("我之前经历过什么")
        self.assertIsNotNone(call)
        self.assertEqual(call["name"], "query_recall")


class QueryRecallExecutorTests(unittest.TestCase):
    def test_returns_hits_text_and_payload(self):
        service = FakeRecallService(results=[_scored("c1-scene-1", "拜师入门", 0.9)])
        runtime = _runtime(recall_service=service)
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "拜师"}}
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["tool_name"], "query_recall")
        self.assertIn("拜师入门", result["text"])
        self.assertEqual(service.calls[0], ("拜师", 7, 3))
        self.assertEqual(len(result["payload"]["results"]), 1)

    def test_no_hits_returns_friendly_message(self):
        service = FakeRecallService(results=[])
        runtime = _runtime(recall_service=service)
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "不存在的事"}}
        )
        # 无命中不是错误：返回成功 + 友好文案，payload.results 为空。
        self.assertTrue(result["success"])
        self.assertEqual(result["payload"]["results"], [])

    def test_empty_query_is_rejected(self):
        service = FakeRecallService()
        runtime = _runtime(recall_service=service)
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "   "}}
        )
        self.assertFalse(result["success"])
        self.assertEqual(service.calls, [])

    def test_service_unbound_reports_disabled(self):
        runtime = _runtime(recall_service=None)
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "拜师"}}
        )
        # 回忆服务未注入时优雅失败，明确告知未启用，不抛异常。
        self.assertFalse(result["success"])
        self.assertIn("未启用", result["text"])

    def test_no_recall_resolver_reports_disabled(self):
        # 完全没提供 resolve_recall_service 回调时也应优雅失败。
        runtime = PlayerCommandToolRuntime(
            resolve_store=lambda: object(),
            resolve_context=lambda: {"user_id": 7, "player_id": 3},
            export_session_snapshot=lambda: {},
            load_session_snapshot=lambda snap: {},
            activate_context=lambda u, p: None,
        )
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "拜师"}}
        )
        self.assertFalse(result["success"])

    def test_missing_player_context_fails(self):
        service = FakeRecallService()
        runtime = _runtime(recall_service=service, user_id=None, player_id=None)
        result = runtime.execute(
            {"should_call": True, "name": "query_recall", "arguments": {"query": "拜师"}}
        )
        self.assertFalse(result["success"])
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
