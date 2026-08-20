from Actor.ActorFormatter import _build_actor_payload
from Memory.context import ActorMemoryContext


def _state(agent_type):
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "g", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "focus_character": "hero"},
        "scene_plan": {"must_happen": [], "character_objectives": {}},
        "director_brief": {"beat_goal": "", "who_should_respond": []},
        "characters": {
            "hero": {"intent": "fight", "memory": {"player_memory": {"overall_impression": "wary", "relation_state": {}, "key_events": []}}},
        },
        "runtime": {"next_act": None},
    }


def _ctx(agent_type):
    return ActorMemoryContext(
        actor_id="hero",
        persona={"agent_type": agent_type, "memory_profile": {}},
        short_term=[{"turn": 1, "content": "hi", "actor": "hero"}],
        retrieved=[],
    )


def test_payload_drops_legacy_memory_keys():
    payload = _build_actor_payload(_state("L1"), _ctx("L1"))
    assert "actor_memory" not in payload
    assert "recent_short_term_memory" not in payload
    assert payload["recent_history"] == [{"turn": 1, "content": "hi", "actor": "hero"}]
    assert payload["recalled_memories"] == []


def test_player_memory_present_for_l1_absent_for_npc():
    l1_payload = _build_actor_payload(_state("L1"), _ctx("L1"))
    assert l1_payload["player_memory"]["overall_impression"] == "wary"
    npc_payload = _build_actor_payload(_state("actor"), _ctx("actor"))
    assert "player_memory" not in npc_payload
