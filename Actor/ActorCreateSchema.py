"""ActorCreateSchema —— 演员创建相关的数据形状定义。

本模块只包含 **数据形状** 与 **常量**，不含任何业务逻辑或副作用：

- JSON Schema 常量（用于 LLM 响应结构化校验）
- 剧本演员数量上限
- 触发"背景保护"的亲缘/关系提示词

`actor_create_agent` 与 `ActorHeuristics` 等模块应该 **从这里导入**，
不要再在各自的文件里重复定义，以避免多份拷贝漂移出不一致的字段。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 容量常量
# ---------------------------------------------------------------------------
# L1 / L2 演员在同一场故事中的数量上限：
# - L1（核心角色）最多 6 位，承担长期主线冲突。
# - L2（重要配角）最多 15 位，作为可发展的支持角色池。
# - MAX_STORY_CHARACTERS 是同一剧本内可存在的"非玩家"命名角色总上限。
MAX_L1_AGENTS = 6
MAX_L2_AGENTS = 15
MAX_STORY_CHARACTERS = MAX_L1_AGENTS + MAX_L2_AGENTS


# ---------------------------------------------------------------------------
# 背景关系提示词
# ---------------------------------------------------------------------------
# 玩家背景故事文本中若出现下列任一关键词，就视为"玩家提到过的重要关系人"，
# 命中即触发背景保护逻辑：该角色不得被随意替换或降级，且分层评估时
# 会倾向于赋予更高的剧情权重（core / deep / 可晋升到 L1）。
BACKSTORY_RELATION_HINTS = (
    "妹妹",
    "弟弟",
    "哥哥",
    "姐姐",
    "师父",
    "师尊",
    "师兄",
    "师姐",
    "师弟",
    "师妹",
    "父亲",
    "母亲",
    "爷爷",
    "奶奶",
    "外公",
    "外婆",
    "宿敌",
    "挚友",
    "青梅",
    "道侣",
    "同门",
    "族长",
)


# ---------------------------------------------------------------------------
# L2 / L1 剧本档 schema
# ---------------------------------------------------------------------------
L2_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "core_drive": {"type": "string", "minLength": 1},
        "judgement_preference": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 2,
        },
        "behavior_rule": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 2,
        },
        "speech_style": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 2,
        },
        "personality_tags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "core_drive",
        "judgement_preference",
        "behavior_rule",
        "speech_style",
        "personality_tags",
    ],
    "additionalProperties": False,
}

L1_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "core_conflict": {"type": "string", "minLength": 1},
        "outer_goal": {"type": "string", "minLength": 1},
        "inner_need": {"type": "string", "minLength": 1},
        "contradiction_axes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "relationship_pressure": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "core_conflict",
        "outer_goal",
        "inner_need",
        "contradiction_axes",
        "relationship_pressure",
    ],
    "additionalProperties": False,
}

LAYER_ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "mentioned_in_player_backstory": {"type": "boolean"},
        "plot_significance": {
            "type": "string",
            "enum": ["core", "supporting", "replaceable"],
        },
        "relationship_depth": {
            "type": "string",
            "enum": ["deep", "functional", "unknown"],
        },
        "long_term_plot_significance": {"type": "boolean"},
        "can_promote_to_l1": {"type": "boolean"},
        "assignment_reason": {"type": "string"},
    },
    "required": [
        "mentioned_in_player_backstory",
        "plot_significance",
        "relationship_depth",
        "long_term_plot_significance",
        "can_promote_to_l1",
        "assignment_reason",
    ],
    "additionalProperties": False,
}

SUPPORTING_CHARACTER_PROPERTIES = {
    "character_id": {"type": "string", "minLength": 1},
    "name": {"type": "string", "minLength": 1},
    "story_role": {"type": "string", "minLength": 1},
    "persona": {
        "type": "array",
        "items": {"type": "string"},
    },
    "base_style": {"type": "string", "minLength": 1},
    "background": {"type": "string", "minLength": 1},
    "occupation": {"type": "string"},
    "secrets": {
        "type": "array",
        "items": {"type": "string"},
    },
    "gender": {"type": "string"},
    "race": {"type": "string"},
    "agent_type": {
        "type": "string",
        "enum": ["actor", "L2", "L1"],
    },
    "layer_assignment": LAYER_ASSIGNMENT_SCHEMA,
    "l2_profile": L2_PROFILE_SCHEMA,
    "l1_profile": L1_PROFILE_SCHEMA,
    "spiritual_root": {"type": "string"},
    "realm": {"type": "string"},
    "main_technique": {"type": "string"},
    "base_relationship": {
        "type": "object",
        "additionalProperties": {"type": "number"},
    },
    "planned_chapter_count": {
        "type": "integer",
        "minimum": 0,
        "maximum": 20,
    },
    "planned_chapter_ids": {
        "type": "array",
        "items": {"type": "string"},
    },
    "introduction_hint": {"type": "string"},
}

SUPPORTING_CHARACTER_REQUIRED = [
    "character_id",
    "name",
    "story_role",
    "persona",
    "base_style",
    "background",
    "secrets",
    "agent_type",
    "layer_assignment",
    "spiritual_root",
    "realm",
    "main_technique",
    "base_relationship",
    "planned_chapter_count",
    "planned_chapter_ids",
    "introduction_hint",
]


ACTOR_CREATE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "actor_create_supporting_cast",
        "schema": {
            "type": "object",
            "properties": {
                "characters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": SUPPORTING_CHARACTER_PROPERTIES,
                        "required": SUPPORTING_CHARACTER_REQUIRED,
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["characters"],
            "additionalProperties": False,
        },
    },
}


CONTEXTUAL_ACTOR_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "actor_create_contextual_actor",
        "schema": {
            "type": "object",
            "properties": {
                "actor": {
                    "type": "object",
                    "properties": SUPPORTING_CHARACTER_PROPERTIES,
                    "required": SUPPORTING_CHARACTER_REQUIRED,
                    "additionalProperties": False,
                },
            },
            "required": ["actor"],
            "additionalProperties": False,
        },
    },
}


__all__ = [
    "MAX_L1_AGENTS",
    "MAX_L2_AGENTS",
    "MAX_STORY_CHARACTERS",
    "BACKSTORY_RELATION_HINTS",
    "L2_PROFILE_SCHEMA",
    "L1_PROFILE_SCHEMA",
    "LAYER_ASSIGNMENT_SCHEMA",
    "SUPPORTING_CHARACTER_PROPERTIES",
    "SUPPORTING_CHARACTER_REQUIRED",
    "ACTOR_CREATE_RESPONSE_SCHEMA",
    "CONTEXTUAL_ACTOR_RESPONSE_SCHEMA",
]
