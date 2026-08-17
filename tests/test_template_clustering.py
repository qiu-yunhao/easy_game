from __future__ import annotations

import unittest

from embedding import BgeEmbeddingModel
from StoryTemplate.TemplateClustering import TemplateClustering


class ClusteringRealBgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clustering = TemplateClustering(BgeEmbeddingModel())

    def test_embed_returns_512_dim(self):
        vecs = self.clustering.embed(["拜师学艺", "夺宝奇遇"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 512)

    def test_dedup_groups_similar_beats(self):
        beats = ["他拜入宗门成为弟子", "少年正式拜师入门修行", "两人在擂台上激烈交手"]
        clusters = self.clustering.dedup_beats(beats)
        # 前两条语义近 → 同簇；第三条独立。共 2 簇。
        self.assertEqual(len(clusters), 2)
        sizes = sorted(len(c) for c in clusters)
        self.assertEqual(sizes, [1, 2])

    def test_merge_characters_by_name_or_vector(self):
        names = ["张三", "张三", "李四"]
        vecs = self.clustering.embed([
            "第三章的张三行侠仗义", "第八十章的张三行侠仗义", "李四阴险狡诈",
        ])
        clusters = self.clustering.merge_characters(names, vecs)
        self.assertEqual(len(clusters), 2)  # 两个张三合一，李四独立


if __name__ == "__main__":
    unittest.main()
