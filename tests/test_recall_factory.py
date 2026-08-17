from __future__ import annotations

import unittest
from typing import Sequence

from db import Database
from db.access import DataAccess


class _FakeEmbedding:
    """假嵌入模型：固定 512 维，避免测试下载 bge / 依赖 torch。"""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(t))] + [0.0] * 511 for t in texts]


class RecallFactoryTests(unittest.TestCase):
    """回忆栈工厂：把基础模块组装成 RecallService + AsyncSceneIndexer。

    关键约束：
    - 回忆库未配置（DataAccess.has_recall() 为 False）时返回 (None, None)，
      让上层优雅跳过、服务器照常启动。
    - embedding 重且可选：默认懒加载 BgeEmbeddingModel，测试可注入 fake，
      不触发模型下载 / torch 依赖。
    """

    def test_未配置回忆库返回空栈(self):
        from Recall.service.factory import build_recall_stack

        access = DataAccess(save_database=Database("sqlite://"))
        service, indexer = build_recall_stack(access)
        self.assertIsNone(service)
        self.assertIsNone(indexer)

    def test_embedding_可选且懒加载_不配置时不加载(self):
        # 未配置回忆库时，连 embedding 工厂都不应被调用（完全可选）。
        from Recall.service import factory

        called = {"n": 0}

        def _boom():
            called["n"] += 1
            raise AssertionError("未配置回忆库时不应实例化 embedding")

        access = DataAccess(save_database=Database("sqlite://"))
        service, indexer = factory.build_recall_stack(access, embedding_factory=_boom)
        self.assertIsNone(service)
        self.assertEqual(called["n"], 0)

    def test_配置回忆库时组装出可用栈(self):
        # 用 sqlite 作 recall 库无法建 pgvector，故此处只验证「配置齐全时会尝试
        # 用注入的 embedding_factory 组装」——通过一个探针工厂断言它被调用。
        from Recall.service import factory
        from Recall.service.recall_service import RecallService
        from Recall.service.async_indexer import AsyncSceneIndexer

        access = DataAccess(
            save_database=Database("sqlite://"),
            recall_url="sqlite://",
        )
        built = {"n": 0}

        def _fake_factory():
            built["n"] += 1
            return _FakeEmbedding()

        # 向量库/稀疏检索按连接串构造，sqlite 下 create_engine 不会立即连库；
        # 只要工厂逻辑跑通且类型正确即可（真正的 pg 交互在集成测试里覆盖）。
        service, indexer = factory.build_recall_stack(
            access,
            embedding_factory=_fake_factory,
            vector_store_factory=lambda url: _FakeVectorStore(),
            sparse_search_factory=lambda url: None,
        )
        self.assertEqual(built["n"], 1)
        self.assertIsInstance(service, RecallService)
        self.assertIsInstance(indexer, AsyncSceneIndexer)


class _FakeVectorStore:
    """假向量库：满足 HybridRetrieval / RecallService 的最小协议。"""

    def upsert(self, rows) -> None:
        return None

    def search(self, query_vector, *, top_k=10, filters=None):
        return []


if __name__ == "__main__":
    unittest.main()
