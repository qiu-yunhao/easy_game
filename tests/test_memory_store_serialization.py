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


from History.GameMemory import empty_memory_state


def test_deserialize_fills_missing_global_memory_keys():
    store = MemoryStore()
    fragment = {"memory": {"last_compressed_turn": 3}, "character_memory": {}}
    result = store.deserialize_memory(fragment)

    base = empty_memory_state()
    assert result["memory"]["last_compressed_turn"] == 3
    # missing keys backfilled from empty_memory_state
    assert result["memory"]["scene_memory"] == base["scene_memory"]
    assert result["memory"]["playwright_memory"] == base["playwright_memory"]
    assert result["character_memory"] == {}


def test_deserialize_drops_stale_subjective_queues_from_old_saves():
    store = MemoryStore()
    fragment = {
        "memory": {},
        "character_memory": {
            "lin": {
                "player_memory": {"overall_impression": "ally"},
                "short_term_memory": [{"summary": "stale"}],
                "long_term_memory": [{"belief_formed": "stale"}],
                "consolidated_memory": [{"x": 1}],
                "pinned_long_term_memory": [{"y": 2}],
            }
        },
    }
    result = store.deserialize_memory(fragment)

    assert result["character_memory"]["lin"] == {"player_memory": {"overall_impression": "ally"}}


def test_deserialize_handles_none_fragment():
    store = MemoryStore()
    result = store.deserialize_memory(None)
    assert result["memory"] == empty_memory_state()
    assert result["character_memory"] == {}


def test_serialize_deserialize_round_trip_is_stable():
    store = MemoryStore()
    fragment = store.serialize_memory(_state_with_memory())
    first = store.deserialize_memory(fragment)
    # re-serializing the normalized character_memory and deserializing again is idempotent
    second = store.deserialize_memory({
        "memory": first["memory"],
        "character_memory": first["character_memory"],
    })
    assert first["character_memory"] == second["character_memory"]
    assert first["character_memory"]["lin"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 1.5},
            "key_events": [{"impression": "helped me"}],
        }
    }
