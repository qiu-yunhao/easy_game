from __future__ import annotations

import unittest

from web_session import WebGameSession


class FakeIndexer:
    """记录 enqueue 调用，供断言 web_session 是否在幕结束时投递了索引任务。"""

    def __init__(self):
        self.calls: list[tuple[dict, int, int]] = []

    def enqueue(self, scene, *, user_id, player_id):
        self.calls.append((scene, user_id, player_id))


def _finished_state():
    """构造一份「当前幕刚结束」的最小 state，含可提取的幕数据。"""
    return {
        "runtime": {"scene_finished": True},
        "plot": {"scene_id": "c1-scene-1", "chapter_id": "c1"},
        "memory": {
            "scene_memory": {
                "turn_range": "10-12",
                "summary": "主角初入宗门。",
                "key_events": ["拜师"],
            }
        },
        "history": [
            {"turn": 10, "actor": "hero", "content": "我到了。"},
            {"turn": 12, "actor": "hero", "content": "拜见师父。"},
        ],
    }


def _bare_session(*, state, user_id, player_id, indexer):
    """绕过重依赖初始化，只装配触发方法所需的最小属性。"""
    session = WebGameSession.__new__(WebGameSession)
    session.state = state
    session.active_user_id = user_id
    session.active_player_id = player_id
    session._scene_indexer = indexer
    return session


class SceneFinishTriggerTests(unittest.TestCase):
    def test_enqueues_when_scene_finished(self):
        indexer = FakeIndexer()
        session = _bare_session(
            state=_finished_state(), user_id=7, player_id=3, indexer=indexer
        )
        session._maybe_index_finished_scene_unlocked()
        self.assertEqual(len(indexer.calls), 1)
        scene, user_id, player_id = indexer.calls[0]
        self.assertEqual((user_id, player_id), (7, 3))
        self.assertEqual(scene["scene_id"], "c1-scene-1")

    def test_skips_when_indexer_unbound(self):
        session = _bare_session(
            state=_finished_state(), user_id=7, player_id=3, indexer=None
        )
        # 未注入索引器时静默跳过，不应抛错。
        session._maybe_index_finished_scene_unlocked()

    def test_skips_when_scene_not_finished(self):
        indexer = FakeIndexer()
        state = _finished_state()
        state["runtime"]["scene_finished"] = False
        session = _bare_session(state=state, user_id=7, player_id=3, indexer=indexer)
        session._maybe_index_finished_scene_unlocked()
        self.assertEqual(indexer.calls, [])

    def test_skips_when_no_save_context(self):
        indexer = FakeIndexer()
        session = _bare_session(
            state=_finished_state(), user_id=None, player_id=None, indexer=indexer
        )
        # 无存档上下文（user/player 缺失）时无法定位多租户前缀，静默跳过。
        session._maybe_index_finished_scene_unlocked()
        self.assertEqual(indexer.calls, [])

    def test_skips_when_scene_unextractable(self):
        indexer = FakeIndexer()
        state = _finished_state()
        state["plot"]["scene_id"] = ""  # 无 scene_id → 无法提取
        session = _bare_session(state=state, user_id=7, player_id=3, indexer=indexer)
        session._maybe_index_finished_scene_unlocked()
        self.assertEqual(indexer.calls, [])

    def test_bind_recall_indexer_sets_attribute(self):
        indexer = FakeIndexer()
        session = WebGameSession.__new__(WebGameSession)
        session._lock = __import__("threading").Lock()
        session.bind_recall_indexer(indexer)
        self.assertIs(session._scene_indexer, indexer)


if __name__ == "__main__":
    unittest.main()
