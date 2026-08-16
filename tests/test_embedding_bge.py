from __future__ import annotations

import unittest

from embedding import BgeEmbeddingModel


class BgeEmbeddingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 真加载 bge-small-zh-v1.5（首次会联网下载）。
        cls.model = BgeEmbeddingModel()

    def test_维度为_512(self):
        self.assertEqual(self.model.dimension, 512)

    def test_encode_返回每条文本一个_512_维向量(self):
        vecs = self.model.encode(["修仙者踏入洞府", "商人递来一张地图"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 512)

    def test_语义相近文本余弦相似度更高(self):
        import math

        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb)

        v = self.model.encode(["他在酒馆喝酒", "他于客栈饮酒", "剑气纵横三万里"])
        self.assertGreater(cos(v[0], v[1]), cos(v[0], v[2]))


if __name__ == "__main__":
    unittest.main()
