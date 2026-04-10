from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from BaseAgent import AgentMessage, BaseAgent
from CharacterProfile import (
    DEFAULT_CURRENT_REALM,
    DEFAULT_MAIN_TECHNIQUE,
    DEFAULT_SPIRITUAL_ROOT,
    ensure_character_profile,
    normalize_l1_agent_profile,
    normalize_l2_agent_profile,
    normalize_layer_assignment,
    normalize_relationship_mapping,
)
from CharacterRosterTools import CharacterRosterToolRuntime
from PromptUtils import render_json_instruction
from StoryStateUtils import (
    clean_str_list,
    clean_text,
    resolve_player_character_id,
    serialize_story_cast_member,
    story_outline_entries,
)
from StoryToolContext import build_story_tool_prompt_context

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile
    from GameState import GameState
    from SceneConfig import SceneConfig


MAX_L1_AGENTS = 6
MAX_L2_AGENTS = 15
MAX_STORY_CHARACTERS = MAX_L1_AGENTS + MAX_L2_AGENTS
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


ACTOR_CREATE_SYSTEM_PROMPT = """
You are the Story Layer and Cast Architect for an open-world xianxia roleplay game.
Your job is to supplement the cast so later Actor agents have concrete character settings to play,
and to assign each new role into the correct interactive layer.

Rules:
- Return strict JSON only.
- Never exceed the provided player-bound L1/L2 limits unless the role is explicitly protected by the player-backstory rule.
- Base `actor` roles are reusable ActorAgent templates and are not constrained by the L1/L2 caps.
- Before creating or upgrading any role, inspect the provided `character_roster_snapshot`.
- When `loaded_tool_skills` is provided, inspect those skill modules first and follow their tool contracts exactly.
- If the roster snapshot shows that an L1 or L2 layer is already full, reuse an existing role or downgrade the function unless the player-backstory rule explicitly protects the role.
- Reuse existing supporting character ids when the same person already exists.
- If no story outline exists yet, only extract characters that the player clearly implied in the background.
- If a story outline exists, create only the minimum supplemental cast needed to support those chapters.
- Do not return the player character as a new character.
- Every character needs a distinct dramatic function and practical reason to appear.
- Every character must include `spiritual_root`, `realm`, and `main_technique`, even when they are ordinary defaults.
- You are also responsible for `agent_type` assignment:
  - Use base `actor` for reusable functional roles that mainly provide atmosphere, logistics, simple guidance, or one-shot scene support.
  - Any character clearly mentioned in the player's background by name, title, or explicit relationship must be at least interactive (`L2` or `L1`), never a discardable background extra.
  - Use `L1` for long-term mainline roles, deep bonds, irreplaceable rivals, blood/fate ties, or characters expected to carry major turning points across chapters.
  - Use `L2` for important but softer support roles that mainly serve a scene, chapter, route, or short-term functional need.
  - Prefer `actor` when the role is replaceable, single-purpose, and does not need long-lived autonomous planning.
  - If a background-mentioned role matters but their long-term weight is still unclear, choose `L2`, not `L1`.
  - You may mark an `L2` with `layer_assignment.can_promote_to_l1 = true` when the role could later be upgraded.
- Every generated role must include `layer_assignment`.
- If `agent_type = "L2"`, include a compact `l2_profile`.
- If `agent_type = "L1"`, include a complete `l1_profile`.
- `planned_chapter_ids` may only use chapter ids that were provided to you.
"""

def _build_character_id(
    *,
    raw_id: str,
    name: str,
    character_profiles: dict[str, "CharacterProfile"],
    used_ids: set[str],
    fallback_index: int,
) -> str:
    if raw_id and raw_id in character_profiles:
        return raw_id
    if name:
        for character_id, profile in character_profiles.items():
            if clean_text(profile.get("name", "")) == name:
                return character_id

    candidate = re.sub(r"[^a-z0-9]+", "_", raw_id.lower()).strip("_")
    if not candidate:
        candidate = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not candidate:
        candidate = f"supporting_{fallback_index}"

    resolved = candidate
    suffix = 2
    while resolved in character_profiles or resolved in used_ids:
        resolved = f"{candidate}_{suffix}"
        suffix += 1
    return resolved


def _assign_chapter_ids(
    *,
    outline_ids: list[str],
    start_index: int,
    planned_chapter_count: int,
) -> list[str]:
    if not outline_ids or planned_chapter_count <= 0:
        return []

    chapter_ids: list[str] = []
    bounded_start = max(0, min(start_index, len(outline_ids) - 1))
    for chapter_id in outline_ids[bounded_start:]:
        if chapter_id not in chapter_ids:
            chapter_ids.append(chapter_id)
        if len(chapter_ids) >= planned_chapter_count:
            break

    if len(chapter_ids) < planned_chapter_count:
        for chapter_id in outline_ids:
            if chapter_id not in chapter_ids:
                chapter_ids.append(chapter_id)
            if len(chapter_ids) >= planned_chapter_count:
                break

    return chapter_ids


def _contains_backstory_signal(player_background: str, candidate_text: str) -> bool:
    background = clean_text(player_background)
    candidate = clean_text(candidate_text)
    if not background or not candidate:
        return False
    if len(candidate) >= 2 and candidate in background:
        return True
    return any(hint in candidate and hint in background for hint in BACKSTORY_RELATION_HINTS)


def _infer_backstory_priority(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    player_background: str,
) -> bool:
    for source in (raw_character.get("layer_assignment"), existing_profile.get("layer_assignment")):
        if isinstance(source, Mapping) and isinstance(source.get("mentioned_in_player_backstory"), bool):
            return bool(source.get("mentioned_in_player_backstory"))

    for candidate_text in (
        raw_character.get("name", ""),
        raw_character.get("story_role", ""),
        raw_character.get("introduction_hint", ""),
        existing_profile.get("name", ""),
        existing_profile.get("story_role", ""),
        existing_profile.get("introduction_hint", ""),
    ):
        if _contains_backstory_signal(player_background, clean_text(candidate_text)):
            return True
    return False


def _build_layer_assignment_seed(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    player_background: str,
    planned_chapter_count: int,
    planned_chapter_ids: list[str],
) -> dict[str, Any]:
    explicit_assignment = raw_character.get("layer_assignment")
    explicit_assignment = explicit_assignment if isinstance(explicit_assignment, Mapping) else {}
    existing_assignment = existing_profile.get("layer_assignment")
    existing_assignment = existing_assignment if isinstance(existing_assignment, Mapping) else {}

    mentioned_in_player_backstory = _infer_backstory_priority(
        raw_character,
        existing_profile,
        player_background=player_background,
    )
    plot_significance = clean_text(
        explicit_assignment.get("plot_significance", ""),
        clean_text(existing_assignment.get("plot_significance", ""), "supporting"),
    ).lower()
    if plot_significance not in {"core", "supporting", "replaceable"}:
        plot_significance = "supporting"

    relationship_depth = clean_text(
        explicit_assignment.get("relationship_depth", ""),
        clean_text(existing_assignment.get("relationship_depth", ""), "unknown"),
    ).lower()
    if relationship_depth not in {"deep", "functional", "unknown"}:
        relationship_depth = "functional" if mentioned_in_player_backstory else "unknown"

    explicit_long_term = explicit_assignment.get("long_term_plot_significance")
    existing_long_term = existing_assignment.get("long_term_plot_significance")
    long_term_plot_significance = (
        bool(explicit_long_term)
        if isinstance(explicit_long_term, bool)
        else (
            bool(existing_long_term)
            if isinstance(existing_long_term, bool)
            else planned_chapter_count >= 2 or len(planned_chapter_ids) >= 2
        )
    )

    assignment_reason = clean_text(
        explicit_assignment.get("assignment_reason", ""),
        clean_text(existing_assignment.get("assignment_reason", "")),
    )
    if not assignment_reason:
        if mentioned_in_player_backstory and long_term_plot_significance:
            assignment_reason = "player_backstory_long_term"
        elif mentioned_in_player_backstory:
            assignment_reason = "player_backstory_interactive_floor"
        elif plot_significance == "core":
            assignment_reason = "core_plot_weight"
        else:
            assignment_reason = "supporting_plot_need"

    explicit_can_promote = explicit_assignment.get("can_promote_to_l1")
    existing_can_promote = existing_assignment.get("can_promote_to_l1")
    can_promote_to_l1 = (
        bool(explicit_can_promote)
        if isinstance(explicit_can_promote, bool)
        else (
            bool(existing_can_promote)
            if isinstance(existing_can_promote, bool)
            else bool(
                mentioned_in_player_backstory
                or long_term_plot_significance
                or plot_significance == "supporting"
            )
        )
    )

    return {
        "mentioned_in_player_backstory": mentioned_in_player_backstory,
        "plot_significance": plot_significance,
        "relationship_depth": relationship_depth,
        "long_term_plot_significance": long_term_plot_significance,
        "can_promote_to_l1": can_promote_to_l1,
        "assignment_reason": assignment_reason,
    }


def _resolve_story_agent_type(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    layer_assignment_seed: Mapping[str, Any],
    planned_chapter_count: int,
    planned_chapter_ids: list[str],
) -> str:
    explicit_agent_type = clean_text(
        raw_character.get("agent_type", ""),
        clean_text(existing_profile.get("agent_type", "")),
    )
    if explicit_agent_type not in {"actor", "L1", "L2"}:
        explicit_agent_type = ""

    mentioned_in_player_backstory = bool(layer_assignment_seed.get("mentioned_in_player_backstory", False))
    long_term_plot_significance = bool(layer_assignment_seed.get("long_term_plot_significance", False))
    plot_significance = clean_text(layer_assignment_seed.get("plot_significance", ""), "supporting")
    relationship_depth = clean_text(layer_assignment_seed.get("relationship_depth", ""), "unknown")
    multi_chapter_presence = planned_chapter_count >= 2 or len(planned_chapter_ids) >= 2

    if mentioned_in_player_backstory:
        if explicit_agent_type == "L1":
            return "L1"
        if long_term_plot_significance or plot_significance == "core" or relationship_depth == "deep":
            return "L1"
        return "L2"

    if explicit_agent_type:
        return explicit_agent_type
    if long_term_plot_significance or multi_chapter_presence or plot_significance == "core":
        return "L1"
    if plot_significance == "replaceable":
        return "actor"
    return "L2"


def _count_story_layers(character_profiles: dict[str, "CharacterProfile"]) -> tuple[int, int]:
    l1_count = 0
    l2_count = 0
    for profile in character_profiles.values():
        agent_type = clean_text(profile.get("agent_type", ""), "actor")
        if agent_type == "L1":
            l1_count += 1
        elif agent_type == "L2":
            l2_count += 1
    return l1_count, l2_count


def _resolve_effective_roster_counts(
    character_profiles: dict[str, "CharacterProfile"],
    character_roster_snapshot: Mapping[str, Any] | None,
) -> tuple[int, int, int]:
    local_l1_count, local_l2_count = _count_story_layers(character_profiles)
    local_actor_count = sum(
        1
        for character_id, profile in character_profiles.items()
        if character_id != "player" and clean_text(profile.get("agent_type", "actor"), "actor") == "actor"
    )
    summary = (
        character_roster_snapshot.get("summary", {})
        if isinstance(character_roster_snapshot, Mapping)
        else {}
    )
    roster_l1_count = int(summary.get("total_L1", 0) or 0) if isinstance(summary, Mapping) else 0
    roster_l2_count = int(summary.get("total_L2", 0) or 0) if isinstance(summary, Mapping) else 0
    roster_actor_count = int(summary.get("total_ActorAgent", 0) or 0) if isinstance(summary, Mapping) else 0
    return (
        max(local_l1_count, roster_l1_count),
        max(local_l2_count, roster_l2_count),
        max(local_actor_count, roster_actor_count),
    )


def _respect_agent_layer_limits(
    *,
    resolved_agent_type: str,
    layer_assignment: Mapping[str, Any],
    existing_l1_count: int,
    existing_l2_count: int,
    new_l1_count: int,
    new_l2_count: int,
) -> str:
    mentioned_in_player_backstory = bool(layer_assignment.get("mentioned_in_player_backstory", False))
    if resolved_agent_type == "L1":
        if existing_l1_count + new_l1_count < MAX_L1_AGENTS or mentioned_in_player_backstory:
            return "L1"
        resolved_agent_type = "L2"
    if resolved_agent_type == "L2":
        if existing_l2_count + new_l2_count < MAX_L2_AGENTS or mentioned_in_player_backstory:
            return "L2"
    return "actor"


def _respect_player_bound_capacity(
    *,
    resolved_agent_type: str,
    layer_assignment: Mapping[str, Any],
    max_total_characters: int,
    existing_l1_count: int,
    existing_l2_count: int,
    new_l1_count: int,
    new_l2_count: int,
) -> str:
    if resolved_agent_type not in {"L1", "L2"}:
        return resolved_agent_type
    if max_total_characters <= 0:
        return resolved_agent_type if bool(layer_assignment.get("mentioned_in_player_backstory", False)) else "actor"

    current_story_bound_count = existing_l1_count + existing_l2_count + new_l1_count + new_l2_count
    if current_story_bound_count < max_total_characters or bool(
        layer_assignment.get("mentioned_in_player_backstory", False)
    ):
        return resolved_agent_type
    return "actor"


class ActorCreateAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        character_roster_tool_runtime = kwargs.pop("character_roster_tool_runtime", None)
        super().__init__(
            system_prompt=ACTOR_CREATE_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.45),
            max_tokens=kwargs.pop("max_tokens", 1800),
            **kwargs,
        )
        self.character_roster_tool_runtime: CharacterRosterToolRuntime | None = character_roster_tool_runtime

    def bind_character_roster_tool_runtime(
        self,
        tool_runtime: CharacterRosterToolRuntime | None,
    ) -> None:
        self.character_roster_tool_runtime = tool_runtime

    def build_instruction(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: CharacterRosterToolRuntime | None = None,
        resolved_snapshots: dict[str, Any] | None = None,
    ) -> str:
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        existing_l1_count, existing_l2_count, existing_actor_count = _resolve_effective_roster_counts(
            character_profiles,
            character_roster_snapshot,
        )
        outline = [
            {
                "chapter_id": clean_text(chapter.get("chapter_id")),
                "title": clean_text(chapter.get("title")),
                "main_goal": clean_text(chapter.get("main_goal")),
                "summary": clean_text(chapter.get("summary")),
            }
            for chapter in game_state["plot"].get("story_outline", [])
            if isinstance(chapter, Mapping)
        ]
        existing_cast = [
            serialize_story_cast_member(character_id, profile)
            for character_id, profile in character_profiles.items()
        ]
        payload = {
            "creative_goal": (
                "Supplement the cast so the story outline and current/future chapters have concrete interactive agents "
                "with an intentional L1/L2 layer assignment."
            ),
            "constraints": {
                "max_player_bound_characters": max_total_characters,
                "existing_player_bound_character_count": existing_l1_count + existing_l2_count,
                "max_new_player_bound_characters": max(
                    0,
                    max_total_characters - (existing_l1_count + existing_l2_count),
                ),
                "base_actor_templates_are_unbounded": True,
                "has_story_outline": bool(outline),
                "instruction_when_no_outline": (
                    "Only return characters that the player's background clearly implies."
                ),
                "instruction_when_outline_exists": (
                    "Create or refine only the minimum supporting cast needed for the outlined chapters."
                ),
                "player_backstory_floor_rule": (
                    "Any role clearly mentioned in the player background must be assigned as L1 or L2, never treated as a discardable extra."
                ),
                "L1_rule": (
                    "Use L1 for long-term mainline roles, deep bonds, irreplaceable rivals, blood/fate ties, or characters expected to carry major turns."
                ),
                "L2_rule": (
                    "Use L2 for important but softer support roles that mainly serve a scene, chapter, route, or short-term functional need."
                ),
                "actor_rule": (
                    "Use actor for functional or atmospheric roles that can be reused as a shared template and do not need long-horizon autonomy."
                ),
                "max_l1_agents": MAX_L1_AGENTS,
                "existing_l1_agents": existing_l1_count,
                "max_l2_agents": MAX_L2_AGENTS,
                "existing_l2_agents": existing_l2_count,
                "existing_actor_templates": existing_actor_count,
            },
            "player_character_id": player_id,
            "player_profile": {
                "name": clean_text(player_profile.get("name", player_id)),
                "background": clean_text(player_profile.get("background", "")),
                "race": clean_text(player_profile.get("race", "")),
                "spiritual_root": clean_text(
                    player_profile.get("spiritual_root", ""),
                    DEFAULT_SPIRITUAL_ROOT,
                ),
                "realm": clean_text(player_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                "main_technique": clean_text(
                    player_profile.get("main_technique", ""),
                    DEFAULT_MAIN_TECHNIQUE,
                ),
            },
            "story": {
                "story_premise": clean_text(game_state["plot"].get("story_premise", "")),
                "exploration_drive": clean_text(game_state["plot"].get("exploration_drive", "")),
                "current_chapter_id": clean_text(game_state["plot"].get("chapter_id", "")),
                "current_chapter_title": clean_text(game_state["plot"].get("current_chapter_title", "")),
                "current_chapter_overview": clean_text(
                    game_state["plot"].get("current_chapter_overview", "")
                ),
                "story_outline": outline,
            },
            "opening_scene_seed": {
                "scene_id": clean_text(game_state["plot"].get("scene_id", "")),
                "location_id": clean_text(game_state["scene"].get("location_id", "")),
                "time_tag": clean_text(game_state["scene"].get("time_tag", "")),
                "default_on_stage": clean_str_list(scene_config.get("default_on_stage", [])),
            },
            **build_story_tool_prompt_context(
                task="supporting_cast",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                resolved_snapshots=resolved_snapshots,
                cast_size=len(existing_cast),
                supporting_cast_count=max(0, len(existing_cast) - 1),
                outline_exists=bool(outline),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "existing_cast": existing_cast,
        }
        return render_json_instruction(
            "Return only supplemental character settings as strict JSON. "
            "Do not echo the full cast. Reuse existing supporting ids when refining already generated characters. "
            "Use lowercase ASCII snake_case ids whenever you create a new id. "
            "Every character must include `agent_type` and `layer_assignment`. "
            "If `agent_type` is `L2`, include a complete `l2_profile`; if `agent_type` is `L1`, include a complete `l1_profile`. "
            "For reusable base actors, set `agent_type` to `actor` and include a practical `occupation`.",
            payload,
        )

    def build_contextual_actor_instruction(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        destination: str,
        objective: str,
        reward_item: str,
        player_intent: str,
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: CharacterRosterToolRuntime | None = None,
        resolved_snapshots: dict[str, Any] | None = None,
    ) -> str:
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        existing_cast = [
            serialize_story_cast_member(character_id, profile)
            for character_id, profile in character_profiles.items()
        ]
        payload = {
            "creative_goal": (
                "Create exactly one interactive profile who can be activated in the very next scene "
                "to respond to the player's immediate intent. This ActorAgent may be any fitting archetype: "
                "disciple, guard, attendant, elder, vendor, witness, gatekeeper, rival, guide, or another scene-appropriate role."
            ),
            "constraints": {
                "create_exactly_one_actor": True,
                "actor_must_not_be_player": True,
                "actor_should_be_usable_immediately": True,
                "actor_type_is_not_fixed": True,
                "choose_L1_only_when_the_scene_introduces_a_major_long_arc_role": True,
            },
            "player_character_id": player_id,
            "player_profile": {
                "name": clean_text(player_profile.get("name", player_id)),
                "background": clean_text(player_profile.get("background", "")),
                "spiritual_root": clean_text(
                    player_profile.get("spiritual_root", ""),
                    DEFAULT_SPIRITUAL_ROOT,
                ),
                "realm": clean_text(player_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                "main_technique": clean_text(
                    player_profile.get("main_technique", ""),
                    DEFAULT_MAIN_TECHNIQUE,
                ),
            },
            "immediate_scene_need": {
                "destination": clean_text(destination),
                "objective": clean_text(objective),
                "reward_item": clean_text(reward_item),
                "player_intent": clean_text(player_intent),
                "current_location": clean_text(game_state["scene"].get("location_id", "")),
            },
            "story": {
                "chapter_id": clean_text(game_state["plot"].get("chapter_id", "")),
                "chapter_title": clean_text(game_state["plot"].get("current_chapter_title", "")),
                "chapter_goal": clean_text(game_state["plot"].get("chapter_goal", "")),
                "story_premise": clean_text(game_state["plot"].get("story_premise", "")),
                "exploration_drive": clean_text(game_state["plot"].get("exploration_drive", "")),
            },
            "scene_config": {
                "scene_id": clean_text(scene_config.get("scene_id", "")),
                "default_location_id": clean_text(scene_config.get("default_location_id", "")),
            },
            **build_story_tool_prompt_context(
                task="contextual_actor",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                resolved_snapshots=resolved_snapshots,
                cast_size=len(existing_cast),
                supporting_cast_count=max(0, len(existing_cast) - 1),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "existing_cast": existing_cast,
        }
        return render_json_instruction(
            "Return exactly one contextual ActorAgent under the `actor` field as strict JSON. "
            "This actor should exist to make the next scene playable and interactive. "
            "Do not generate multiple characters, and do not write scene prose or dialogue. "
            "Choose between `actor`, `L2`, and `L1` using the same story-weight rules. "
            "Always include `layer_assignment`, plus the matching `l2_profile` or `l1_profile` when applicable.",
            payload,
        )

    def normalize_supporting_cast(
        self,
        output: Mapping[str, Any] | None,
        *,
        game_state: "GameState",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, "CharacterProfile"]:
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        player_background = clean_text(player_profile.get("background", ""))
        outline_ids = [
            clean_text(chapter.get("chapter_id"))
            for chapter in story_outline_entries(game_state)
            if clean_text(chapter.get("chapter_id"))
        ]
        current_chapter_id = clean_text(game_state["plot"].get("chapter_id"))
        start_index = outline_ids.index(current_chapter_id) if current_chapter_id in outline_ids else 0
        existing_l1_count, existing_l2_count, _ = _resolve_effective_roster_counts(
            character_profiles,
            character_roster_snapshot,
        )
        new_l1_count = 0
        new_l2_count = 0
        normalized: dict[str, CharacterProfile] = {}
        used_ids: set[str] = set()

        for fallback_index, raw_character in enumerate(output.get("characters", []) if output else [], start=1):
            if not isinstance(raw_character, Mapping):
                continue

            raw_id = clean_text(raw_character.get("character_id", ""))
            name = clean_text(raw_character.get("name", ""))
            if not name:
                continue

            character_id = _build_character_id(
                raw_id=raw_id,
                name=name,
                character_profiles=character_profiles,
                used_ids=used_ids,
                fallback_index=fallback_index,
            )
            existing_profile = character_profiles.get(character_id, {})
            existing_source = clean_text(existing_profile.get("profile_source", ""))
            if character_id in character_profiles and existing_source != "actor_create_agent":
                continue

            story_role = clean_text(raw_character.get("story_role", "")) or clean_text(
                existing_profile.get("story_role", "")
            )
            persona = clean_str_list(raw_character.get("persona", [])) or clean_str_list(
                existing_profile.get("persona", [])
            )
            if not persona:
                persona = [story_role or "supporting cast", "watchful", "decisive"]

            base_style = clean_text(raw_character.get("base_style", "")) or clean_text(
                existing_profile.get("base_style", "")
            )
            if not base_style:
                base_style = story_role or "measured and vivid"

            background = clean_text(raw_character.get("background", "")) or clean_text(
                existing_profile.get("background", "")
            )
            if not background:
                background = f"{name} is a supporting figure in the current story arc."

            secrets = clean_str_list(raw_character.get("secrets", [])) or clean_str_list(
                existing_profile.get("secrets", [])
            )

            provided_chapter_ids = [
                chapter_id
                for chapter_id in clean_str_list(raw_character.get("planned_chapter_ids", []))
                if chapter_id in outline_ids
            ]
            planned_chapter_count = int(raw_character.get("planned_chapter_count", 0) or 0)
            if planned_chapter_count <= 0:
                planned_chapter_count = int(existing_profile.get("planned_chapter_count", 0) or 0)
            if planned_chapter_count <= 0:
                planned_chapter_count = max(1, len(provided_chapter_ids))
            if outline_ids and not provided_chapter_ids:
                provided_chapter_ids = _assign_chapter_ids(
                    outline_ids=outline_ids,
                    start_index=start_index,
                    planned_chapter_count=planned_chapter_count,
                )
            if provided_chapter_ids:
                planned_chapter_count = max(planned_chapter_count, len(provided_chapter_ids))

            layer_assignment_seed = _build_layer_assignment_seed(
                raw_character,
                existing_profile,
                player_background=player_background,
                planned_chapter_count=planned_chapter_count,
                planned_chapter_ids=provided_chapter_ids,
            )
            resolved_agent_type = _resolve_story_agent_type(
                raw_character,
                existing_profile,
                layer_assignment_seed=layer_assignment_seed,
                planned_chapter_count=planned_chapter_count,
                planned_chapter_ids=provided_chapter_ids,
            )
            layer_assignment = normalize_layer_assignment(
                layer_assignment_seed,
                agent_type=resolved_agent_type,  # type: ignore[arg-type]
                fallback_reason=clean_text(layer_assignment_seed.get("assignment_reason", "")),
            )
            resolved_agent_type = _respect_agent_layer_limits(
                resolved_agent_type=resolved_agent_type,
                layer_assignment=layer_assignment,
                existing_l1_count=existing_l1_count,
                existing_l2_count=existing_l2_count,
                new_l1_count=new_l1_count,
                new_l2_count=new_l2_count,
            )
            resolved_agent_type = _respect_player_bound_capacity(
                resolved_agent_type=resolved_agent_type,
                layer_assignment=layer_assignment,
                max_total_characters=max_total_characters,
                existing_l1_count=existing_l1_count,
                existing_l2_count=existing_l2_count,
                new_l1_count=new_l1_count,
                new_l2_count=new_l2_count,
            )
            layer_assignment = normalize_layer_assignment(
                layer_assignment,
                agent_type=resolved_agent_type,  # type: ignore[arg-type]
                fallback_reason=clean_text(layer_assignment.get("assignment_reason", "")),
            )

            normalized_profile = ensure_character_profile(
                {
                    "character_id": character_id,
                    "name": name,
                    "agent_type": resolved_agent_type,
                    "story_layer": resolved_agent_type if resolved_agent_type in {"L1", "L2"} else "actor",
                    "occupation": clean_text(raw_character.get("occupation", ""))
                    or clean_text(existing_profile.get("occupation", "")),
                    "persona": persona,
                    "base_style": base_style,
                    "base_relationship": normalize_relationship_mapping(raw_character.get("base_relationship", {}))
                    or dict(existing_profile.get("base_relationship", {})),
                    "secrets": secrets,
                    "background": background,
                    "story_role": story_role,
                    "introduction_hint": clean_text(raw_character.get("introduction_hint", ""))
                    or clean_text(existing_profile.get("introduction_hint", "")),
                    "planned_chapter_count": planned_chapter_count,
                    "planned_chapter_ids": provided_chapter_ids,
                    "profile_source": "actor_create_agent",
                    "layer_assignment": layer_assignment,
                    "spiritual_root": clean_text(
                        raw_character.get("spiritual_root", ""),
                        clean_text(existing_profile.get("spiritual_root", ""), DEFAULT_SPIRITUAL_ROOT),
                    ),
                    "realm": clean_text(
                        raw_character.get("realm", ""),
                        clean_text(existing_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                    ),
                    "main_technique": clean_text(
                        raw_character.get("main_technique", ""),
                        clean_text(existing_profile.get("main_technique", ""), DEFAULT_MAIN_TECHNIQUE),
                    ),
                    **(
                        {
                            "l1_profile": normalize_l1_agent_profile(
                                raw_character.get("l1_profile", existing_profile.get("l1_profile", {})),
                                fallback_story_role=story_role,
                                fallback_persona=persona,
                                fallback_background=background,
                            )
                        }
                        if resolved_agent_type == "L1"
                        else (
                            {
                                "l2_profile": normalize_l2_agent_profile(
                                    raw_character.get("l2_profile", existing_profile.get("l2_profile", {})),
                                    fallback_story_role=story_role,
                                    fallback_persona=persona,
                                    fallback_style=base_style,
                                )
                            }
                            if resolved_agent_type == "L2"
                            else {}
                        )
                    ),
                },
                character_id=character_id,
            )

            for optional_field in ("gender", "race"):
                value = clean_text(raw_character.get(optional_field, "")) or clean_text(
                    existing_profile.get(optional_field, "")
                )
                if value:
                    normalized_profile[optional_field] = value

            normalized[character_id] = normalized_profile
            if resolved_agent_type == "L1":
                new_l1_count += 1
            elif resolved_agent_type == "L2":
                new_l2_count += 1
            used_ids.add(character_id)

        return normalized

    def normalize_contextual_actor(
        self,
        output: Mapping[str, Any] | None,
        *,
        game_state: "GameState",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
    ) -> "CharacterProfile | None":
        if not output or not isinstance(output.get("actor"), Mapping):
            return None

        normalized = self.normalize_supporting_cast(
            {"characters": [dict(output.get("actor", {}))]},
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=character_roster_snapshot,
        )
        return next(iter(normalized.values()), None) if normalized else None

    def sync_supporting_cast(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        history: list[AgentMessage] | None = None,
        max_total_characters: int = MAX_STORY_CHARACTERS,
    ) -> dict[str, "CharacterProfile"]:
        resolved_snapshots: dict[str, Any] = {}
        instruction = self.build_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            resolved_snapshots=resolved_snapshots,
        )
        result = self.command(
            instruction=instruction,
            history=history,
            response_format=ACTOR_CREATE_RESPONSE_SCHEMA,
        )
        return self.normalize_supporting_cast(
            result,
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=resolved_snapshots.get("character_roster_snapshot"),
        )

    def create_contextual_actor(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        destination: str,
        objective: str,
        reward_item: str,
        player_intent: str,
        history: list[AgentMessage] | None = None,
        max_total_characters: int = MAX_STORY_CHARACTERS,
    ) -> "CharacterProfile | None":
        resolved_snapshots: dict[str, Any] = {}
        instruction = self.build_contextual_actor_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            destination=destination,
            objective=objective,
            reward_item=reward_item,
            player_intent=player_intent,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            resolved_snapshots=resolved_snapshots,
        )
        result = self.command(
            instruction=instruction,
            history=history,
            response_format=CONTEXTUAL_ACTOR_RESPONSE_SCHEMA,
        )
        return self.normalize_contextual_actor(
            result,
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=resolved_snapshots.get("character_roster_snapshot"),
        )
