from Persistence.Store import normalize_loaded_state


def test_normalize_loaded_state_drops_stale_character_queues():
    state = {
        "memory": {"last_compressed_turn": 2},
        "characters": {
            "lin": {
                "id": "lin",
                "emotion": "calm",
                "memory": {
                    "player_memory": {"overall_impression": "ally"},
                    "long_term_memory": [{"belief_formed": "stale"}],
                },
            }
        },
        "history": [{"turn": 1}],
    }
    result = normalize_loaded_state(state)

    assert result["characters"]["lin"]["emotion"] == "calm"
    assert result["characters"]["lin"]["memory"] == {"player_memory": {"overall_impression": "ally"}}
    assert "scene_memory" in result["memory"]
    # non-memory state untouched
    assert result["history"] == [{"turn": 1}]


def test_normalize_loaded_state_handles_missing_memory():
    state = {"characters": {}, "history": []}
    result = normalize_loaded_state(state)
    assert "scene_memory" in result["memory"]
    assert result["characters"] == {}
