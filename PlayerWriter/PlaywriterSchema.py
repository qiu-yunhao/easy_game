STORY_PREMISE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "playwright_story_premise",
        "schema": {
            "type": "object",
            "properties": {
                "story_premise": {"type": "string", "minLength": 1},
                "exploration_drive": {"type": "string", "minLength": 1},
            },
            "required": [
                "story_premise",
                "exploration_drive",
            ],
            "additionalProperties": False,
        },
    },
}


STORY_OUTLINE_BRIEF_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "playwright_story_outline_brief",
        "schema": {
            "type": "object",
            "properties": {
                "story_outline": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "chapter_id": {"type": "string", "minLength": 1},
                            "title": {"type": "string", "minLength": 1},
                            "main_goal": {"type": "string", "minLength": 1},
                            "summary": {"type": "string", "minLength": 1},
                        },
                        "required": [
                            "chapter_id",
                            "title",
                            "main_goal",
                            "summary",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "story_outline",
            ],
            "additionalProperties": False,
        },
    },
}


CHAPTER_EXPANSION_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "playwright_chapter_expansion",
        "schema": {
            "type": "object",
            "properties": {
                "chapter_title": {"type": "string", "minLength": 1},
                "chapter_goal": {"type": "string", "minLength": 1},
                "chapter_overview": {"type": "string", "minLength": 1},
                "exploration_hooks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "key_locations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "chapter_title",
                "chapter_goal",
                "chapter_overview",
                "exploration_hooks",
                "key_locations",
            ],
            "additionalProperties": False,
        },
    },
}


SCENE_CANDIDATES_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "playwright_scene_candidates",
        "schema": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "candidate_id": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                            "location_id": {"type": "string", "minLength": 1},
                            "beat": {"type": "string", "minLength": 1},
                            "scene_goal": {"type": "string", "minLength": 1},
                            "must_happen": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "must_not_happen": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "dramatic_curve": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "character_objectives": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                            "exit_condition": {"type": "string", "minLength": 1},
                            "notes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "candidate_id",
                            "label",
                            "location_id",
                            "beat",
                            "scene_goal",
                            "must_happen",
                            "must_not_happen",
                            "dramatic_curve",
                            "character_objectives",
                            "exit_condition",
                            "notes",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "candidates",
            ],
            "additionalProperties": False,
        },
    },
}
