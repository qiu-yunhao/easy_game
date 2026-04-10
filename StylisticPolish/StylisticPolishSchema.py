STYLISTIC_POLISH_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "stylistic_polish",
        "schema": {
            "type": "object",
            "properties": {
                "polished_action": {"type": "string"},
                "diagnosis": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["polished_action", "diagnosis"],
            "additionalProperties": False,
        },
    },
}


STYLISTIC_NARRATION_BATCH_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "stylistic_narration_batch",
        "schema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "history_turn": {"type": "integer"},
                            "polished_text": {"type": "string"},
                        },
                        "required": ["history_turn", "polished_text"],
                        "additionalProperties": False,
                    },
                },
                "diagnosis": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["segments", "diagnosis"],
            "additionalProperties": False,
        },
    },
}
