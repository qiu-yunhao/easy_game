from Memory.store import MemoryStore
from GameplayTuning import RelationshipTuning


def test_record_player_impression_appends_event_and_clamps_relation():
    store = MemoryStore()
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    event = {"turn": 3, "summary": "helped", "impression": "trusting", "relation_delta": 2.0, "tags": ["trust"]}
    result = store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=2.0,
        event=event,
        limit=8,
        tuning=RelationshipTuning(),
    )
    pm = result["player_memory"]
    assert pm["overall_impression"] == "trusting"
    # RelationshipTuning() clamps to maximum_delta=1.0 (matches ActorRuntime._clamp_relationship)
    assert pm["relation_state"]["player"] == 1.0
    assert pm["key_events"] == [event]


def test_record_player_impression_is_pure():
    store = MemoryStore()
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    original = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=1.0,
        event={"turn": 1, "summary": "s", "impression": "observe", "relation_delta": 1.0, "tags": []},
        limit=8,
        tuning=RelationshipTuning(),
    )
    assert memory_state == original  # input untouched


def test_record_player_impression_trims_to_limit():
    store = MemoryStore()
    existing = [{"turn": i} for i in range(8)]
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": existing}}
    event = {"turn": 99, "summary": "", "impression": "observe", "relation_delta": 0.0, "tags": []}
    result = store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=0.0,
        event=event,
        limit=8,
        tuning=RelationshipTuning(),
    )
    assert len(result["player_memory"]["key_events"]) == 8
    assert result["player_memory"]["key_events"][-1] == event
