from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from hybrid_retrieval.rerank import RerankWeights, rerank


def _sd(doc_id, relevance, recency, importance):
    doc = VectorDoc(doc_id, "act_chunk", doc_id, {})
    return ScoredDoc(
        doc=doc,
        score=relevance,
        factors={"relevance": relevance, "recency": recency, "importance": importance},
    )


class RerankTest(unittest.TestCase):
    def test_按加权三因子重排(self):
        docs = [
            _sd("low_rel", relevance=0.2, recency=1.0, importance=1.0),
            _sd("high_rel", relevance=0.9, recency=0.1, importance=0.1),
        ]
        # 关联性权重压倒性时，high_rel 应排第一
        out = rerank(docs, weights=RerankWeights(relevance=1.0, recency=0.0, importance=0.0))
        self.assertEqual(out[0].doc.doc_id, "high_rel")

    def test_权重可覆盖偏向新近度(self):
        docs = [
            _sd("old", relevance=0.9, recency=0.0, importance=0.5),
            _sd("new", relevance=0.5, recency=1.0, importance=0.5),
        ]
        out = rerank(docs, weights=RerankWeights(relevance=0.1, recency=1.0, importance=0.0))
        self.assertEqual(out[0].doc.doc_id, "new")


if __name__ == "__main__":
    unittest.main()
