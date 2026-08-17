from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from StoryStateUtils import normalize_lookup_text


ToolAudience = Literal["player", "story"]
StoryToolTask = Literal[
    "story_premise",
    "story_outline",
    "chapter_expansion",
    "scene_candidates",
    "director_update",
    "supporting_cast",
    "contextual_actor",
]
SKILLS_DIR = Path(__file__).resolve().parent / "skills"
DEFAULT_STORY_TOOL_SKILL_IDS: tuple[str, ...] = ("character_roster_skill",)
STORY_STATUS_TOOL_SKILL_IDS: tuple[str, ...] = ("character_status_skill",)
STORY_SCENE_TOOL_SKILL_IDS: tuple[str, ...] = ("scene_skill",)
STORY_MEMORY_TOOL_SKILL_IDS: tuple[str, ...] = ("memory_skill",)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    reason: str
    keywords: tuple[str, ...]
    parameters: dict[str, Any]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ToolSkillDefinition:
    skill_id: str
    file_name: str
    description: str
    trigger_keywords: tuple[str, ...]
    audiences: tuple[ToolAudience, ...]
    tools: tuple[ToolDefinition, ...]

    @property
    def file_path(self) -> Path:
        return SKILLS_DIR / self.file_name


def _tool(
    name: str,
    *,
    description: str,
    reason: str,
    keywords: tuple[str, ...],
    parameters: dict[str, Any] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        reason=reason,
        keywords=keywords,
        parameters=parameters or {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )


TOOL_SKILLS: tuple[ToolSkillDefinition, ...] = (
    ToolSkillDefinition(
        skill_id="inventory_skill",
        file_name="inventory_skill.md",
        description="Inventory and backpack queries.",
        trigger_keywords=("背包", "包里", "包裹", "物品", "道具", "inventory", "backpack", "item", "items"),
        audiences=("player", "story"),
        tools=(
            _tool(
                "query_inventory",
                description="Query the current player's inventory items and quantities.",
                reason="player wants inventory information",
                keywords=("背包", "包里", "包裹", "物品", "道具", "inventory", "backpack", "items"),
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="character_status_skill",
        file_name="character_status_skill.md",
        description="Player status, attributes, and current state.",
        trigger_keywords=("状态", "属性", "面板", "status", "stats", "profile"),
        audiences=("player", "story"),
        tools=(
            _tool(
                "query_player_status",
                description="Query the player's attributes, profile, and scene state.",
                reason="player or story agent wants character status information",
                keywords=("状态", "属性", "面板", "status", "stats", "profile"),
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="relation_skill",
        file_name="relation_skill.md",
        description="Relationship and favor queries for named characters.",
        trigger_keywords=("关系", "好感", "亲密", "relation", "favor", "affection"),
        audiences=("player",),
        tools=(
            _tool(
                "query_relation",
                description="Query the current player's relation with a target character.",
                reason="player wants relation information",
                keywords=("关系", "好感", "亲密", "relation", "favor", "affection"),
                parameters={
                    "type": "object",
                    "properties": {
                        "target_name": {
                            "type": "string",
                            "description": "Target character name or id.",
                        }
                    },
                    "required": ["target_name"],
                },
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="quest_skill",
        file_name="quest_skill.md",
        description="Quest and objective queries.",
        trigger_keywords=("任务", "委托", "目标", "quest", "quests", "objective"),
        audiences=("player",),
        tools=(
            _tool(
                "query_quests",
                description="Query the player's current active quests.",
                reason="player wants quest information",
                keywords=("任务", "委托", "目标", "quest", "quests", "objective"),
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="recall_skill",
        file_name="recall_skill.md",
        description="Long-term recall of past finished scenes via natural language.",
        trigger_keywords=("回忆", "之前", "经历", "记得", "曾经", "以前", "过去", "recall", "remember", "past"),
        audiences=("player",),
        tools=(
            _tool(
                "query_recall",
                description=(
                    "Recall what the player has experienced in earlier finished scenes. "
                    "Use only when the player asks about the past in natural language; "
                    "read-only, one-shot, returns relevant past history fragments."
                ),
                reason="player wants to recall past experiences",
                keywords=("回忆", "之前", "经历", "记得", "曾经", "以前", "过去", "recall", "remember", "past"),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language description of what the player wants to recall.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Optional max number of fragments to return (default 10).",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="save_load_skill",
        file_name="save_load_skill.md",
        description="Manual save and load operations.",
        trigger_keywords=("存档", "读档", "保存", "加载", "save", "load", "checkpoint"),
        audiences=("player",),
        tools=(
            _tool(
                "save_checkpoint",
                description="Save the current session snapshot for the active player.",
                reason="player wants to save progress",
                keywords=("存档", "保存", "save", "savegame", "checkpoint"),
                parameters={
                    "type": "object",
                    "properties": {
                        "save_label": {
                            "type": "string",
                            "description": "Optional manual save label.",
                        }
                    },
                    "required": [],
                },
            ),
            _tool(
                "load_checkpoint",
                description="Load the latest or requested save snapshot for a player.",
                reason="player wants to load progress",
                keywords=("读档", "加载", "load", "loadgame", "checkpoint"),
                parameters={
                    "type": "object",
                    "properties": {
                        "player_id": {
                            "type": "integer",
                            "description": "Optional player id to load.",
                        },
                        "slot_name": {
                            "type": "string",
                            "description": "Optional save slot name to load.",
                        },
                    },
                    "required": [],
                },
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="scene_skill",
        file_name="scene_skill.md",
        description="Current scene, stage, and runtime context for story agents.",
        trigger_keywords=("scene", "stage", "location", "context"),
        audiences=("story",),
        tools=(
            _tool(
                "query_scene_context",
                description="Query the current scene context, stage state, and nearby runtime constraints.",
                reason="agent wants current scene context",
                keywords=("scene", "stage", "location", "context"),
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="memory_skill",
        file_name="memory_skill.md",
        description="Recent story memory, compressed history, and open-loop context.",
        trigger_keywords=("memory", "history", "open loop", "conflict"),
        audiences=("story",),
        tools=(
            _tool(
                "query_story_memory",
                description="Query current scene memory, planning memory, and recent history context.",
                reason="agent wants story memory context",
                keywords=("memory", "history", "open loop", "conflict"),
            ),
        ),
    ),
    ToolSkillDefinition(
        skill_id="character_roster_skill",
        file_name="character_roster_skill.md",
        description="Character roster lookup for director/playwright style agents.",
        trigger_keywords=("角色清单", "角色列表", "roster", "cast", "layer"),
        audiences=("story",),
        tools=(
            _tool(
                "query_character_roster",
                description="Query the current save's roster summary and character list.",
                reason="agent wants character roster information",
                keywords=("角色清单", "角色列表", "roster", "cast", "layer"),
                parameters={
                    "type": "object",
                    "properties": {
                        "player_id": {
                            "type": "string",
                            "description": "Optional player id. Falls back to the active save.",
                        },
                        "layer_filter": {
                            "type": "string",
                            "enum": ["L1", "L2", "ActorAgent", "all"],
                            "description": "Filter by story layer.",
                        },
                    },
                    "required": ["player_id"],
                },
            ),
        ),
    ),
)


def _contains_any(normalized_text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword and normalize_lookup_text(keyword) in normalized_text for keyword in keywords)


def tool_skills_for_audience(audience: ToolAudience) -> tuple[ToolSkillDefinition, ...]:
    return tuple(spec for spec in TOOL_SKILLS if audience in spec.audiences)


def tool_skills_by_ids(
    skill_ids: Iterable[str],
    *,
    audience: ToolAudience | None = None,
) -> tuple[ToolSkillDefinition, ...]:
    ordered_ids: list[str] = []
    for skill_id in skill_ids:
        resolved = str(skill_id or "").strip()
        if resolved and resolved not in ordered_ids:
            ordered_ids.append(resolved)

    resolved_skills: list[ToolSkillDefinition] = []
    for skill_id in ordered_ids:
        skill = next((spec for spec in TOOL_SKILLS if spec.skill_id == skill_id), None)
        if skill is None:
            raise KeyError(f"Unknown tool skill: {skill_id}")
        if audience is not None and audience not in skill.audiences:
            raise KeyError(f"Tool skill {skill_id!r} is not available for audience {audience!r}")
        resolved_skills.append(skill)
    return tuple(resolved_skills)


def select_tool_skills(raw_input: str, *, audience: ToolAudience = "player") -> tuple[ToolSkillDefinition, ...]:
    normalized_text = normalize_lookup_text(raw_input)
    if not normalized_text:
        return ()
    matches: list[ToolSkillDefinition] = []
    for spec in tool_skills_for_audience(audience):
        if _contains_any(normalized_text, spec.trigger_keywords) or any(
            _contains_any(normalized_text, tool.keywords) for tool in spec.tools
        ):
            matches.append(spec)
    return tuple(matches)


def tool_definitions_for_audience(audience: ToolAudience) -> tuple[ToolDefinition, ...]:
    return tuple(tool for spec in tool_skills_for_audience(audience) for tool in spec.tools)


def find_tool_definition(name: str, *, audience: ToolAudience) -> ToolDefinition | None:
    for tool in tool_definitions_for_audience(audience):
        if tool.name == name:
            return tool
    return None


def match_tool_definition(
    raw_input: str,
    *,
    audience: ToolAudience = "player",
) -> tuple[ToolDefinition | None, ToolSkillDefinition | None]:
    normalized_text = normalize_lookup_text(raw_input)
    if not normalized_text:
        return None, None
    for skill in select_tool_skills(raw_input, audience=audience):
        for tool in skill.tools:
            if _contains_any(normalized_text, tool.keywords):
                return tool, skill
    return None, None


@lru_cache(maxsize=None)
def load_tool_skill_markdown(skill_id: str) -> str:
    for skill in TOOL_SKILLS:
        if skill.skill_id == skill_id:
            return skill.file_path.read_text(encoding="utf-8").strip()
    raise KeyError(f"Unknown tool skill: {skill_id}")


def _serialize_tool_skill_prompt(skill: ToolSkillDefinition) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "file_path": str(skill.file_path.relative_to(Path(__file__).resolve().parent)),
        "description": skill.description,
        "tool_names": [tool.name for tool in skill.tools],
        "tool_schemas": [tool.schema() for tool in skill.tools],
        "markdown": load_tool_skill_markdown(skill.skill_id),
    }


def _story_roster_snapshot_has_signal(character_roster_snapshot: Mapping[str, Any] | None) -> bool:
    if not isinstance(character_roster_snapshot, Mapping):
        return False
    summary = character_roster_snapshot.get("summary", {})
    if isinstance(summary, Mapping):
        for key in ("total_L1", "total_L2", "total_ActorAgent", "filtered_total"):
            if int(summary.get(key, 0) or 0) > 0:
                return True
    characters = character_roster_snapshot.get("characters", [])
    if isinstance(characters, list) and characters:
        return True
    decision_hints = character_roster_snapshot.get("decision_hints", {})
    return isinstance(decision_hints, Mapping) and bool(decision_hints)


def select_story_tool_skill_ids(
    *,
    task: StoryToolTask,
    character_roster_snapshot: Mapping[str, Any] | None = None,
    cast_size: int = 0,
    supporting_cast_count: int = 0,
    current_chapter_cast_count: int = 0,
    on_stage_count: int = 0,
    available_stage_candidate_count: int = 0,
    outline_exists: bool = False,
    history_count: int = 0,
    completed_chapter_count: int = 0,
) -> tuple[str, ...]:
    roster_ready = _story_roster_snapshot_has_signal(character_roster_snapshot)
    include_roster = task in {"supporting_cast", "contextual_actor"}
    include_status = task in {"story_outline", "chapter_expansion"}
    include_scene = task in {"director_update", "scene_candidates", "contextual_actor"} and (
        on_stage_count > 0 or available_stage_candidate_count > 0 or cast_size > 1
    )
    include_memory = task in {"director_update", "scene_candidates"} and history_count > 0
    if task == "story_premise":
        include_roster = roster_ready or supporting_cast_count > 0
    elif task == "story_outline":
        include_roster = roster_ready or supporting_cast_count > 0 or outline_exists
    elif task == "chapter_expansion":
        include_roster = roster_ready or current_chapter_cast_count > 1 or supporting_cast_count > 0 or outline_exists
        include_memory = completed_chapter_count > 0 or history_count > 0
    elif task == "scene_candidates":
        include_roster = (
            roster_ready
            or current_chapter_cast_count > max(1, on_stage_count)
            or supporting_cast_count > max(1, on_stage_count)
        )
        include_memory = history_count > 0 or completed_chapter_count > 0
    elif task == "director_update":
        include_roster = roster_ready or available_stage_candidate_count > 0 or cast_size > max(1, on_stage_count)
    selected: list[str] = []
    if include_status:
        selected.extend(STORY_STATUS_TOOL_SKILL_IDS)
    if include_scene:
        selected.extend(STORY_SCENE_TOOL_SKILL_IDS)
    if include_memory:
        selected.extend(STORY_MEMORY_TOOL_SKILL_IDS)
    if include_roster:
        selected.extend(DEFAULT_STORY_TOOL_SKILL_IDS)
    return tuple(selected)


def render_tool_schemas_for_prompt(
    raw_input: str | None = None,
    *,
    audience: ToolAudience = "player",
) -> list[dict[str, Any]]:
    if raw_input:
        selected = select_tool_skills(raw_input, audience=audience)
        if selected:
            return [tool.schema() for skill in selected for tool in skill.tools]
    return [tool.schema() for tool in tool_definitions_for_audience(audience)]


def render_tool_schemas_for_ids(
    skill_ids: Iterable[str],
    *,
    audience: ToolAudience,
) -> list[dict[str, Any]]:
    return [tool.schema() for skill in tool_skills_by_ids(skill_ids, audience=audience) for tool in skill.tools]


def load_tool_skill_prompt_context(
    raw_input: str,
    *,
    audience: ToolAudience = "player",
) -> list[dict[str, Any]]:
    return [_serialize_tool_skill_prompt(skill) for skill in select_tool_skills(raw_input, audience=audience)]


def load_tool_skill_prompt_context_for_ids(
    skill_ids: Iterable[str],
    *,
    audience: ToolAudience,
) -> list[dict[str, Any]]:
    return [_serialize_tool_skill_prompt(skill) for skill in tool_skills_by_ids(skill_ids, audience=audience)]


def build_story_tool_prompt_payload(
    *,
    task: StoryToolTask,
    character_roster_snapshot: Mapping[str, Any] | None = None,
    cast_size: int = 0,
    supporting_cast_count: int = 0,
    current_chapter_cast_count: int = 0,
    on_stage_count: int = 0,
    available_stage_candidate_count: int = 0,
    outline_exists: bool = False,
    history_count: int = 0,
    completed_chapter_count: int = 0,
) -> dict[str, Any]:
    skill_ids = select_story_tool_skill_ids(
        task=task,
        character_roster_snapshot=character_roster_snapshot,
        cast_size=cast_size,
        supporting_cast_count=supporting_cast_count,
        current_chapter_cast_count=current_chapter_cast_count,
        on_stage_count=on_stage_count,
        available_stage_candidate_count=available_stage_candidate_count,
        outline_exists=outline_exists,
        history_count=history_count,
        completed_chapter_count=completed_chapter_count,
    )
    return {
        "loaded_tool_skills": load_tool_skill_prompt_context_for_ids(skill_ids, audience="story"),
        "available_tools": render_tool_schemas_for_ids(skill_ids, audience="story"),
    }
