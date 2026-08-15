from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from db import Database, DatabaseConfig
from Persistence.Store import GameSaveStore


class PersistenceInjectionTest(unittest.TestCase):
    def test_可注入_Database_并建表(self):
        db = Database(DatabaseConfig(database_url="sqlite+pysqlite:///:memory:"))
        store = GameSaveStore(db)
        store.create_schema()  # 不应抛异常，且复用注入的 engine
        self.assertIs(store.engine, db.engine)

    def test_向后兼容_仍可传_url(self):
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()
        self.assertIsNotNone(store.engine)


if __name__ == "__main__":
    unittest.main()
