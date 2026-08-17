from __future__ import annotations

import unittest

from db import Database
from db.access import DataAccess


class DataAccessTests(unittest.TestCase):
    """数据访问层：统一管理「多库混排」——存档走 MySQL、回忆走 Postgres。

    业务模块不再各自 create_engine / 硬编码 URL，而是向本层按用途取连接：
    存档主库通过 database() 复用，回忆库通过 recall_url()/recall_database() 取。
    回忆库为可选，未配置时对外表现为「不可用」，让整套回忆栈优雅跳过。
    """

    def test_未配置回忆库时不可用(self):
        access = DataAccess(save_database=Database("sqlite://"))
        self.assertFalse(access.has_recall())
        self.assertIsNone(access.recall_url())
        self.assertIsNone(access.recall_database())

    def test_存档库始终可取(self):
        save = Database("sqlite://")
        access = DataAccess(save_database=save)
        self.assertIs(access.database(), save)

    def test_配置回忆库后可取连接串与_Database(self):
        access = DataAccess(
            save_database=Database("sqlite://"),
            recall_url="sqlite://",
        )
        self.assertTrue(access.has_recall())
        self.assertEqual(access.recall_url(), "sqlite://")
        recall_db = access.recall_database()
        self.assertIsInstance(recall_db, Database)

    def test_回忆_Database_懒建且复用同一实例(self):
        access = DataAccess(
            save_database=Database("sqlite://"),
            recall_url="sqlite://",
        )
        first = access.recall_database()
        second = access.recall_database()
        self.assertIs(first, second)  # 复用，不重复 create_engine

    def test_空白回忆_URL_视为未配置(self):
        access = DataAccess(
            save_database=Database("sqlite://"),
            recall_url="   ",
        )
        self.assertFalse(access.has_recall())
        self.assertIsNone(access.recall_url())


if __name__ == "__main__":
    unittest.main()
