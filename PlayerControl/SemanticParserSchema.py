from __future__ import annotations

from ResolvedActSchema import build_resolved_act_response_schema


PLAYER_ACTION_RESPONSE_SCHEMA = build_resolved_act_response_schema(
    "player_action_parse",
    include_tool_call=True,
)
