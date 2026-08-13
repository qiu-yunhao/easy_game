from __future__ import annotations

import json
from typing import TYPE_CHECKING

from CharacterProfile import CharacterProfile, ensure_character_profile
from GameState import GameState, create_character_runtime_state
from StoryStateUtils import serialize_story_cast_member
from Actor.ActorCreateAgent import ActorCreateAgent, MAX_STORY_CHARACTERS

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def _dedupe_character_ids(character_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    for character_id in character_ids:
        resolved = str(character_id or "").strip()
        if resolved and resolved not in deduped:
            deduped.append(resolved)
    return deduped


def _build_story_cast_signature(state: GameState, deps: "GraphDependencies") -> str:
    player_actor = str(state["player"].get("controlled_character", "") or "").strip()
    player_background = str(
        deps.character_profiles.get(player_actor, {}).get("background", "")
        or deps.character_profiles.get("player", {}).get("background", "")
        or ""
    ).strip()
    outline = [
        {
            "chapter_id": str(chapter.get("chapter_id", "") or "").strip(),
            "title": str(chapter.get("title", "") or "").strip(),
            "main_goal": str(chapter.get("main_goal", "") or "").strip(),
            "summary": str(chapter.get("summary", "") or "").strip(),
        }
        for chapter in state["plot"].get("story_outline", [])
        if isinstance(chapter, dict)
    ]
    supplemental_cast = [
        {
            key: serialized_profile[key]
            for key in ("character_id", "name", "story_role", "planned_chapter_ids")
        }
        for character_id, profile in deps.character_profiles.items()
        if str(profile.get("profile_source", "") or "").strip() == "actor_create_agent"
        for serialized_profile in [serialize_story_cast_member(character_id, profile)]
    ]
    return json.dumps(
        {
            "story_premise": str(state["plot"].get("story_premise", "") or "").strip(),
            "exploration_drive": str(state["plot"].get("exploration_drive", "") or "").strip(),
            "player_background": player_background,
            "outline": outline,
            "supplemental_cast": supplemental_cast,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _merge_story_cast(
    state: GameState,
    deps: "GraphDependencies",
    supplemental_profiles: dict[str, CharacterProfile],
) -> GameState:
    if not supplemental_profiles:
        return state

    merged_profiles = dict(deps.character_profiles)
    for character_id, profile in supplemental_profiles.items():
        existing_profile = merged_profiles.get(character_id, {})
        merged_profiles[character_id] = ensure_character_profile(
            {
                **existing_profile,
                **profile,
                "base_relationship": {
                    **dict(existing_profile.get("base_relationship", {})),
                    **dict(profile.get("base_relationship", {})),
                },
                "persona": list(profile.get("persona", [])) or list(existing_profile.get("persona", [])),
                "secrets": list(profile.get("secrets", [])) or list(existing_profile.get("secrets", [])),
            },
            character_id=character_id,
            include_backpack="backpack" in profile or "backpack" in existing_profile,
        )

    deps.character_profiles.clear()
    deps.character_profiles.update(dict(list(merged_profiles.items())[:MAX_STORY_CHARACTERS]))

    next_characters = dict(state["characters"])
    for character_id, profile in deps.character_profiles.items():
        if character_id not in next_characters:
            next_characters[character_id] = create_character_runtime_state(
                intent=str(profile.get("introduction_hint", "") or profile.get("story_role", "") or "").strip()
            )
    return {
        **state,
        "characters": next_characters,
    }


def _ensure_story_cast(
    state: GameState,
    deps: "GraphDependencies",
    actor_create_agent: ActorCreateAgent | None,
) -> GameState:
    signature = _build_story_cast_signature(state, deps)
    if signature == deps.actor_create_signature:
        return state
    if actor_create_agent is None:
        deps.actor_create_signature = signature
        return state
    try:
        supplemental_profiles = actor_create_agent.sync_supporting_cast(
            game_state=state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
            max_total_characters=MAX_STORY_CHARACTERS,
        )
    except (RuntimeError, ValueError):
        deps.actor_create_signature = signature
        return state
    next_state = _merge_story_cast(state, deps, supplemental_profiles)
    deps.actor_create_signature = _build_story_cast_signature(next_state, deps)
    return next_state


def _resolve_default_on_stage(
    state: GameState,
    deps: "GraphDependencies",
    *,
    chapter_id: str | None = None,
) -> list[str]:
    target_chapter_id = str(chapter_id or state["plot"].get("chapter_id", "") or "").strip()
    seeded_on_stage = _dedupe_character_ids(
        [
            str(actor_id).strip()
            for actor_id in deps.scene_config.get("default_on_stage", state["scene"].get("on_stage", []))
            if str(actor_id).strip() and str(actor_id).strip() in deps.character_profiles
        ]
    )
    for character_id, profile in deps.character_profiles.items():
        planned_chapter_ids = [str(item).strip() for item in profile.get("planned_chapter_ids", []) if str(item).strip()]
        if target_chapter_id and target_chapter_id in planned_chapter_ids and character_id not in seeded_on_stage:
            seeded_on_stage.append(character_id)

    player_actor = str(state["player"].get("controlled_character", "") or "").strip()
    if player_actor and player_actor in deps.character_profiles and player_actor not in seeded_on_stage:
        seeded_on_stage.insert(0, player_actor)

    fallback = _dedupe_character_ids(
        [str(actor_id).strip() for actor_id in state["scene"].get("on_stage", []) if str(actor_id).strip()]
    )
    return (seeded_on_stage or fallback)[:4]


def _seed_scene_cast_for_current_chapter(state: GameState, deps: "GraphDependencies") -> GameState:
    if str(state["plot"].get("scene_candidates_source", "") or "").strip() == "contextual_handoff":
        return state

    desired_on_stage = _resolve_default_on_stage(state, deps)
    if not desired_on_stage:
        return state

    current_suppressed = [
        actor_id for actor_id in state["scene"].get("suppressed", []) if actor_id in desired_on_stage
    ]
    current_focus = state["scene"].get("focus_character")
    if current_focus not in desired_on_stage:
        player_actor = state["player"].get("controlled_character")
        current_focus = player_actor if player_actor in desired_on_stage else desired_on_stage[0]

    return {
        **state,
        "scene": {
            **state["scene"],
            "on_stage": desired_on_stage,
            "suppressed": current_suppressed,
            "focus_character": current_focus,
        },
        "runtime": {
            **state["runtime"],
            "eligible_actors": desired_on_stage,
        },
    }
