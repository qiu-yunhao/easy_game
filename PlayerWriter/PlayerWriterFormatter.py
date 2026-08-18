from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from StoryStateUtils import (
    clean_str_list,
    clean_text,
    current_outline_entry,
    resolve_player_profile,
    serialize_story_cast_member,
    story_outline_entries,
)
from Cultivation import (
    build_chapter_transition_requirement,
    chapter_realm_sequence,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
)
from GameState import SceneCandidate
from PromptUtils import render_json_instruction
from ScenePlan import ScenePlan, empty_scene_plan
from StoryToolContext import build_story_tool_prompt_context

if TYPE_CHECKING:
    from CharacterRosterTools import CharacterRosterToolRuntime
    from CharacterProfile import CharacterProfile
    from GameState import GameState
    from SceneConfig import SceneConfig


_clean_text = clean_text
_clean_list = clean_str_list
_resolve_player_profile = resolve_player_profile
_resolve_current_outline_chapter = current_outline_entry


def _split_chapter_id(chapter_id: str) -> tuple[str, int]:
    match = re.match(r"^(.*?)-(\d+)$", chapter_id.strip())
    if not match:
        return chapter_id.strip() or "chapter", 1
    return match.group(1), int(match.group(2))


def _build_outline_fallback_ids(
    game_state: "GameState",
    *,
    desired_chapter_count: int,
) -> list[str]:
    existing_outline = story_outline_entries(game_state)
    if existing_outline:
        last_chapter_id = _clean_text(existing_outline[-1].get("chapter_id"))
        start_offset = 1
    else:
        last_chapter_id = _clean_text(game_state["plot"].get("chapter_id")) or "chapter-qinglan-1"
        start_offset = 0

    prefix, current_number = _split_chapter_id(last_chapter_id)
    if not existing_outline and not re.search(r"-\d+$", last_chapter_id):
        current_number = 0

    return [
        f"{prefix}-{current_number + start_offset + index}"
        for index in range(desired_chapter_count)
    ]


def _resolve_outline_realm_start(
    game_state: "GameState",
    character_profiles: dict[str, "CharacterProfile"],
) -> str:
    existing_outline = story_outline_entries(game_state)
    if existing_outline:
        last_outline = existing_outline[-1]
        return _clean_text(last_outline.get("next_realm")) or next_major_realm(
            _clean_text(last_outline.get("realm_stage"))
        )
    player_id, player_profile = _resolve_player_profile(game_state, character_profiles)
    _ = player_id
    return normalize_major_realm(player_profile.get("realm", ""))


def _serialize_completed_chapters(
    game_state: "GameState",
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    completed = list(game_state["plot"].get("completed_chapters", []))
    if limit > 0:
        completed = completed[-limit:]
    return [
        {
            "chapter_id": _clean_text(chapter.get("chapter_id")),
            "title": _clean_text(chapter.get("title")),
            "goal": _clean_text(chapter.get("goal")),
            "overview": _clean_text(chapter.get("overview")),
            "summary": _clean_text(chapter.get("summary")),
            "key_events": _clean_list(chapter.get("key_events")),
            "revealed_facts": _clean_list(chapter.get("revealed_facts")),
            "open_loops": _clean_list(chapter.get("open_loops")),
            "completed_turn": int(chapter.get("completed_turn", 0) or 0),
        }
        for chapter in completed
    ]


def _serialize_cast(
    game_state: "GameState",
    character_profiles: dict[str, "CharacterProfile"],
    *,
    player_id: str,
) -> list[dict[str, Any]]:
    current_chapter_id = _clean_text(game_state["plot"].get("chapter_id"))
    default_on_stage = [
        _clean_text(actor_id)
        for actor_id in game_state["scene"].get("on_stage", [])
        if _clean_text(actor_id)
    ]
    serialized: list[dict[str, Any]] = []
    for character_id, profile in character_profiles.items():
        serialized_profile = serialize_story_cast_member(character_id, profile)
        planned_chapter_ids = list(serialized_profile["planned_chapter_ids"])
        serialized.append(
            {
                **serialized_profile,
                "role_hint": (
                    "player"
                    if character_id == player_id
                    else "default opening/support"
                    if character_id in default_on_stage
                    else "supporting cast"
                ),
                "planned_chapter_ids": planned_chapter_ids,
                "in_current_chapter": current_chapter_id in planned_chapter_ids
                or character_id in default_on_stage,
                "introduction_hint": _clean_text(profile.get("introduction_hint", "")),
            }
        )
    return serialized[:20]


def _resolve_chapter_cast_ids(
    game_state: "GameState",
    character_profiles: dict[str, "CharacterProfile"],
    *,
    player_id: str,
) -> list[str]:
    chapter_id = _clean_text(game_state["plot"].get("chapter_id"))
    chapter_cast = [
        _clean_text(actor_id)
        for actor_id in game_state["scene"].get("on_stage", [])
        if _clean_text(actor_id)
    ]
    if player_id and player_id in character_profiles and player_id not in chapter_cast:
        chapter_cast.insert(0, player_id)
    for character_id, profile in character_profiles.items():
        planned_chapter_ids = _clean_list(profile.get("planned_chapter_ids", []))
        if chapter_id and chapter_id in planned_chapter_ids and character_id not in chapter_cast:
            chapter_cast.append(character_id)
    return chapter_cast[:8]


class PlaywrightFormatter:
    def _normalize_outline_brief_entry(
        self,
        chapter: Mapping[str, Any] | None,
        fallback_id: str,
        *,
        realm_stage: str,
        next_realm: str,
    ) -> dict[str, Any]:
        data = chapter or {}
        chapter_id = _clean_text(data.get("chapter_id")) or fallback_id
        title = _clean_text(data.get("title")) or f"{realm_stage}篇"
        main_goal = _clean_text(data.get("main_goal"))
        summary = _clean_text(data.get("summary")) or main_goal
        return {
            "chapter_id": chapter_id,
            "title": title,
            "main_goal": main_goal,
            "summary": summary,
            "exploration_hooks": [],
            "key_locations": [],
            "realm_stage": realm_stage,
            "next_realm": next_realm,
        }

    def _normalize_scene_candidate(
        self,
        candidate: Mapping[str, Any] | None,
        *,
        on_stage: list[str],
        fallback_location: str,
        index: int,
    ) -> SceneCandidate:
        data = candidate or {}
        candidate_id = _clean_text(data.get("candidate_id")) or f"candidate-{index + 1}"
        label = _clean_text(data.get("label")) or f"Scene Candidate {index + 1}"
        location_id = _clean_text(data.get("location_id")) or fallback_location
        beat = _clean_text(data.get("beat")) or label
        scene_goal = _clean_text(data.get("scene_goal"))
        must_happen = _clean_list(data.get("must_happen"))
        must_not_happen = _clean_list(data.get("must_not_happen"))
        dramatic_curve = _clean_list(data.get("dramatic_curve"))
        exit_condition = _clean_text(data.get("exit_condition"))
        notes = _clean_list(data.get("notes"))
        character_objectives = {
            str(cid): str(goal).strip()
            for cid, goal in (data.get("character_objectives") or {}).items()
            if str(cid) in on_stage and str(goal).strip()
        }
        return {
            "candidate_id": candidate_id,
            "label": label,
            "location_id": location_id,
            "beat": beat,
            "scene_goal": scene_goal,
            "must_happen": must_happen,
            "must_not_happen": must_not_happen,
            "dramatic_curve": dramatic_curve,
            "character_objectives": character_objectives,
            "exit_condition": exit_condition,
            "notes": notes,
        }

    def normalize_story_premise(
        self,
        output: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        return {
            "story_premise": _clean_text(output.get("story_premise") if output else ""),
            "exploration_drive": _clean_text(output.get("exploration_drive") if output else ""),
        }

    def build_story_premise_instruction(
        self,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
    ) -> str:
        player_id, player_profile = _resolve_player_profile(game_state, character_profiles)
        cast = _serialize_cast(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        payload = {
            "creative_goal": (
                "Define an open-world xianxia story premise centered on cultivation and longevity. "
                "The story should feel open at the start, without a fixed investigation-style mainline."
            ),
            "fixed_global_goal": "修仙求长生",
            "player_character_id": player_id,
            "player_profile": {
                "name": player_profile.get("name", player_id),
                "gender": player_profile.get("gender", ""),
                "race": player_profile.get("race", ""),
                "background": player_profile.get("background", ""),
                "spiritual_root": player_profile.get("spiritual_root", ""),
                "realm": player_profile.get("realm", ""),
            },
            "opening_scene_seed": {
                "chapter_id": game_state["plot"]["chapter_id"],
                "scene_id": game_state["plot"]["scene_id"],
                "location_id": game_state["scene"]["location_id"],
                "time_tag": game_state["scene"]["time_tag"],
            },
            "scene_config": scene_config,
            **build_story_tool_prompt_context(
                task="story_premise",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                cast_size=len(cast),
                supporting_cast_count=sum(1 for member in cast if member.get("role_hint") != "player"),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "cast": cast,
        }
        return render_json_instruction(
            "Create the story premise and exploration drive as strict JSON. "
            "Keep both fields concrete, concise, and open-world in feel. "
            "Do not frame the opening around a fixed hidden truth, interrogation, or single predetermined quest. "
            "Use player-specified supporting characters when they already exist, but do not generate the chapter outline yet.",
            payload,
        )

    def normalize_story_outline_brief(
        self,
        output: Mapping[str, Any] | None,
        game_state: "GameState",
        desired_chapter_count: int,
        character_profiles: dict[str, "CharacterProfile"] | None = None,
    ) -> list[dict[str, Any]]:
        outline: list[dict[str, Any]] = []
        fallback_ids = _build_outline_fallback_ids(
            game_state,
            desired_chapter_count=desired_chapter_count,
        )
        resolved_profiles = character_profiles or {}
        starting_realm = _resolve_outline_realm_start(game_state, resolved_profiles)
        realm_pairs = chapter_realm_sequence(starting_realm, desired_chapter_count)
        for index, chapter in enumerate(output.get("story_outline", []) if output else [], start=1):
            fallback_id = fallback_ids[index - 1] if index - 1 < len(fallback_ids) else fallback_ids[-1]
            realm_stage, next_realm = realm_pairs[index - 1] if index - 1 < len(realm_pairs) else realm_pairs[-1]
            outline.append(
                self._normalize_outline_brief_entry(
                    chapter,
                    fallback_id,
                    realm_stage=realm_stage,
                    next_realm=next_realm,
                )
            )
        return outline

    def build_story_outline_brief_instruction(
        self,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        desired_chapter_count: int,
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
    ) -> str:
        player_id, player_profile = _resolve_player_profile(game_state, character_profiles)
        cast = _serialize_cast(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        current_chapter_cast = _resolve_chapter_cast_ids(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        starting_realm = _resolve_outline_realm_start(game_state, character_profiles)
        planned_realm_sequence = [
            {"realm_stage": realm_stage, "next_realm": next_realm}
            for realm_stage, next_realm in chapter_realm_sequence(starting_realm, desired_chapter_count)
        ]
        existing_outline = [
            {
                "chapter_id": _clean_text(chapter.get("chapter_id")),
                "title": _clean_text(chapter.get("title")),
                "main_goal": _clean_text(chapter.get("main_goal")),
                "summary": _clean_text(chapter.get("summary")),
                "realm_stage": _clean_text(chapter.get("realm_stage")),
                "next_realm": _clean_text(chapter.get("next_realm")),
            }
            for chapter in story_outline_entries(game_state)
        ]
        frontier_chapter = existing_outline[-1] if existing_outline else {
            "chapter_id": game_state["plot"]["chapter_id"],
            "title": "",
            "main_goal": "",
            "summary": "",
        }
        payload = {
            "creative_goal": (
                "Generate the next short batch of future chapter slots for a rolling xianxia outline. "
                "Each chapter corresponds to exactly one major cultivation realm and should define only its title, main goal, and concise summary."
            ),
            "fixed_global_goal": "修仙求长生",
            "desired_chapter_count": desired_chapter_count,
            "player_character_id": player_id,
            "player_profile": {
                "name": player_profile.get("name", player_id),
                "race": player_profile.get("race", ""),
                "background": player_profile.get("background", ""),
                "spiritual_root": player_profile.get("spiritual_root", ""),
                "realm": normalize_realm_text(player_profile.get("realm", "")),
            },
            **build_story_tool_prompt_context(
                task="story_outline",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                cast_size=len(cast),
                supporting_cast_count=sum(1 for member in cast if member.get("role_hint") != "player"),
                current_chapter_cast_count=len(current_chapter_cast),
                outline_exists=bool(existing_outline),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "planned_realm_sequence": planned_realm_sequence,
            "cast": cast,
            "current_chapter_cast": current_chapter_cast,
            "story_premise": game_state["plot"].get("story_premise", ""),
            "exploration_drive": game_state["plot"].get("exploration_drive", ""),
            "existing_outline": existing_outline[-4:],
            "completed_chapters": _serialize_completed_chapters(game_state),
            "frontier": {
                "current_chapter_id": game_state["plot"]["chapter_id"],
                "current_chapter_index": int(game_state["plot"].get("current_chapter_index", 0) or 0),
                "last_outlined_chapter": frontier_chapter,
                "opening_location_id": scene_config.get(
                    "default_location_id",
                    game_state["scene"]["location_id"],
                ),
            },
        }
        return render_json_instruction(
            "Produce the next batch of brief story outline entries as strict JSON. "
            f"Return exactly {desired_chapter_count} future chapters that come after the already planned outline. "
            "Keep each summary to 1-2 sentences. Do not repeat existing chapters. "
            "The story's only stable long-term objective is immortality through cultivation, and each chapter must feel open-ended in how that progress is achieved. "
            "Respect player-specified supporting characters when they exist. "
            "If some supporting characters have not been assigned to chapters yet, you may decide how many chapters they should materially influence. "
            "Do not expand hooks or locations yet.",
            payload,
        )

    def normalize_chapter_expansion(
        self,
        output: Mapping[str, Any] | None,
        default_title: str,
        default_goal: str,
        default_overview: str,
    ) -> dict[str, Any]:
        return {
            "chapter_title": _clean_text(output.get("chapter_title") if output else "") or default_title,
            "chapter_goal": _clean_text(output.get("chapter_goal") if output else "") or default_goal,
            "chapter_overview": _clean_text(output.get("chapter_overview") if output else "") or default_overview,
            "exploration_hooks": _clean_list(output.get("exploration_hooks") if output else []),
            "key_locations": _clean_list(output.get("key_locations") if output else []),
        }

    def build_chapter_expansion_instruction(
        self,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
        template_guidance: str = "",
    ) -> str:
        player_id, player_profile = _resolve_player_profile(game_state, character_profiles)
        current_outline = _resolve_current_outline_chapter(game_state)
        chapter_realm = _clean_text(
            current_outline.get("realm_stage"),
        ) or _clean_text(game_state["plot"].get("current_chapter_realm", ""))
        next_realm = _clean_text(
            current_outline.get("next_realm"),
        ) or _clean_text(game_state["plot"].get("next_chapter_realm", ""))
        cast = _serialize_cast(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        current_chapter_cast = _resolve_chapter_cast_ids(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        payload = {
            "creative_goal": (
                "Expand only the current chapter slot into a concrete chapter goal, overview, hooks, "
                "and key locations. Preserve continuity with completed chapters while keeping the route to progression open-ended."
            ),
            "fixed_global_goal": "修仙求长生",
            "player_character_id": player_id,
            "player_profile": {
                "name": player_profile.get("name", player_id),
                "race": player_profile.get("race", ""),
                "background": player_profile.get("background", ""),
                "spiritual_root": player_profile.get("spiritual_root", ""),
                "realm": normalize_realm_text(player_profile.get("realm", "")),
            },
            **build_story_tool_prompt_context(
                task="chapter_expansion",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                cast_size=len(cast),
                supporting_cast_count=sum(1 for member in cast if member.get("role_hint") != "player"),
                current_chapter_cast_count=len(current_chapter_cast),
                outline_exists=bool(current_outline),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "cast": cast,
            "current_chapter_cast": current_chapter_cast,
            "plot": {
                "chapter_id": game_state["plot"]["chapter_id"],
                "current_chapter_index": int(game_state["plot"].get("current_chapter_index", 0) or 0),
                "current_chapter_realm": chapter_realm,
                "next_chapter_realm": next_realm,
                "chapter_transition_requirement": build_chapter_transition_requirement(
                    chapter_realm,
                    next_realm,
                ),
                "story_premise": game_state["plot"].get("story_premise", ""),
                "exploration_drive": game_state["plot"].get("exploration_drive", ""),
                "current_outline_chapter": current_outline,
                "completed_chapters": _serialize_completed_chapters(game_state),
            },
            "opening_scene": {
                "location_id": game_state["scene"]["location_id"],
                "time_tag": game_state["scene"]["time_tag"],
                "beat": game_state["scene"]["beat"],
            },
            "scene_config": scene_config,
        }
        if template_guidance:
            payload["reference_skeleton"] = template_guidance
        return render_json_instruction(
            "Expand the current chapter as strict JSON. "
            "Keep the chapter overview concise, use the chapter cast when relevant, and return 2-4 exploration hooks plus 2-4 key locations. "
            "The chapter should feel like one cultivation realm's worth of open-ended growth, not a single mandatory questline.",
            payload,
        )

    def normalize_scene_candidates(
        self,
        output: Mapping[str, Any] | None,
        on_stage: list[str],
        fallback_location: str,
    ) -> list[SceneCandidate]:
        candidates = output.get("candidates", []) if output else []
        return [
            self._normalize_scene_candidate(
                candidate,
                on_stage=on_stage,
                fallback_location=fallback_location,
                index=index,
            )
            for index, candidate in enumerate(candidates)
            if isinstance(candidate, Mapping)
        ]

    def build_scene_candidates_instruction(
        self,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
        template_guidance: str = "",
    ) -> str:
        current_outline_chapter = _resolve_current_outline_chapter(game_state)
        completed_chapters = _serialize_completed_chapters(game_state)
        player_id, _ = _resolve_player_profile(game_state, character_profiles)
        cast = _serialize_cast(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        current_chapter_cast = _resolve_chapter_cast_ids(
            game_state,
            character_profiles,
            player_id=player_id,
        )
        character_blocks = []
        for cid in game_state["scene"]["on_stage"]:
            profile = character_profiles.get(cid, {})
            runtime = game_state["characters"].get(cid, {})
            character_blocks.append(
                {
                    "character_id": cid,
                    "name": profile.get("name", cid),
                    "persona": profile.get("persona", []),
                    "intent": runtime.get("intent", ""),
                    "emotion": runtime.get("emotion", {}),
                }
            )

        payload = {
            "creative_goal": (
                "Generate 2-3 scene candidates for the current moment. "
                "Each candidate should be a playable next scene that advances the current chapter's cultivation progress."
            ),
            "fixed_global_goal": "修仙求长生",
            "plot": {
                "chapter_id": game_state["plot"]["chapter_id"],
                "scene_id": game_state["plot"]["scene_id"],
                "current_scene_index": int(game_state["plot"].get("current_scene_index", 0) or 0),
                "chapter_goal": game_state["plot"].get("chapter_goal", ""),
                "current_chapter_realm": game_state["plot"].get("current_chapter_realm", ""),
                "next_chapter_realm": game_state["plot"].get("next_chapter_realm", ""),
                "chapter_transition_requirement": game_state["plot"].get(
                    "chapter_transition_requirement",
                    "",
                ),
                "current_chapter_title": game_state["plot"].get("current_chapter_title", ""),
                "current_chapter_overview": game_state["plot"].get("current_chapter_overview", ""),
                "current_chapter_hooks": game_state["plot"].get("current_chapter_hooks", []),
                "current_outline_chapter": current_outline_chapter,
                "story_premise": game_state["plot"].get("story_premise", ""),
                "exploration_drive": game_state["plot"].get("exploration_drive", ""),
                "completed_chapters": completed_chapters,
                "plot_flags": game_state["plot"].get("plot_flags", {}),
            },
            **build_story_tool_prompt_context(
                task="scene_candidates",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                cast_size=len(cast),
                supporting_cast_count=sum(1 for member in cast if member.get("role_hint") != "player"),
                current_chapter_cast_count=len(current_chapter_cast),
                on_stage_count=len(game_state["scene"]["on_stage"]),
                outline_exists=bool(current_outline_chapter),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(completed_chapters),
            ),
            "cast": cast,
            "current_chapter_cast": current_chapter_cast,
            "scene": {
                "location_id": game_state["scene"]["location_id"],
                "time_tag": game_state["scene"]["time_tag"],
                "beat": game_state["scene"]["beat"],
                "tension": game_state["scene"]["tension"],
                "on_stage": game_state["scene"]["on_stage"],
                "allow_interrupt": game_state["scene"]["allow_interrupt"],
            },
            "scene_config": scene_config,
            "playwright_memory": game_state["memory"]["playwright_memory"],
            "characters_on_stage": character_blocks,
            "recent_history": game_state["history"][-4:],
        }
        if template_guidance:
            payload["reference_beats"] = template_guidance
        return render_json_instruction(
            "Generate scene candidates as strict JSON. "
            "Return 2 or 3 concise candidates. Each candidate should define a concrete location, beat, "
            "scene goal, constraints, and exit condition. Keep the active scene playable with the current on-stage cast, "
            "while staying aware of the broader chapter cast. Favor open-world cultivation choices over single-solution plot rails. Do not write dialogue.",
            payload,
        )

    def scene_candidate_to_plan(
        self,
        candidate: Mapping[str, Any] | None,
    ) -> ScenePlan:
        if not candidate:
            return empty_scene_plan()
        return {
            "scene_goal": _clean_text(candidate.get("scene_goal")),
            "must_happen": _clean_list(candidate.get("must_happen")),
            "must_not_happen": _clean_list(candidate.get("must_not_happen")),
            "dramatic_curve": _clean_list(candidate.get("dramatic_curve")),
            "character_objectives": {
                str(cid): str(goal).strip()
                for cid, goal in (candidate.get("character_objectives") or {}).items()
                if str(goal).strip()
            },
            "exit_condition": _clean_text(candidate.get("exit_condition")),
            "notes": _clean_list(candidate.get("notes")),
        }
