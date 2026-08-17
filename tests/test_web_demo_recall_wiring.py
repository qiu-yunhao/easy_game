from __future__ import annotations

import unittest
from unittest import mock

import web_demo


class _FakeSession:
    """假会话：只记录 bind 调用，不触发真实引擎逻辑。"""

    def __init__(self) -> None:
        self.service = "unset"
        self.indexer = "unset"

    def bind_recall_service(self, service) -> None:
        self.service = service

    def bind_recall_indexer(self, indexer) -> None:
        self.indexer = indexer


class _FakeIndexer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class SetupRecallTests(unittest.TestCase):
    """web_demo._setup_recall 接线：按需组装并绑定回忆栈到会话。"""

    def test_未配置回忆库返回_None_不绑定(self):
        session = _FakeSession()
        # recall_url 为空 → DataAccess.has_recall() False → 直接返回 None。
        result = web_demo._setup_recall(
            session, save_database=object(), recall_url="   "
        )
        self.assertIsNone(result)
        self.assertEqual(session.service, "unset")
        self.assertEqual(session.indexer, "unset")

    def test_配置齐全则组装绑定并启动索引器(self):
        session = _FakeSession()
        fake_service = object()
        fake_indexer = _FakeIndexer()
        # 桩掉 build_recall_stack，避免真连 pg / 加载 bge。
        with mock.patch(
            "Recall.service.build_recall_stack",
            return_value=(fake_service, fake_indexer),
        ):
            result = web_demo._setup_recall(
                session, save_database=object(), recall_url="postgresql://x"
            )
        self.assertIs(result, fake_indexer)
        self.assertIs(session.service, fake_service)
        self.assertIs(session.indexer, fake_indexer)
        self.assertTrue(fake_indexer.started)

    def test_栈组装返回空则不绑定(self):
        session = _FakeSession()
        with mock.patch(
            "Recall.service.build_recall_stack", return_value=(None, None)
        ):
            result = web_demo._setup_recall(
                session, save_database=object(), recall_url="postgresql://x"
            )
        self.assertIsNone(result)
        self.assertEqual(session.service, "unset")


if __name__ == "__main__":
    unittest.main()
