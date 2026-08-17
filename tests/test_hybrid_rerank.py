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

    def test_原始量纲因子先归一化不压垮relevance(self):
        # 真实场景：relevance 是 RRF 分(~0.016 量级)，recency/importance 是原始
        # turn/评分(0-12、0-5)。默认权重下，语义最相关(relevance 最高)的应排第一，
        # 而不该被量纲更大的 importance/recency 淹没。
        docs = [
            _sd("relevant", relevance=1 / 61, recency=2.0, importance=3.0),
            _sd("off_topic", relevance=1 / 62, recency=12.0, importance=5.0),
        ]
        out = rerank(docs)  # 默认 0.6/0.2/0.2
        self.assertEqual(out[0].doc.doc_id, "relevant")

    def test_单候选归一化不除零(self):
        # 候选集只有一个时 max==min，归一化不应除零。
        out = rerank([_sd("only", relevance=0.016, recency=7.0, importance=4.0)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].doc.doc_id, "only")


if __name__ == "__main__":
    unittest.main()
