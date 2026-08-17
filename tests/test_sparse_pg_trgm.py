from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from hybrid_retrieval.sparse import PgTrgmSparseSearch
from vectordb import PgVectorStore

_URL = "postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test"
_TABLE = "sparse_probe"


def _vec(seed: float) -> list[float]:
    v = [0.0] * 512
    v[0] = seed
    v[1] = 1.0 - seed
    return v


class PgTrgmSparseSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 复用同一张向量表：稀疏检索直接查 text/meta 列，与稠密共库同表。
        cls.store = PgVectorStore(_URL, table=_TABLE, dim=512)
        cls.store.reset()
        cls.store.upsert(
            [
                (VectorDoc("u1:p2:a", "act_chunk", "在酒馆里与掌柜的争执", {"player_id": 2}), _vec(0.9)),
                (VectorDoc("u1:p2:b", "act_chunk", "山巅论剑输给了对手", {"player_id": 2}), _vec(0.1)),
                (VectorDoc("u1:p3:c", "act_chunk", "酒馆门口捡到钱袋", {"player_id": 3}), _vec(0.5)),
            ]
        )
        cls.sparse = PgTrgmSparseSearch(_URL, table=_TABLE)

    def test_关键词子串命中返回_ScoredDoc(self):
        hits = self.sparse("酒馆", top_k=10)
        self.assertTrue(all(isinstance(h, ScoredDoc) for h in hits))
        ids = {h.doc.doc_id for h in hits}
        # "酒馆" 出现在 a 与 c 中，b 不含。
        self.assertIn("u1:p2:a", ids)
        self.assertIn("u1:p3:c", ids)
        self.assertNotIn("u1:p2:b", ids)

    def test_带完整文档实体便于补取(self):
        hits = self.sparse("酒馆", top_k=10)
        target = next(h for h in hits if h.doc.doc_id == "u1:p2:a")
        self.assertEqual(target.doc.text, "在酒馆里与掌柜的争执")
        self.assertEqual(target.doc.metadata.get("player_id"), 2)

    def test_按_metadata_过滤(self):
        hits = self.sparse("酒馆", top_k=10, filters={"player_id": 2})
        ids = {h.doc.doc_id for h in hits}
        self.assertIn("u1:p2:a", ids)
        self.assertNotIn("u1:p3:c", ids)  # player_id=3 被过滤掉

    def test_无命中返回空(self):
        hits = self.sparse("完全不相干的词", top_k=10)
        self.assertEqual(hits, [])

    def test_可作为回调传给_HybridRetrieval(self):
        # 回调签名须匹配 SparseSearch：(query, *, top_k, filters=None)。
        hits = self.sparse("酒馆", top_k=5, filters=None)
        self.assertLessEqual(len(hits), 5)


if __name__ == "__main__":
    unittest.main()
