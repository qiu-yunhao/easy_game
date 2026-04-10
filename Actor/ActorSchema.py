from __future__ import annotations

from ResolvedActSchema import build_resolved_act_response_schema


ACTOR_TURN_RESPONSE_SCHEMA = build_resolved_act_response_schema(
    "actor_turn",
    include_actor=True,
    include_content=True,
)
