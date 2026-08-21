from Persistence.store_snapshot import _resolve_story_layer


def test_player_layer_preserved():
    assert _resolve_story_layer({"story_layer": "player"}) == "player"


def test_l1_layer_preserved():
    assert _resolve_story_layer({"story_layer": "L1"}) == "L1"


def test_actor_is_default():
    assert _resolve_story_layer({"story_layer": ""}) == "actor"
    assert _resolve_story_layer({}) == "actor"


def test_stale_l2_story_layer_collapses_to_actor():
    # old saves may still carry story_layer="L2"; two-tier model has no L2
    assert _resolve_story_layer({"story_layer": "L2"}) == "actor"


def test_stale_l2_agent_type_collapses_to_actor():
    assert _resolve_story_layer({"agent_type": "L2"}) == "actor"


def test_l1_agent_type_resolves_to_l1():
    assert _resolve_story_layer({"agent_type": "L1"}) == "L1"


def test_l1_profile_classified_as_story_character():
    # profiles resolving to L1 are story characters; actor/player are not
    assert _resolve_story_layer({"story_layer": "L1"}) == "L1"
    assert _resolve_story_layer({"story_layer": "actor"}) != "L1"
    assert _resolve_story_layer({"story_layer": "player"}) != "L1"
