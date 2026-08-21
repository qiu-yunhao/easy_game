from datatypes import VectorDoc, ScoredDoc
from Memory.default_provider import DefaultActorMemoryProvider


class _StubRecall:
    def __init__(self):
        self.calls = []

    def recall_memory_blocks(self, query, *, user_id, player_id, actor_id, window_start, top_k=5):
        self.calls.append({"actor_id": actor_id, "window_start": window_start})
        return [ScoredDoc(doc=VectorDoc(doc_id="d1", doc_type="memory_block", text="old", metadata={}), score=1.0)]


def _state(turn_index=100):
    return {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": {"intent": "explore", "memory": {"player_memory": {}}}},
        "history": [{"turn": 99, "actor": "hero", "content": "recent", "on_stage": ["hero"], "location_id": "loc"}],
        "runtime": {"turn_index": turn_index},
    }


def test_l1_gets_recall_with_correct_window_start():
    recall = _StubRecall()
    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recent_rounds=3,
        recall_service=recall,
        user_id=1,
        player_id=1,
        summary_horizon_turns=45,
    )
    ctx = provider.build("hero", _state(turn_index=100))
    assert ctx.retrieved
    assert recall.calls[0]["actor_id"] == "hero"
    assert recall.calls[0]["window_start"] == max(0, 100 - 45 + 1)  # == 56


def test_npc_gets_no_recall():
    recall = _StubRecall()
    provider = DefaultActorMemoryProvider(
        character_profiles={"npc": {"agent_type": "actor", "memory_profile": {}}},
        recent_rounds=3,
        recall_service=recall,
        user_id=1,
        player_id=1,
        summary_horizon_turns=45,
    )
    state = {
        "scene": {"location_id": "loc", "on_stage": ["npc"]},
        "characters": {"npc": {"intent": "", "memory": {"player_memory": {}}}},
        "history": [{"turn": 1, "actor": "npc", "content": "x", "on_stage": ["npc"], "location_id": "loc"}],
        "runtime": {"turn_index": 100},
    }
    ctx = provider.build("npc", state)
    assert ctx.retrieved == []
    assert recall.calls == []
