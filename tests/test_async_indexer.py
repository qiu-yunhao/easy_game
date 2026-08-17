from __future__ import annotations

import threading
import unittest

from db import Database
from Persistence.Models import Base
from Persistence.recall_index_log_store import RecallIndexLogStore
from Recall.service.async_indexer import AsyncSceneIndexer


def _memory_db() -> Database:
    # SQLite 内存库需 StaticPool + check_same_thread=False，才能跨线程共享同一连接。
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    db = Database.__new__(Database)
    db.engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._session_factory = sessionmaker(db.engine, expire_on_commit=False, future=True)
    db.create_all(Base.metadata)
    return db


class RecallIndexLogStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = RecallIndexLogStore(_memory_db())

    def test_unindexed_scene_reports_false(self):
        self.assertFalse(self.store.is_indexed(player_id=3, scene_id="c1-scene-1"))

    def test_mark_then_is_indexed(self):
        self.store.mark_indexed(player_id=3, scene_id="c1-scene-1")
        self.assertTrue(self.store.is_indexed(player_id=3, scene_id="c1-scene-1"))

    def test_mark_is_idempotent(self):
        self.store.mark_indexed(player_id=3, scene_id="c1-scene-1")
        # 同一 (player, scene) 重复标记不应抛错（唯一键冲突需吞掉）。
        self.store.mark_indexed(player_id=3, scene_id="c1-scene-1")
        self.assertTrue(self.store.is_indexed(player_id=3, scene_id="c1-scene-1"))

    def test_scoped_by_player(self):
        self.store.mark_indexed(player_id=3, scene_id="c1-scene-1")
        # 不同玩家同名 scene 互不影响。
        self.assertFalse(self.store.is_indexed(player_id=5, scene_id="c1-scene-1"))


class FakeRecallService:
    """记录被索引的幕，供断言后台确实调用了索引。"""

    def __init__(self):
        self.indexed: list[tuple[int, int, str]] = []
        self.lock = threading.Lock()

    def index_completed_scenes(self, scenes, *, user_id, player_id, chunk_size=4):
        with self.lock:
            for scene in scenes:
                self.indexed.append((user_id, player_id, scene["scene_id"]))


def _scene(scene_id="c1-scene-1"):
    return {
        "history": [{"turn": 10, "actor": "hero", "content": "x"}],
        "scene_memory": {"turn_range": "10-10", "summary": "s", "key_events": []},
        "scene_id": scene_id,
        "chapter_id": "c1",
    }


class AsyncSceneIndexerTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeRecallService()
        self.log = RecallIndexLogStore(_memory_db())
        self.indexer = AsyncSceneIndexer(recall_service=self.service, index_log=self.log)
        self.indexer.start()

    def tearDown(self):
        self.indexer.stop()

    def test_enqueue_triggers_background_index(self):
        self.indexer.enqueue(_scene(), user_id=7, player_id=3)
        self.indexer.join()
        self.assertEqual(len(self.service.indexed), 1)
        self.assertEqual(self.service.indexed[0], (7, 3, "c1-scene-1"))

    def test_indexed_scene_is_logged(self):
        self.indexer.enqueue(_scene(), user_id=7, player_id=3)
        self.indexer.join()
        self.assertTrue(self.log.is_indexed(player_id=3, scene_id="c1-scene-1"))

    def test_duplicate_scene_indexed_only_once(self):
        self.indexer.enqueue(_scene(), user_id=7, player_id=3)
        self.indexer.join()
        self.assertEqual(len(self.service.indexed), 1)
        # 同一幕再次入队（如流式路径+工具路径都命中）应被防重日志挡下。
        self.indexer.enqueue(_scene(), user_id=7, player_id=3)
        self.indexer.join()
        self.assertEqual(len(self.service.indexed), 1)

    def test_index_failure_does_not_mark_log(self):
        def boom(scenes, *, user_id, player_id, chunk_size=4):
            raise RuntimeError("embed 挂了")

        self.service.index_completed_scenes = boom
        self.indexer.enqueue(_scene("c1-scene-2"), user_id=7, player_id=3)
        self.indexer.join()
        # 索引失败不写日志，保证下次能重试。
        self.assertFalse(self.log.is_indexed(player_id=3, scene_id="c1-scene-2"))


if __name__ == "__main__":
    unittest.main()
