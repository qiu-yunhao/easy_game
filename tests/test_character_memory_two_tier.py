from CharacterMemory import (
    empty_character_memory_state,
    ensure_character_memory_state,
    memory_config_for_agent_type,
)


def test_state_holds_only_player_memory():
    state = empty_character_memory_state()
    assert set(state.keys()) == {"player_memory"}
    assert state["player_memory"] == {
        "overall_impression": "",
        "relation_state": {},
        "key_events": [],
    }


def test_two_tiers_only_l1_and_actor():
    l1 = memory_config_for_agent_type("L1")
    npc = memory_config_for_agent_type("actor")
    assert memory_config_for_agent_type("L2") == npc
    assert l1["player_memory_limit"] == 8
    assert npc["player_memory_limit"] == 3
    assert set(l1.keys()) == {"player_memory_limit", "player_memory_depth"}


def test_ensure_state_drops_legacy_queues():
    legacy = {
        "long_term_memory": [{"event_summary": "x", "turn_recorded": 1}],
        "short_term_memory": [{"turn": 1, "summary": "y"}],
        "consolidated_memory": [{"turn_start": 0, "turn_end": 1, "event_summary": "z"}],
        "pinned_long_term_memory": [{"event_summary": "p", "turn_recorded": 2}],
        "player_memory": {"overall_impression": "wary", "relation_state": {"player": 1.0}, "key_events": []},
    }
    result = ensure_character_memory_state(legacy, actor_profile={"agent_type": "L1"})
    assert set(result.keys()) == {"player_memory"}
    assert result["player_memory"]["overall_impression"] == "wary"
    assert result["player_memory"]["relation_state"] == {"player": 1.0}
