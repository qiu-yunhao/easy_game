from History.MemoryRefreshPolicy import run_async_refresh
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


def _state(n, last_compressed=0, blocks=None):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "time_tag": "", "beat": "", "tension": 0.0, "focus_character": ""},
        "runtime": {"turn_index": n, "scene_finished": False, "last_actor": "hero", "last_mode": "speak"},
        "history": history,
        "memory": {"last_compressed_turn": last_compressed, "scene_memory": {"compressed_blocks": blocks or []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


class _FakeCompactor:
    def __init__(self, pending=None):
        self._pending = pending
        self.enqueued = []
    def take_pending(self):
        p, self._pending = self._pending, None
        return p
    def enqueue(self, state):
        self.enqueued.append(state)


def test_degrades_without_store_or_compactor():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    st = _state(3)
    # store=None 或 compactor=None → 原样返回
    assert run_async_refresh(st, manager=mgr, store=None, compactor=_FakeCompactor()) is st
    assert run_async_refresh(st, manager=mgr, store=MemoryStore(history_manager=mgr), compactor=None) is st


def test_joins_pending_merges_evicts_and_derives_views():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    store = MemoryStore(history_manager=mgr)
    # 先真实压出一批 blocks 当作"上一轮后台结果"
    src = _state(5)
    blocks, new_last = store.compact(src)
    assert blocks and new_last == 5
    compactor = _FakeCompactor(pending=(blocks, new_last))
    # 当前轮 history 有到 turn 8(5 已压缩)
    st = _state(8)
    out = run_async_refresh(st, manager=mgr, store=store, compactor=compactor)
    # 游标推进到 5,history 驱逐掉 turn<=5,只剩 6,7,8
    assert out["memory"]["last_compressed_turn"] == 5
    assert [h["turn"] for h in out["history"]] == [6, 7, 8]
    # 视图已同步派生(键齐全)
    assert set(out["memory"].keys()) >= {"scene_memory", "playwright_memory", "director_memory", "scheduler_memory", "last_compressed_turn"}
    # compressed_blocks 已合并进来
    assert out["memory"]["scene_memory"]["compressed_blocks"] == blocks
