from Memory.store import MemoryStore
from Persistence.store_snapshot import build_world_state_payload
from Persistence.Store import normalize_loaded_state


def _snapshot_with_old_save():
    return {
        "state": {
            "plot": {"scene_id": "s1"},
            "scene": {"on_stage": ["lin"]},
            "runtime": {"turn_index": 5},
            "scene_plan": {},
            "director_brief": {},
            "history": [{"turn": 5, "actor": "lin"}],
            "player": {"controlled_character": "player"},
            "memory": {"last_compressed_turn": 4},
            "characters": {
                "lin": {
                    "id": "lin",
                    "emotion": "wary",
                    "intent": "test",
                    "memory": {
                        "player_memory": {
                            "overall_impression": "ally",
                            "relation_state": {"player": 2.0},
                            "key_events": [{"impression": "saved me"}],
                        },
                        "short_term_memory": [{"summary": "STALE"}],
                        "long_term_memory": [{"belief_formed": "STALE"}],
                        "consolidated_memory": [{"x": 1}],
                        "pinned_long_term_memory": [{"y": 2}],
                    },
                }
            },
        }
    }


def test_world_state_payload_then_load_preserves_player_impression_and_drops_queues():
    snapshot = _snapshot_with_old_save()

    # save side: world_state payload
    world_state = build_world_state_payload(snapshot)
    lin_saved = world_state["characters"]["lin"]
    assert lin_saved["emotion"] == "wary"
    assert lin_saved["intent"] == "test"
    assert lin_saved["memory"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 2.0},
            "key_events": [{"impression": "saved me"}],
        }
    }

    # load side: normalize the raw game_state_json (which still has stale queues)
    loaded = normalize_loaded_state(snapshot["state"])
    lin_loaded = loaded["characters"]["lin"]
    assert lin_loaded["emotion"] == "wary"
    assert lin_loaded["memory"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 2.0},
            "key_events": [{"impression": "saved me"}],
        }
    }
    # non-memory state fully preserved
    assert loaded["plot"] == {"scene_id": "s1"}
    assert loaded["history"] == [{"turn": 5, "actor": "lin"}]
    # global memory backfilled to canonical shape
    assert "scene_memory" in loaded["memory"]
    assert loaded["memory"]["last_compressed_turn"] == 4


def test_original_state_not_mutated_by_save_or_load():
    snapshot = _snapshot_with_old_save()
    build_world_state_payload(snapshot)
    normalize_loaded_state(snapshot["state"])
    # source still carries the stale queues (pure functions did not mutate)
    assert snapshot["state"]["characters"]["lin"]["memory"]["short_term_memory"] == [{"summary": "STALE"}]
