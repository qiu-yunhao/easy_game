from Memory.store import MemoryStore
from History.HistoryManager import HistoryManager


def _state(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {
            "chapter_id": "c1",
            "scene_id": "s1",
            "chapter_goal": "goal",
            "plot_flags": {},
        },
        "scene": {
            "location_id": "loc",
            "on_stage": ["hero"],
            "time_tag": "day",
            "beat": "b1",
            "tension": 0.0,
            "focus_character": None,
        },
        "runtime": {
            "turn_index": n,
            "last_actor": "hero",
            "last_mode": "speak",
        },
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_store_compact_delegates_to_history_manager():
    store = MemoryStore(history_manager=HistoryManager(compression_trigger_size=30, summary_horizon_turns=45))
    state = _state(5)
    blocks, new_last = store.compact(state)
    assert blocks
    assert new_last == 5
    assert state["memory"]["scene_memory"]["compressed_blocks"] == []


def test_store_derive_views_from_existing_blocks():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    store = MemoryStore(history_manager=mgr)
    state = _state(5)
    blocks, _ = store.compact(state)
    views = store.derive_views(state, blocks)
    assert set(views.keys()) == {
        "last_compressed_turn", "scene_memory", "playwright_memory",
        "director_memory", "scheduler_memory",
    }
