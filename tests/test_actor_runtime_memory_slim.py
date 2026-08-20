from Actor.ActorRuntime import apply_resolved_act
from GameplayTuning import RelationshipTuning


def _base_state(resolved_act):
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["player", "npc", "hero"]},
        "player": {"controlled_character": "player"},
        "characters": {
            "player": {"intent": "", "memory": {}},
            "npc": {"intent": "", "memory": {}},
            "hero": {"intent": "", "memory": {}},
        },
        "history": [],
        "runtime": {
            "turn_index": 5,
            "resolved_act": resolved_act,
            "pending_beat_actors": [],
            "beat_fallback_turns_remaining": 0,
        },
    }


def _act(**over):
    base = {
        "actor": "player", "mode": "speak", "target": "hero", "content": "hi",
        "spoken_text": "hi", "nonverbal_action": "", "next_intent": "",
        "emotion_update": {}, "relationship_update": {"hero": 2.0},
        "revealed_facts": [], "triggered_plot_flags": {},
        "should_end_scene": False, "should_end_chapter": False,
    }
    base.update(over)
    return base


def test_no_long_term_or_short_term_queues_written():
    profiles = {
        "hero": {"agent_type": "L1"},
        "npc": {"agent_type": "actor"},
        "player": {"agent_type": "actor"},
    }
    state = _base_state(_act())
    result = apply_resolved_act(state, RelationshipTuning(), character_profiles=profiles)
    for cid in ("player", "npc", "hero"):
        mem = result["characters"][cid]["memory"]
        assert set(mem.keys()) == {"player_memory"}


def test_player_impression_only_for_l1():
    profiles = {
        "hero": {"agent_type": "L1"},
        "npc": {"agent_type": "actor"},
        "player": {"agent_type": "actor"},
    }
    state = _base_state(_act(actor="player", target="hero"))
    result = apply_resolved_act(state, RelationshipTuning(), character_profiles=profiles)
    assert result["characters"]["hero"]["memory"]["player_memory"]["key_events"]
    assert result["characters"]["npc"]["memory"]["player_memory"]["key_events"] == []
