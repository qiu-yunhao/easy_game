from __future__ import annotations

from Director.DirectorFormatter import _group_actor_ids_by_tier


def test_l2_folds_into_actor_tier() -> None:
    profiles = {
        "hero": {"agent_type": "L1"},
        "old_l2": {"agent_type": "L2"},
        "npc": {"agent_type": "actor"},
    }
    grouped = _group_actor_ids_by_tier(["hero", "old_l2", "npc"], profiles)

    # L2 is no longer a distinct tier bucket.
    assert "L2" not in grouped
    # L1 stays separate.
    assert grouped["L1"] == ["hero"]
    # Former L2 profiles fold into the actor/NPC bucket alongside plain actors.
    assert set(grouped["actor"]) == {"old_l2", "npc"}
