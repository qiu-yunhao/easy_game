from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


def _state(n, last_compressed=0, blocks=None):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "time_tag": "", "beat": "", "tension": "", "focus_character": ""},
        "runtime": {"turn_index": n, "scene_finished": False, "last_actor": "hero", "last_mode": "speak"},
        "history": history,
        "memory": {"last_compressed_turn": last_compressed, "scene_memory": {"compressed_blocks": blocks or []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_enqueue_then_join_merges_and_reports_cursor():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    store = MemoryStore(history_manager=mgr)
    compactor = AsyncMemoryCompactor(memory_store=store)
    compactor.start()
    try:
        compactor.enqueue(_state(35))  # >= threshold worth of history
        compactor.join()
        blocks, new_last = compactor.take_pending()
        assert new_last > 0
        evicted = mgr.evict_compressed_history(_state(35)["history"], new_last)
        assert all(item["turn"] > new_last for item in evicted)
    finally:
        compactor.stop()
