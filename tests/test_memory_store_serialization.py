from Memory.store import MemoryStore


def _state_with_memory():
    return {
        "memory": {
            "last_compressed_turn": 7,
            "scene_memory": {"summary": "s", "key_events": [], "compressed_blocks": []},
            "playwright_memory": {"beats": []},
            "director_memory": {"notes": []},
            "scheduler_memory": {"pressure": []},
        },
        "characters": {
            "lin": {
                "id": "lin",
                "emotion": "calm",
                "memory": {
                    "player_memory": {
                        "overall_impression": "ally",
                        "relation_state": {"player": 1.5},
                        "key_events": [{"impression": "helped me"}],
                    },
                    "short_term_memory": [{"summary": "old queue"}],
                    "long_term_memory": [{"belief_formed": "stale"}],
                },
            },
            "npc": {"id": "npc", "emotion": "neutral"},
        },
    }


def test_serialize_extracts_global_memory_and_per_character_player_memory():
    store = MemoryStore()
    fragment = store.serialize_memory(_state_with_memory())

    assert fragment["memory"]["last_compressed_turn"] == 7
    assert fragment["memory"]["scene_memory"]["summary"] == "s"
    # per-character memory keeps ONLY player_memory
    assert fragment["character_memory"]["lin"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 1.5},
            "key_events": [{"impression": "helped me"}],
        }
    }
    # character with no memory sub-dict produces no entry
    assert "npc" not in fragment["character_memory"]


def test_serialize_is_pure_no_mutation():
    store = MemoryStore()
    state = _state_with_memory()
    store.serialize_memory(state)
    # subjective queue still present in the source state (not stripped in place)
    assert state["characters"]["lin"]["memory"]["short_term_memory"] == [{"summary": "old queue"}]
