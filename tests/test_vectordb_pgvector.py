from __future__ import annotations

import unittest

from datatypes import VectorDoc
from vectordb import PgVectorStore, VectorStore

_URL = "postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test"


def _vec(seed: float) -> list[float]:
    # 造一个方向可控的 512 维向量：前两位用不同 seed，方便断言最近邻。
    v = [0.0] * 512
    v[0] = seed
    v[1] = 1.0 - seed
    return v


class PgVectorStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PgVectorStore(_URL, table="vectordb_probe", dim=512)
        cls.store.reset()  # 每次测试重建表，保证幂等

    def test_是_VectorStore_子类(self):
        self.assertIsInstance(self.store, VectorStore)

    def test_upsert_后能按余弦最近邻检索(self):
        docs = [
            (VectorDoc("u1:p2:a", "act_chunk", "甲", {"user_id": 1}), _vec(0.9)),
            (VectorDoc("u1:p2:b", "act_chunk", "乙", {"user_id": 1}), _vec(0.1)),
        ]
        self.store.upsert(docs)
        hits = self.store.search(_vec(0.85), top_k=1)
        self.assertEqual(hits[0].doc.doc_id, "u1:p2:a")

    def test_upsert_幂等不重复(self):
        doc = (VectorDoc("u9:p9:x", "act_chunk", "丙", {}), _vec(0.5))
        self.store.upsert([doc])
        self.store.upsert([doc])  # 同 id 再写一次
        hits = self.store.search(_vec(0.5), top_k=10)
        ids = [h.doc.doc_id for h in hits]
        self.assertEqual(ids.count("u9:p9:x"), 1)

    def test_按_metadata_过滤(self):
        self.store.upsert(
            [
                (VectorDoc("f:1", "act_chunk", "p1", {"player_id": 1}), _vec(0.3)),
                (VectorDoc("f:2", "act_chunk", "p2", {"player_id": 2}), _vec(0.3)),
            ]
        )
        hits = self.store.search(_vec(0.3), top_k=10, filters={"player_id": 2})
        self.assertTrue(all(h.doc.metadata.get("player_id") == 2 for h in hits))
        self.assertIn("f:2", [h.doc.doc_id for h in hits])

    def test_按_doc_type_顶层列过滤(self):
        # doc_type 是顶层列而非 metadata 键，filter 需命中列而不是 meta->>doc_type。
        self.store.upsert(
            [
                (VectorDoc("dt:sum", "scene_summary", "整幕摘要", {"user_id": 7}), _vec(0.6)),
                (VectorDoc("dt:act", "act_chunk", "行动片段", {"user_id": 7}), _vec(0.6)),
            ]
        )
        hits = self.store.search(
            _vec(0.6), top_k=10, filters={"user_id": 7, "doc_type": "scene_summary"}
        )
        ids = [h.doc.doc_id for h in hits]
        self.assertIn("dt:sum", ids)
        self.assertNotIn("dt:act", ids)  # act_chunk 应被 doc_type 过滤掉


    def test_delete_按_id_删除(self):
        self.store.upsert([(VectorDoc("del:1", "act_chunk", "d", {}), _vec(0.42))])
        self.store.delete(["del:1"])
        hits = self.store.search(_vec(0.42), top_k=50)
        self.assertNotIn("del:1", [h.doc.doc_id for h in hits])


if __name__ == "__main__":
    unittest.main()
