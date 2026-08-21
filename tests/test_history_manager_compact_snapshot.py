from History.HistoryManager import HistoryManager


def _state_with_uncompressed(n):
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
        "memory": {
            "last_compressed_turn": 0,
            "scene_memory": {"compressed_blocks": []},
        },
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_compact_snapshot_produces_blocks_and_cursor():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    state = _state_with_uncompressed(5)
    new_blocks, new_last = mgr.compact_snapshot(state)
    assert new_blocks  # at least one block
    assert new_last == 5  # turn_end of the last compressed item
    # snapshot compaction must NOT mutate the input state
    assert state["memory"]["scene_memory"]["compressed_blocks"] == []
    assert state["memory"]["last_compressed_turn"] == 0
