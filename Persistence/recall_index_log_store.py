from __future__ import annotations

from sqlalchemy import select

from db import Database
from Persistence.Models import RecallIndexLog

"""回忆索引防重日志的读写封装。

按 (player_id, scene_id) 记录「已索引」事实，供异步索引器消费前查重、成功后落标。
复用注入的 Database 连接来源（与存档同库），不自建 engine。
"""


class RecallIndexLogStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def is_indexed(self, *, player_id: int, scene_id: str) -> bool:
        """查询某玩家的某一幕是否已索引过。"""
        with self._database.session() as db:
            stmt = select(RecallIndexLog.id).where(
                RecallIndexLog.player_id == player_id,
                RecallIndexLog.scene_id == scene_id,
            )
            return db.execute(stmt).first() is not None

    def mark_indexed(self, *, player_id: int, scene_id: str) -> None:
        """把某玩家的某一幕标记为已索引；重复标记时吞掉唯一键冲突（幂等）。"""
        with self._database.session() as db:
            exists = db.execute(
                select(RecallIndexLog.id).where(
                    RecallIndexLog.player_id == player_id,
                    RecallIndexLog.scene_id == scene_id,
                )
            ).first()
            if exists is not None:
                return
            db.add(RecallIndexLog(player_id=player_id, scene_id=scene_id))
            db.commit()
