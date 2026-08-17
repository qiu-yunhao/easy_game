from __future__ import annotations

import unittest
from typing import Any, Sequence

from datatypes import ScoredDoc, VectorDoc
from Recall.service.recall_service import RecallService


class FakeEmbedding:
    """假 embedding：把文本长度映射成定长向量，只为验证接线，不做真编码。"""

    def __init__(self, dim: int = 4) -> None:
        self._dim = dim
        self.encoded: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.encoded.extend(texts)
        return [[float(len(t))] * self._dim for t in texts]


class FakeVectorStore:
    """假向量库：记录 upsert 的行，供断言 embed→upsert 数据流。"""

    def __init__(self) -> None:
        self.rows: list[tuple[VectorDoc, list[float]]] = []

    def upsert(self, rows: Sequence[tuple[VectorDoc, list[float]]]) -> None:
        self.rows.extend(rows)

    def search(self, query_vector, *, top_k=10, filters=None):
        return []

    def delete(self, ids):
        pass


class FakeHybrid:
    """假混合检索：按注入的脚本按 doc_type 返回结果，并记录每次 search 的 filters。"""

    def __init__(self, results_by_doc_type: dict[str, list[ScoredDoc]]) -> None:
        self._results = results_by_doc_type
        self.calls: list[dict[str, Any]] = []

    def search(self, query, *, top_k=10, filters=None, weights=None, fetch_k=50):
        self.calls.append({"query": query, "top_k": top_k, "filters": dict(filters or {})})
        doc_type = (filters or {}).get("doc_type")
        return list(self._results.get(doc_type, []))


def _scene(**overrides):
    base = {
        "history": [
            {"turn": 10, "actor": "hero", "mode": "dialogue", "content": "line-10", "importance_score": 0.5},
            {"turn": 11, "actor": "merchant", "mode": "dialogue", "content": "line-11", "importance_score": 0.7},
        ],
        "scene_memory": {
            "turn_range": "10-11",
            "summary": "主角在酒馆遇到商人。",
            "key_events": ["达成交易"],
            "compressed_blocks": [{"max_score": 0.9}],
        },
        "scene_id": "c1-scene-1",
        "chapter_id": "c1",
    }
    base.update(overrides)
    return base


def _scored(doc_id: str, doc_type: str, scene_id: str, score: float) -> ScoredDoc:
    return ScoredDoc(
        doc=VectorDoc(
            doc_id=doc_id,
            doc_type=doc_type,
            text=f"text-{doc_id}",
            metadata={"scene_id": scene_id, "doc_type": doc_type},
        ),
        score=score,
    )


class IndexCompletedScenesTests(unittest.TestCase):
    def setUp(self):
        self.embedding = FakeEmbedding(dim=4)
        self.store = FakeVectorStore()
        self.hybrid = FakeHybrid({})
        self.service = RecallService(
            embedding=self.embedding,
            vector_store=self.store,
            hybrid=self.hybrid,
        )

    def test_index_embeds_and_upserts_all_docs(self):
        self.service.index_completed_scenes([_scene()], user_id=7, player_id=3)
        # 一幕产出 1 摘要 + 1 片段（2 条 history、chunk_size 默认 4）= 2 条文档
        self.assertEqual(len(self.store.rows), 2)
        doc_types = {doc.doc_type for doc, _ in self.store.rows}
        self.assertEqual(doc_types, {"scene_summary", "act_chunk"})

    def test_upserted_vector_dim_matches_embedding(self):
        self.service.index_completed_scenes([_scene()], user_id=7, player_id=3)
        for _, vector in self.store.rows:
            self.assertEqual(len(vector), 4)

    def test_index_carries_tenant_keys_in_metadata(self):
        self.service.index_completed_scenes([_scene()], user_id=7, player_id=3)
        for doc, _ in self.store.rows:
            self.assertEqual(doc.metadata["user_id"], 7)
            self.assertEqual(doc.metadata["player_id"], 3)

    def test_empty_scenes_noop(self):
        self.service.index_completed_scenes([], user_id=7, player_id=3)
        self.assertEqual(self.store.rows, [])
        self.assertEqual(self.embedding.encoded, [])


class QueryRecallTests(unittest.TestCase):
    def setUp(self):
        self.embedding = FakeEmbedding(dim=4)
        self.store = FakeVectorStore()
        # 粗召回命中一幕 c1-scene-1；细召回在该幕内返回两条片段。
        self.hybrid = FakeHybrid(
            {
                "scene_summary": [_scored("sum-1", "scene_summary", "c1-scene-1", 0.9)],
                "act_chunk": [
                    _scored("chunk-1", "act_chunk", "c1-scene-1", 0.8),
                    _scored("chunk-2", "act_chunk", "c1-scene-1", 0.6),
                ],
            }
        )
        self.service = RecallService(
            embedding=self.embedding,
            vector_store=self.store,
            hybrid=self.hybrid,
        )

    def test_coarse_search_filters_by_tenant_and_summary_type(self):
        self.service.query_recall("酒馆发生了什么", user_id=7, player_id=3)
        coarse = self.hybrid.calls[0]["filters"]
        self.assertEqual(coarse["user_id"], 7)
        self.assertEqual(coarse["player_id"], 3)
        self.assertEqual(coarse["doc_type"], "scene_summary")

    def test_fine_search_filters_by_hit_scene_and_chunk_type(self):
        self.service.query_recall("酒馆发生了什么", user_id=7, player_id=3)
        fine = self.hybrid.calls[1]["filters"]
        self.assertEqual(fine["doc_type"], "act_chunk")
        self.assertEqual(fine["scene_id"], "c1-scene-1")
        self.assertEqual(fine["user_id"], 7)
        self.assertEqual(fine["player_id"], 3)

    def test_returns_fine_grained_chunks(self):
        results = self.service.query_recall("酒馆发生了什么", user_id=7, player_id=3)
        ids = [r.doc.doc_id for r in results]
        self.assertIn("chunk-1", ids)
        self.assertIn("chunk-2", ids)

    def test_no_coarse_hit_returns_empty(self):
        empty_hybrid = FakeHybrid({"scene_summary": [], "act_chunk": []})
        service = RecallService(
            embedding=self.embedding, vector_store=self.store, hybrid=empty_hybrid
        )
        results = service.query_recall("无关查询", user_id=7, player_id=3)
        self.assertEqual(results, [])
        # 粗召回落空则不应再发起细召回。
        self.assertEqual(len(empty_hybrid.calls), 1)


if __name__ == "__main__":
    unittest.main()
