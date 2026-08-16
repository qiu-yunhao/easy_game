from __future__ import annotations

import unittest

from embedding import EmbeddingModel


class _FakeModel(EmbeddingModel):
    @property
    def dimension(self) -> int:
        return 4

    def encode(self, texts):
        return [[float(len(t))] * 4 for t in texts]


class EmbeddingInterfaceTest(unittest.TestCase):
    def test_可被_mock_实现供上层单测(self):
        model = _FakeModel()
        self.assertEqual(model.dimension, 4)
        vecs = model.encode(["ab", "abc"])
        self.assertEqual(vecs, [[2.0] * 4, [3.0] * 4])


if __name__ == "__main__":
    unittest.main()
