from __future__ import annotations

import unittest

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

from db import Database, DatabaseConfig

Base = declarative_base()


class _Row(Base):
    __tablename__ = "db_foundation_probe"
    id = Column(Integer, primary_key=True)
    name = Column(String(32))


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        # 用内存 SQLite 验证通用封装本身，不依赖具体后端。
        self.db = Database(DatabaseConfig(database_url="sqlite+pysqlite:///:memory:"))

    def test_create_all_建表后可读写(self):
        self.db.create_all(Base.metadata)
        with self.db.session() as s:
            s.add(_Row(id=1, name="张三"))
            s.commit()
        with self.db.session() as s:
            row = s.get(_Row, 1)
            self.assertEqual(row.name, "张三")

    def test_session_异常时回滚(self):
        self.db.create_all(Base.metadata)
        with self.assertRaises(ValueError):
            with self.db.session() as s:
                s.add(_Row(id=2, name="李四"))
                raise ValueError("boom")
        with self.db.session() as s:
            self.assertIsNone(s.get(_Row, 2))


if __name__ == "__main__":
    unittest.main()
