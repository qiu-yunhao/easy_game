from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from hybrid_retrieval import HybridRetrieval
from hybrid_retrieval.rerank import RerankWeights


class _FakeEmbedding:
    @property
    def dimension(self):
        return 4

    def encode(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class _FakeVectorStore:
    def upsert(self, rows):
        pass

    def delete(self, ids):
        pass

    def search(self, query_vector, *, top_k=10, filters=None):
        return [
            ScoredDoc(VectorDoc("a", "act_chunk", "甲", {"importance": 0.9}), 0.95),
            ScoredDoc(VectorDoc("b", "act_chunk", "乙", {"importance": 0.1}), 0.90),
        ]


def _fake_sparse(query, *, top_k, filters=None):
    return ["b", "a"]


class HybridRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.retr = HybridRetrieval(
            embedding=_FakeEmbedding(),
            vector_store=_FakeVectorStore(),
            sparse_search=_fake_sparse,
        )

    def test_端到端返回_ScoredDoc_列表(self):
        out = self.retr.search("酒馆里发生了什么", top_k=2)
        self.assertTrue(all(isinstance(x, ScoredDoc) for x in out))
        self.assertLessEqual(len(out), 2)

    def test_权重可从调用方传入(self):
        out = self.retr.search(
            "酒馆里发生了什么",
            top_k=2,
            weights=RerankWeights(relevance=0.0, recency=0.0, importance=1.0),
        )
        # importance 权重独大时，metadata.importance 高的 a 排第一
        self.assertEqual(out[0].doc.doc_id, "a")


if __name__ == "__main__":
    unittest.main()
