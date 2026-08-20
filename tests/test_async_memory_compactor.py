from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


def _snapshot(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "time_tag": "", "beat": "", "tension": "", "focus_character": ""},
        "runtime": {"turn_index": n, "last_actor": "", "last_mode": ""},
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def _store(trigger=30):
    return MemoryStore(history_manager=HistoryManager(compression_trigger_size=trigger))


def test_enqueue_join_produces_pending_result():
    compactor = AsyncMemoryCompactor(memory_store=_store())
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        result = compactor.take_pending()
        assert result is not None
        blocks, new_last = result
        assert blocks and new_last == 5
        assert compactor.take_pending() is None
    finally:
        compactor.stop()


def test_failure_leaves_no_pending(monkeypatch):
    store = _store()

    def boom(_state):
        raise RuntimeError("compaction failed")

    monkeypatch.setattr(store, "compact", boom)
    compactor = AsyncMemoryCompactor(memory_store=store)
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        assert compactor.take_pending() is None
    finally:
        compactor.stop()


def test_snapshot_isolation_does_not_touch_source():
    compactor = AsyncMemoryCompactor(memory_store=_store())
    compactor.start()
    try:
        snap = _snapshot(5)
        compactor.enqueue(snap)
        compactor.join()
        compactor.take_pending()
        assert snap["memory"]["last_compressed_turn"] == 0
    finally:
        compactor.stop()
