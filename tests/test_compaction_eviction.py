from History.HistoryManager import HistoryManager


def test_evict_removes_only_compressed_turns():
    history = [{"turn": t, "content": f"l{t}"} for t in range(1, 11)]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=5)
    assert [item["turn"] for item in kept] == [6, 7, 8, 9, 10]


def test_evict_noop_when_cursor_zero():
    history = [{"turn": t} for t in range(1, 4)]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=0)
    assert [item["turn"] for item in kept] == [1, 2, 3]


def test_evict_keeps_block_internal_raw_items_untouched():
    history = [{"turn": 1, "content": "a"}, {"turn": 2, "content": "b"}]
    blocks = [{"turn_start": 1, "turn_end": 2, "raw_items": list(history)}]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=2)
    assert kept == []
    assert blocks[0]["raw_items"] == [{"turn": 1, "content": "a"}, {"turn": 2, "content": "b"}]
