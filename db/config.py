from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DatabaseConfig:
    """数据库连接配置，从业务类抽出的通用参数。"""

    database_url: str
    echo: bool = False
    pool_size: int | None = None
    max_overflow: int | None = None
