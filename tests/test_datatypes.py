from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from datatypes.tenancy import template_prefix, template_scope_prefix, tenant_prefix


class TenancyTest(unittest.TestCase):
    def test_tenant_prefix_格式(self):
        self.assertEqual(tenant_prefix(1, 2), "u1:p2:")

    def test_template_prefix_在租户前追加模板段(self):
        self.assertEqual(template_prefix(7, 1, 2), "tmpl:7:u1:p2:")

    def test_template_scope_prefix_只按模板隔离不带租户(self):
        self.assertEqual(template_scope_prefix(7), "tmpl:7:")


class VectorDocTest(unittest.TestCase):
    def test_vector_doc_保存核心字段与元数据(self):
        doc = VectorDoc(
            doc_id="u1:p2:s1:scene_summary",
            doc_type="scene_summary",
            text="正文",
            metadata={"user_id": 1, "player_id": 2},
        )
        self.assertEqual(doc.doc_id, "u1:p2:s1:scene_summary")
        self.assertEqual(doc.metadata["user_id"], 1)

    def test_scored_doc_携带总分与分项因子(self):
        doc = VectorDoc(doc_id="d1", doc_type="act_chunk", text="t", metadata={})
        scored = ScoredDoc(doc=doc, score=0.9, factors={"relevance": 0.8, "recency": 0.5})
        self.assertAlmostEqual(scored.score, 0.9)
        self.assertEqual(scored.factors["relevance"], 0.8)


if __name__ == "__main__":
    unittest.main()
