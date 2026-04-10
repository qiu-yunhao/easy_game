from __future__ import annotations

from typing import Any


def build_resolved_act_response_schema(
    schema_name: str,
    *,
    include_actor: bool = False,
    include_content: bool = False,
    include_tool_call: bool = False,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "mode": {"type": "string"},
        "target": {"type": ["string", "null"]},
        "spoken_text": {"type": "string"},
        "nonverbal_action": {"type": "string"},
        "next_intent": {"type": "string"},
        "emotion_update": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "relationship_update": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "revealed_facts": {
            "type": "array",
            "items": {"type": "string"},
        },
        "triggered_plot_flags": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "should_end_scene": {"type": "boolean"},
        "should_end_chapter": {"type": "boolean"},
    }
    required = [
        "mode",
        "target",
        "spoken_text",
        "nonverbal_action",
        "next_intent",
        "emotion_update",
        "relationship_update",
        "revealed_facts",
        "triggered_plot_flags",
        "should_end_scene",
        "should_end_chapter",
    ]

    if include_actor:
        properties["actor"] = {"type": ["string", "null"]}
        required.insert(0, "actor")
    if include_content:
        properties["content"] = {"type": "string"}
    if include_tool_call:
        properties["tool_call"] = {
            "type": "object",
            "properties": {
                "should_call": {"type": "boolean"},
                "name": {
                    "type": "string",
                    "enum": [
                        "",
                        "query_inventory",
                        "query_player_status",
                        "query_relation",
                        "query_quests",
                        "save_checkpoint",
                        "load_checkpoint",
                    ],
                },
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "reason": {"type": "string"},
            },
            "required": ["should_call", "name", "arguments", "reason"],
            "additionalProperties": False,
        }
        required.append("tool_call")

    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
