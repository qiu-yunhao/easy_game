from __future__ import annotations

import unittest

from eval_rag.dataset import (
    EVAL_PLAYER_ID, EVAL_USER_ID, EvalSample, EvalScene,
    build_samples, build_scenes, gold_doc_id,
)


class DatasetContractTests(unittest.TestCase):
    def test_gold_doc_id_对齐_scene_indexer_格式(self):
        self.assertEqual(
            gold_doc_id("scene_inn_01", 2),
            f"u{EVAL_USER_ID}:p{EVAL_PLAYER_ID}:scene_inn_01:act_chunk:2",
        )

    def test_场景语料非空且字段齐全(self):
        scenes = build_scenes()
        self.assertGreaterEqual(len(scenes), 8)
        for s in scenes:
            self.assertTrue(s.scene_id and s.chapter_id)
            self.assertGreaterEqual(len(s.history), 4)  # 至少切出 1 块
            self.assertIn("summary", s.scene_memory)

    def test_样本约_50_条且_gold_引用真实存在的_chunk(self):
        scenes = {s.scene_id: s for s in build_scenes()}
        samples = build_samples()
        self.assertGreaterEqual(len(samples), 48)
        self.assertLessEqual(len(samples), 55)
        for smp in samples:
            self.assertTrue(smp.question and smp.gold_answer)
            self.assertTrue(smp.gold_doc_ids)
            scene = scenes[smp.scene_id]
            max_chunk = (len(scene.history) - 1) // 4
            for did in smp.gold_doc_ids:
                idx = int(did.rsplit(":", 1)[1])  # gold 引用的 act_chunk index 不得越界
                self.assertLessEqual(idx, max_chunk)


if __name__ == "__main__":
    unittest.main()
