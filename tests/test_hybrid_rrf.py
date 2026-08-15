from __future__ import annotations

import unittest

from hybrid_retrieval.rrf import rrf_fuse


class RrfTest(unittest.TestCase):
    def test_两条排名靠前的文档融合分更高(self):
        dense = ["a", "b", "c"]
        sparse = ["b", "a", "d"]
        fused = rrf_fuse([dense, sparse], k=60)
        # a、b 在两路都靠前，应排在只在单路出现的 c/d 之前
        top2 = [doc_id for doc_id, _ in fused[:2]]
        self.assertIn("a", top2)
        self.assertIn("b", top2)

    def test_单路缺失的文档仍可入榜(self):
        fused = dict(rrf_fuse([["a"], ["b"]], k=60))
        self.assertIn("a", fused)
        self.assertIn("b", fused)


if __name__ == "__main__":
    unittest.main()
