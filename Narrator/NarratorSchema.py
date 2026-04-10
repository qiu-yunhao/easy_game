NARRATOR_BATCH_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "narrator_batch",
        "schema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "history_turn": {"type": "integer"},
                            "actor": {"type": "string"},
                            "narrated_text": {"type": "string"},
                        },
                        "required": ["history_turn", "actor", "narrated_text"],
                        "additionalProperties": False,
                    },
                },
                "notes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["segments", "notes"],
            "additionalProperties": False,
        },
    },
}


NARRATOR_INTRO_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "narrator_intro",
        "schema": {
            "type": "object",
            "properties": {
                "intro_text": {"type": "string"},
                "notes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["intro_text", "notes"],
            "additionalProperties": False,
        },
    },
}
