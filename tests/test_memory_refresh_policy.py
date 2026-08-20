from History.MemoryRefreshPolicy import decide_refresh


def _state(*, turn_index, last_compressed_turn, history_turns, scene_finished=False, has_blocks=False):
    return {
        "runtime": {"turn_index": turn_index, "scene_finished": scene_finished},
        "memory": {
            "last_compressed_turn": last_compressed_turn,
            "scene_memory": {"compressed_blocks": ([{"turn_end": 1}] if has_blocks else [])},
        },
        "history": [{"turn": t} for t in history_turns],
    }


def test_opening_no_compress():
    d = decide_refresh(_state(turn_index=0, last_compressed_turn=-1, history_turns=[], has_blocks=False), trigger_size=30)
    assert d.should_compress is False
    assert d.compress_all is False


def test_below_threshold_no_compress():
    hist = list(range(1, 11))  # 10 uncompressed
    d = decide_refresh(_state(turn_index=10, last_compressed_turn=0, history_turns=hist, has_blocks=True), trigger_size=30)
    assert d.should_compress is False


def test_at_threshold_compresses():
    hist = list(range(1, 31))  # 30 uncompressed
    d = decide_refresh(_state(turn_index=30, last_compressed_turn=0, history_turns=hist, has_blocks=True), trigger_size=30)
    assert d.should_compress is True
    assert d.compress_all is False


def test_scene_finished_flushes_all():
    hist = list(range(1, 6))  # 5 uncompressed, below threshold
    d = decide_refresh(_state(turn_index=5, last_compressed_turn=0, history_turns=hist, scene_finished=True, has_blocks=True), trigger_size=30)
    assert d.should_compress is True
    assert d.compress_all is True
