DIRECTOR_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "director_stage_brief",
        "schema": {
            "type": "object",
            "properties": {
                "beat": {"type": "string"},
                "beat_goal": {"type": "string"},
                "focus_character": {"type": ["string", "null"]},
                "tension_target": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "allow_interrupt": {"type": "boolean"},
                "who_should_respond": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "lead_in_text": {"type": "string"},
                "wrap_up_text": {"type": "string"},
                "stage_actions": {
                    "type": "object",
                    "properties": {
                        "enter": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "leave": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "suppress": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "unsuppress": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["enter", "leave", "suppress", "unsuppress"],
                    "additionalProperties": False,
                },
                "notes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "beat",
                "beat_goal",
                "focus_character",
                "tension_target",
                "allow_interrupt",
                "who_should_respond",
                "lead_in_text",
                "wrap_up_text",
                "stage_actions",
                "notes",
            ],
            "additionalProperties": False,
        },
    },
}
