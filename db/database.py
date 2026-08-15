from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.config import DatabaseConfig

"""SQLAlchemy engine/session 的通用封装。

只做连接与会话管理，不含任何业务表逻辑——存档表、角色表等仍留在 Persistence。
业务模块通过注入 Database 复用同一连接来源，不再各自 create_engine。
"""


class Database:
    def __init__(self, config: DatabaseConfig | str) -> None:
        self.config = (
            DatabaseConfig(database_url=config) if isinstance(config, str) else config
        )
        kwargs: dict[str, object] = {"echo": self.config.echo, "future": True}
        # 池参数按需透传；SQLite 内存库不接受池参数，故仅在显式配置时传入。
        if self.config.pool_size is not None:
            kwargs["pool_size"] = self.config.pool_size
        if self.config.max_overflow is not None:
            kwargs["max_overflow"] = self.config.max_overflow
        self.engine: Engine = create_engine(self.config.database_url, **kwargs)
        self._session_factory = sessionmaker(
            self.engine, expire_on_commit=False, future=True
        )

    def create_all(self, metadata) -> None:
        """按传入的 MetaData 建表；建哪些表由调用方（业务模块）决定。"""
        metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """会话上下文：正常退出不自动提交（由调用方 commit），异常回滚，末尾关闭。"""
        session = self._session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
