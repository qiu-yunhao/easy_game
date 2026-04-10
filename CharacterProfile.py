from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict

from CharacterMemory import CharacterMemoryConfig, normalize_character_memory_config
from StoryStateUtils import clean_str_list, clean_text


DEFAULT_SPIRITUAL_ROOT = "杂灵根"
DEFAULT_CURRENT_REALM = "练气一层"
DEFAULT_MAIN_TECHNIQUE = "基础吐纳术"


class BackpackItem(TypedDict):
    id: str
    name: str
    quantity: int


AgentType = Literal["actor", "L2", "L1"]
StoryLayer = Literal["player", "actor", "L2", "L1"]
CharacterStorageMode = Literal["player_bound_instance", "shared_template"]
LayerPlotSignificance = Literal["core", "supporting", "replaceable"]
LayerRelationshipDepth = Literal["deep", "functional", "unknown"]


class L2AgentProfile(TypedDict):
    core_drive: str
    judgement_preference: list[str]
    behavior_rule: list[str]
    speech_style: list[str]
    personality_tags: list[str]


class L1AgentProfile(TypedDict):
    core_conflict: str
    outer_goal: str
    inner_need: str
    contradiction_axes: list[str]
    relationship_pressure: list[str]


class LayerAssignment(TypedDict):
    mentioned_in_player_backstory: bool
    plot_significance: LayerPlotSignificance
    relationship_depth: LayerRelationshipDepth
    long_term_plot_significance: bool
    can_promote_to_l1: bool
    assignment_reason: str


class CharacterProfileBase(TypedDict):
    character_id: str
    name: str
    persona: list[str]
    base_style: str
    base_relationship: dict[str, float]
    secrets: list[str]
    spiritual_root: str
    realm: str
    main_technique: str
    agent_type: AgentType
    story_layer: StoryLayer
    storage_mode: CharacterStorageMode


class CharacterProfile(CharacterProfileBase, total=False):
    gender: str
    race: str
    background: str
    story_role: str
    introduction_hint: str
    planned_chapter_count: int
    planned_chapter_ids: list[str]
    profile_source: str
    occupation: str
    backpack: list[BackpackItem]
    l2_profile: L2AgentProfile
    l1_profile: L1AgentProfile
    layer_assignment: LayerAssignment
    memory_profile: CharacterMemoryConfig
    is_active: bool
    is_offstage: bool


def normalize_relationship_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}

    cleaned: dict[str, float] = {}
    for key, raw in value.items():
        character_id = clean_text(key)
        if not character_id:
            continue
        try:
            cleaned[character_id] = float(raw)
        except (TypeError, ValueError):
            continue
    return cleaned


def normalize_backpack_items(value: Any) -> list[BackpackItem]:
    if not isinstance(value, list):
        return []

    normalized: list[BackpackItem] = []
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            continue
        item_id = clean_text(raw_item.get("id"))
        name = clean_text(raw_item.get("name"))
        if not item_id or not name:
            continue
        try:
            quantity = int(raw_item.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            continue
        normalized.append(
            {
                "id": item_id,
                "name": name,
                "quantity": quantity,
            }
        )
    return normalized


def _bounded_clean_str_list(value: Any, *, limit: int) -> list[str]:
    return clean_str_list(value)[:limit]


def _normalize_plot_significance(value: Any, *, fallback: LayerPlotSignificance = "supporting") -> LayerPlotSignificance:
    resolved = clean_text(value).lower()
    if resolved in {"core", "supporting", "replaceable"}:
        return resolved  # type: ignore[return-value]
    return fallback


def _normalize_relationship_depth(value: Any, *, fallback: LayerRelationshipDepth = "unknown") -> LayerRelationshipDepth:
    resolved = clean_text(value).lower()
    if resolved in {"deep", "functional", "unknown"}:
        return resolved  # type: ignore[return-value]
    return fallback


def _resolve_agent_type(source: Mapping[str, Any]) -> AgentType:
    explicit = clean_text(source.get("agent_type", ""))
    if explicit in {"actor", "L2", "L1"}:
        return explicit  # type: ignore[return-value]
    if isinstance(source.get("l1_profile"), Mapping):
        return "L1"
    if isinstance(source.get("l2_profile"), Mapping):
        return "L2"
    if clean_text(source.get("profile_source", "")) == "actor_create_agent":
        return "L2"
    return "actor"


def _resolve_story_layer(
    source: Mapping[str, Any],
    *,
    agent_type: AgentType,
    character_id: str,
) -> StoryLayer:
    explicit = clean_text(source.get("story_layer", ""))
    if explicit in {"player", "actor", "L2", "L1"}:
        if explicit == "player":
            return "player"
        if explicit == "actor":
            return "actor"
        return explicit  # type: ignore[return-value]
    if character_id == "player":
        return "player"
    if agent_type in {"L1", "L2"}:
        return agent_type  # type: ignore[return-value]
    return "actor"


def _resolve_storage_mode(story_layer: StoryLayer) -> CharacterStorageMode:
    return "shared_template" if story_layer == "actor" else "player_bound_instance"


def normalize_layer_assignment(
    value: Any,
    *,
    agent_type: AgentType = "actor",
    fallback_reason: str = "",
) -> LayerAssignment:
    source = value if isinstance(value, Mapping) else {}
    mentioned_in_player_backstory = bool(source.get("mentioned_in_player_backstory", False))
    plot_significance = _normalize_plot_significance(
        source.get("plot_significance"),
        fallback="core" if agent_type == "L1" else "supporting",
    )
    relationship_depth = _normalize_relationship_depth(
        source.get("relationship_depth"),
        fallback="deep" if agent_type == "L1" else "unknown",
    )
    long_term_plot_significance = bool(source.get("long_term_plot_significance", agent_type == "L1"))
    can_promote_to_l1 = bool(source.get("can_promote_to_l1", False))
    assignment_reason = clean_text(source.get("assignment_reason", ""), fallback_reason)

    if mentioned_in_player_backstory and plot_significance == "replaceable":
        plot_significance = "supporting"
    if mentioned_in_player_backstory and relationship_depth == "unknown":
        relationship_depth = "functional"
    if agent_type == "L1":
        plot_significance = "core"
        long_term_plot_significance = True
        can_promote_to_l1 = False

    return {
        "mentioned_in_player_backstory": mentioned_in_player_backstory,
        "plot_significance": plot_significance,
        "relationship_depth": relationship_depth,
        "long_term_plot_significance": long_term_plot_significance,
        "can_promote_to_l1": can_promote_to_l1,
        "assignment_reason": assignment_reason,
    }


def normalize_l2_agent_profile(
    value: Any,
    *,
    fallback_story_role: str = "",
    fallback_persona: list[str] | None = None,
    fallback_style: str = "",
) -> L2AgentProfile:
    source = value if isinstance(value, Mapping) else {}
    fallback_persona = list(fallback_persona or [])
    personality_tags = _bounded_clean_str_list(
        source.get("personality_tags", fallback_persona),
        limit=4,
    ) or fallback_persona[:2] or ["谨慎", "务实"]
    judgement_preference = _bounded_clean_str_list(
        source.get("judgement_preference", []),
        limit=2,
    ) or personality_tags[:1] or ["先看局势"]
    behavior_rule = _bounded_clean_str_list(
        source.get("behavior_rule", []),
        limit=2,
    ) or ["优先自保", "再考虑如何支撑局势"]
    speech_style = _bounded_clean_str_list(
        source.get("speech_style", []),
        limit=2,
    )
    if not speech_style:
        fallback_speech_style = clean_text(fallback_style)
        speech_style = [fallback_speech_style] if fallback_speech_style else ["简洁克制"]

    core_drive = clean_text(source.get("core_drive", ""))
    if not core_drive:
        core_drive = f"围绕“{fallback_story_role}”维持自己在局中的位置" if fallback_story_role else "先稳住自己在局中的位置"

    return {
        "core_drive": core_drive,
        "judgement_preference": judgement_preference,
        "behavior_rule": behavior_rule,
        "speech_style": speech_style,
        "personality_tags": personality_tags,
    }


def normalize_l1_agent_profile(
    value: Any,
    *,
    fallback_story_role: str = "",
    fallback_persona: list[str] | None = None,
    fallback_background: str = "",
) -> L1AgentProfile:
    source = value if isinstance(value, Mapping) else {}
    fallback_persona = list(fallback_persona or [])
    contradiction_axes = _bounded_clean_str_list(source.get("contradiction_axes", []), limit=4)
    if not contradiction_axes and len(fallback_persona) >= 2:
        contradiction_axes = [f"{fallback_persona[0]} / {fallback_persona[1]}"]

    relationship_pressure = _bounded_clean_str_list(source.get("relationship_pressure", []), limit=4)
    if not relationship_pressure and fallback_story_role:
        relationship_pressure = [f"与玩家围绕{fallback_story_role}的关系变化会持续施压"]

    core_conflict = clean_text(source.get("core_conflict", ""))
    if not core_conflict:
        core_conflict = (
            f"在{fallback_story_role}的立场与真实本心之间摇摆"
            if fallback_story_role
            else "在执念、责任与真实本心之间摇摆"
        )

    outer_goal = clean_text(source.get("outer_goal", ""))
    if not outer_goal:
        outer_goal = fallback_story_role or "推动这条主线走向自己想要的结果"

    inner_need = clean_text(source.get("inner_need", ""))
    if not inner_need:
        inner_need = (
            f"穿过{fallback_background[:24]}背后的执念，看清自己真正想守住的东西"
            if fallback_background
            else "在局势与关系压迫下看清自己真正想守住的东西"
        )

    return {
        "core_conflict": core_conflict,
        "outer_goal": outer_goal,
        "inner_need": inner_need,
        "contradiction_axes": contradiction_axes,
        "relationship_pressure": relationship_pressure,
    }


def ensure_character_profile(
    profile: Mapping[str, Any] | None,
    *,
    character_id: str = "",
    include_backpack: bool = False,
) -> CharacterProfile:
    source = profile or {}
    resolved_character_id = clean_text(source.get("character_id"), character_id)
    resolved_name = clean_text(source.get("name"), resolved_character_id)
    resolved_agent_type = _resolve_agent_type(source)
    resolved_story_layer = _resolve_story_layer(
        source,
        agent_type=resolved_agent_type,
        character_id=resolved_character_id,
    )
    resolved_persona = clean_str_list(source.get("persona", []))
    resolved_base_style = clean_text(source.get("base_style"))
    resolved_story_role = clean_text(source.get("story_role", ""))

    normalized: CharacterProfile = {
        "character_id": resolved_character_id,
        "name": resolved_name,
        "persona": resolved_persona,
        "base_style": resolved_base_style,
        "base_relationship": normalize_relationship_mapping(source.get("base_relationship", {})),
        "secrets": clean_str_list(source.get("secrets", [])),
        "spiritual_root": clean_text(
            source.get("spiritual_root"),
            DEFAULT_SPIRITUAL_ROOT,
        ),
        "realm": clean_text(source.get("realm"), DEFAULT_CURRENT_REALM),
        "main_technique": clean_text(
            source.get("main_technique"),
            DEFAULT_MAIN_TECHNIQUE,
        ),
        "agent_type": resolved_agent_type,
        "story_layer": resolved_story_layer,
        "storage_mode": _resolve_storage_mode(resolved_story_layer),
    }

    for field in (
        "gender",
        "race",
        "background",
        "story_role",
        "introduction_hint",
        "profile_source",
        "occupation",
    ):
        if field in source:
            normalized[field] = clean_text(source.get(field))

    normalized["is_active"] = bool(source.get("is_active", True))
    normalized["is_offstage"] = bool(source.get("is_offstage", False))

    if "planned_chapter_count" in source:
        try:
            normalized["planned_chapter_count"] = int(source.get("planned_chapter_count", 0) or 0)
        except (TypeError, ValueError):
            normalized["planned_chapter_count"] = 0

    if "planned_chapter_ids" in source:
        normalized["planned_chapter_ids"] = clean_str_list(source.get("planned_chapter_ids", []))

    if include_backpack or "backpack" in source:
        normalized["backpack"] = normalize_backpack_items(source.get("backpack", []))

    normalized["layer_assignment"] = normalize_layer_assignment(
        source.get("layer_assignment", {}),
        agent_type=resolved_agent_type,
        fallback_reason=(
            "player background priority"
            if clean_text(source.get("profile_source", "")) == "player_background"
            else ""
        ),
    )
    normalized["memory_profile"] = normalize_character_memory_config(
        source.get("memory_profile", {}),
        agent_type=resolved_agent_type,
    )

    if resolved_agent_type == "L2":
        normalized["l2_profile"] = normalize_l2_agent_profile(
            source.get("l2_profile", {}),
            fallback_story_role=resolved_story_role,
            fallback_persona=resolved_persona,
            fallback_style=resolved_base_style,
        )
    elif "l2_profile" in source:
        normalized["l2_profile"] = normalize_l2_agent_profile(
            source.get("l2_profile", {}),
            fallback_story_role=resolved_story_role,
            fallback_persona=resolved_persona,
            fallback_style=resolved_base_style,
        )

    if resolved_agent_type == "L1" or "l1_profile" in source:
        normalized["l1_profile"] = normalize_l1_agent_profile(
            source.get("l1_profile", {}),
            fallback_story_role=resolved_story_role,
            fallback_persona=resolved_persona,
            fallback_background=clean_text(source.get("background", "")),
        )

    return normalized


def ensure_character_profiles(
    profiles: Mapping[str, Mapping[str, Any]] | None,
    *,
    player_character_id: str | None = None,
) -> dict[str, CharacterProfile]:
    normalized: dict[str, CharacterProfile] = {}
    for character_id, profile in (profiles or {}).items():
        include_backpack = player_character_id is not None and character_id == player_character_id
        normalized[character_id] = ensure_character_profile(
            profile,
            character_id=character_id,
            include_backpack=include_backpack,
        )
    return normalized


def promote_character_profile_to_l1(
    profile: Mapping[str, Any] | None,
    *,
    character_id: str = "",
    assignment_reason: str = "",
) -> CharacterProfile:
    source = dict(profile or {})
    existing_assignment = source.get("layer_assignment", {})
    source["agent_type"] = "L1"
    source["layer_assignment"] = {
        **(existing_assignment if isinstance(existing_assignment, Mapping) else {}),
        "plot_significance": "core",
        "relationship_depth": "deep",
        "long_term_plot_significance": True,
        "can_promote_to_l1": False,
        "assignment_reason": clean_text(
            assignment_reason,
            clean_text(
                (existing_assignment or {}).get("assignment_reason", "")
                if isinstance(existing_assignment, Mapping)
                else "",
                "promoted_to_l1",
            ),
        ),
    }
    return ensure_character_profile(
        source,
        character_id=character_id or clean_text(source.get("character_id", "")),
        include_backpack="backpack" in source,
    )
