HISTORY_SCORE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "history_score_result",
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "turn": {"type": "integer"},
                            "importance_score": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "score_reason": {"type": "string"},
                        },
                        "required": ["turn", "importance_score", "score_reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
}


HISTORY_CHUNK_SUMMARY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "history_chunk_summary",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "actors": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["summary", "key_points", "actors"],
            "additionalProperties": False,
        },
    },
}
