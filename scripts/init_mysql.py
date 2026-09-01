from __future__ import annotations

"""一次性初始化本地 MySQL：按 .env 中的 URL 建库并建表。

用法：
    1. 编辑 easy_game/.env，把 MYSQL_URL / STAGEBOUND_DATABASE_URL 里的
       YOUR_MYSQL_PASSWORD 换成 root 用户真实密码。
    2. 运行：python scripts/init_mysql.py

会读取 MYSQL_URL 与 STAGEBOUND_DATABASE_URL 两个连接串；若指向同一数据库则只建一次库。
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")


def _parse_url(name: str) -> tuple[URL, str, str] | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    url = make_url(raw)
    return url, (url.database or ""), raw


def _ensure_database(url: URL, database: str) -> None:
    # SQLAlchemy 2.x 的 ``set(database=None)`` 会保留原库名，这里必须显式置空。
    admin_url = url.set(database="")
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        engine.dispose()


def _create_tables(database_url: str) -> None:
    from db import Database
    from Persistence.Store import GameSaveStore
    from StoryTemplate.TemplateRepository import TemplateRepository

    database = Database(database_url)
    GameSaveStore(database).create_schema()
    TemplateRepository(database).create_all()
    print(f"建表完成：{database_url}")


def main() -> int:
    entries = [
        _parse_url("MYSQL_URL"),
        _parse_url("STAGEBOUND_DATABASE_URL"),
    ]
    entries = [entry for entry in entries if entry is not None]
    if not entries:
        print("未配置 MYSQL_URL / STAGEBOUND_DATABASE_URL，无需初始化。", flush=True)
        return 0

    for url, database, _raw in entries:
        if not database:
            print("连接串缺少数据库名，请检查 .env。", flush=True)
            return 1
        _ensure_database(url, database)
        print(f"数据库已就绪：{database}", flush=True)

    for _url, _database, raw in entries:
        _create_tables(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
