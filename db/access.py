from __future__ import annotations

from typing import Optional

from db.database import Database

"""数据访问层：统一管理「多库混排」的接入点。

本系统的数据分布在不同后端：存档主库是 MySQL，回忆（RAG）库需要 Postgres
（pgvector/pg_trgm）。为避免各业务模块各自 create_engine、到处硬编码连接串，
把「有哪些库、各自怎么连」收敛到这一层——业务向本层按用途取连接：

- 存档：database()，复用调用方注入的 save Database。
- 回忆：recall_url()/recall_database()，回忆栈从这里获得自己的 pg 连接。

回忆库是可选的：未配置连接串时 has_recall() 为 False，整套回忆栈据此优雅跳过，
服务器仍能仅凭存档库正常启动。
"""


class DataAccess:
    def __init__(
        self,
        *,
        save_database: Database,
        recall_url: str | None = None,
    ) -> None:
        self._save = save_database
        # 空白/None 一律视为未配置，避免 "  " 这类脏值误判为已启用。
        cleaned = (recall_url or "").strip()
        self._recall_url: Optional[str] = cleaned or None
        self._recall_db: Optional[Database] = None  # 懒建，首次取用时才连接。

    def database(self) -> Database:
        """存档主库（始终可用，由调用方注入）。"""
        return self._save

    def has_recall(self) -> bool:
        """是否已配置回忆库（Postgres）。未配置则回忆栈整体跳过。"""
        return self._recall_url is not None

    def recall_url(self) -> Optional[str]:
        """回忆库连接串；未配置返回 None。"""
        return self._recall_url

    def recall_database(self) -> Optional[Database]:
        """回忆库 Database（懒建、复用同一实例）；未配置返回 None。

        注意：pgvector 向量库与 pg_trgm 稀疏检索目前各自持有 engine（按连接串构造），
        本方法提供的是「按需共用的 recall Database」，供确需 ORM 会话的场景（如仍留在
        MySQL 侧的防重日志之外的将来扩展）复用；回忆栈主链路用 recall_url() 即可。
        """
        if self._recall_url is None:
            return None
        if self._recall_db is None:
            self._recall_db = Database(self._recall_url)
        return self._recall_db
