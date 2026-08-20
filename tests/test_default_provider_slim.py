from Memory.default_provider import DefaultActorMemoryProvider


def _state():
    return {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": {"intent": "explore", "memory": {"player_memory": {}}}},
        "history": [
            {"turn": 1, "actor": "hero", "content": "line", "on_stage": ["hero"], "location_id": "loc"},
        ],
    }


def test_build_returns_short_term_persona_retrieved_no_long_term():
    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recent_rounds=3,
    )
    ctx = provider.build("hero", _state())
    assert ctx.actor_id == "hero"
    assert ctx.short_term  # presence-filtered history
    assert ctx.retrieved == []  # no recall service wired
    assert not hasattr(ctx, "long_term")
