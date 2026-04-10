from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent
from CharacterProfile import CharacterProfile
from GameState import GameState
from Narrator.NarrationFallback import build_fallback_narrated_text
from Narrator.NarrationPresets import resolve_narration_style_guidance
from Narrator.NarratorSchema import (
    NARRATOR_BATCH_RESPONSE_SCHEMA,
    NARRATOR_INTRO_RESPONSE_SCHEMA,
)
from Narrator.NarratorTypes import NarratedSegment, NarrationQueueItem
from PromptUtils import render_json_instruction


NARRATOR_SYSTEM_PROMPT = """
You are the Narrator Agent in a multi-character Chinese xianxia story game.
You may be asked to either:
- turn a small batch of raw character actions into third-person narrative lines
- turn structured story planning into an opening or chapter introduction for the player

Goals:
- preserve the original action logic, speaker order, and interaction chain when narrating action
- add grounded expressions, micro-movements, and posture details
- keep spatial awareness and response relationships between characters
- when writing an introduction, establish where the player is, who matters nearby, and what the immediate direction is

Rules:
1. Write in third person.
2. Do not invent new plot outcomes, powers, or knowledge.
3. If a line contains direct speech, keep the speech compatible with the raw action.
4. Each selected action must receive one corresponding narrated line.
5. Keep the batch coherent: characters should feel like they share the same scene.
6. Keep introduction prose concise, image-rich, and suitable for a Chinese xianxia game.
7. Never echo raw turn logs, actor ids, JSON keys, debug notes, or internal heuristic labels in the prose.
8. Return strict JSON only.
"""


INTRO_POLLUTION_MARKERS = (
    "heuristic",
    "scene_end",
    "must_happen",
    "response_pressure",
    "recent_history",
    "director_brief",
)


def _clean_intro_snippet(value: object, *, max_length: int = 120) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in INTRO_POLLUTION_MARKERS):
        return ""
    if "{" in text or "}" in text:
        return ""
    if len(text) > max_length:
        text = text[:max_length].rstrip("，,；;、 ")
    return text


def _intro_needs_afterglow(state: GameState) -> bool:
    scene_memory = state.get("memory", {}).get("scene_memory", {})
    if str(scene_memory.get("tension_trend", "") or "").strip() in {"rising", "high"}:
        return True
    return bool(scene_memory.get("active_conflicts", []))


def _build_transition_context(state: GameState) -> dict[str, Any]:
    scene_memory = state.get("memory", {}).get("scene_memory", {})
    recent_beats = [
        cleaned
        for item in state.get("history", [])[-3:]
        for cleaned in [_clean_intro_snippet(item.get("content", ""))]
        if cleaned
    ]
    return {
        "afterglow_required": _intro_needs_afterglow(state),
        "recent_beats": recent_beats,
        "scene_summary": _clean_intro_snippet(scene_memory.get("summary", ""), max_length=160),
        "active_conflicts": [
            cleaned
            for value in scene_memory.get("active_conflicts", [])[:3]
            for cleaned in [_clean_intro_snippet(value, max_length=80)]
            if cleaned
        ],
        "open_loops": [
            cleaned
            for value in scene_memory.get("open_loops", [])[:3]
            for cleaned in [_clean_intro_snippet(value, max_length=80)]
            if cleaned
        ],
    }


def _build_instruction(
    *,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
    batch: list[NarrationQueueItem],
    style_preset: str,
) -> str:
    payload = {
        "style_guidance": resolve_narration_style_guidance(style_preset),
        "scene": state["scene"],
        "scene_plan": state["scene_plan"],
        "director_brief": state["director_brief"],
        "recent_history": state["history"][-8:],
        "selected_actions": [
            {
                **item,
                "actor_profile": character_profiles.get(item["actor"], {}),
                "target_profile": character_profiles.get(item["target"] or "", {}),
            }
            for item in batch
        ],
    }
    return render_json_instruction(
        "Expand the following batch of raw action records into third-person narration as strict JSON.",
        payload,
    )


def _build_intro_instruction(
    *,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
    intro_kind: str,
    style_preset: str,
) -> str:
    player_id = str(state["player"].get("controlled_character", "") or "").strip()
    current_chapter_id = str(state["plot"].get("chapter_id", "") or "").strip()
    relevant_cast_ids: list[str] = []

    for actor_id in state["scene"].get("on_stage", []):
        resolved_id = str(actor_id or "").strip()
        if resolved_id and resolved_id not in relevant_cast_ids:
            relevant_cast_ids.append(resolved_id)

    for actor_id, profile in character_profiles.items():
        if actor_id in relevant_cast_ids:
            continue
        planned_chapter_ids = [
            str(item or "").strip()
            for item in profile.get("planned_chapter_ids", [])
            if str(item or "").strip()
        ]
        if current_chapter_id and current_chapter_id in planned_chapter_ids:
            relevant_cast_ids.append(actor_id)

    payload = {
        "task": f"{intro_kind}_introduction",
        "style_guidance": resolve_narration_style_guidance(style_preset),
        "player_profile": character_profiles.get(player_id, {}),
        "relevant_cast": {
            actor_id: character_profiles.get(actor_id, {})
            for actor_id in relevant_cast_ids[:4]
            if actor_id in character_profiles
        },
        "scene": state["scene"],
        "plot": {
            "story_premise": state["plot"].get("story_premise", ""),
            "exploration_drive": state["plot"].get("exploration_drive", ""),
            "chapter_id": state["plot"].get("chapter_id", ""),
            "chapter_title": state["plot"].get("current_chapter_title", ""),
            "chapter_goal": state["plot"].get("chapter_goal", ""),
            "chapter_overview": state["plot"].get("current_chapter_overview", ""),
            "chapter_hooks": state["plot"].get("current_chapter_hooks", []),
            "completed_chapters": [
                {
                    "title": _clean_intro_snippet(chapter.get("title", ""), max_length=60),
                    "summary": _clean_intro_snippet(chapter.get("summary", ""), max_length=120),
                }
                for chapter in state["plot"].get("completed_chapters", [])[-2:]
                if isinstance(chapter, dict)
            ],
        },
        "transition_context": _build_transition_context(state),
        "constraints": [
            "Write 2 to 4 Chinese sentences.",
            "Keep a xianxia register and third-person perspective.",
            "Mention place, people, and immediate direction without inventing future outcomes.",
            "If `transition_context.afterglow_required` is true, open with 1 sentence acknowledging lingering pressure before introducing the new direction.",
            "Do not quote raw history arrays, turn ids, key:value pairs, or internal labels.",
        ],
    }
    return render_json_instruction(
        "Write the requested scene introduction as strict JSON.",
        payload,
    )


class NarratorAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=NARRATOR_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.65),
            max_tokens=kwargs.pop("max_tokens", 1000),
            **kwargs,
        )

    def narrate_action_batch(
        self,
        *,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
        batch: list[NarrationQueueItem],
        style_preset: str,
    ) -> list[NarratedSegment]:
        result = self.command(
            instruction=_build_instruction(
                state=state,
                character_profiles=character_profiles,
                batch=batch,
                style_preset=style_preset,
            ),
            response_format=NARRATOR_BATCH_RESPONSE_SCHEMA,
        )
        requested_by_turn = {int(item["history_turn"]): item for item in batch}
        requested_turns = set(requested_by_turn)
        normalized: list[NarratedSegment] = []
        seen_turns: set[int] = set()

        for item in result.get("segments", []):
            history_turn = int(item.get("history_turn", 0) or 0)
            requested_item = requested_by_turn.get(history_turn)
            if requested_item is None or history_turn in seen_turns:
                continue

            actor = str(item.get("actor", "") or "").strip()
            narrated_text = str(item.get("narrated_text", "") or "").strip()
            if not actor or actor != requested_item["actor"] or not narrated_text:
                continue

            seen_turns.add(history_turn)
            normalized.append(
                {
                    "history_turn": history_turn,
                    "actor": requested_item["actor"],
                    "narrated_text": narrated_text,
                }
            )

        if seen_turns == requested_turns:
            normalized.sort(key=lambda item: item["history_turn"])
            return normalized

        fallback_map = {segment["history_turn"]: segment for segment in normalized}
        for item in batch:
            if item["history_turn"] in fallback_map:
                continue

            actor_id = str(item.get("actor", "") or "").strip()
            target_id = str(item.get("target", "") or "").strip()
            actor_name = str(
                character_profiles.get(actor_id, {}).get("name", actor_id) or actor_id
            ).strip()
            target_name = str(
                character_profiles.get(target_id, {}).get("name", target_id) or target_id
            ).strip()
            speech = str(item.get("raw_spoken_text", "") or "").strip()
            action = str(item.get("raw_nonverbal_action", "") or "").strip() or str(
                item.get("raw_content", "") or ""
            ).strip()
            normalized.append(
                {
                    "history_turn": item["history_turn"],
                    "actor": item["actor"],
                    "narrated_text": build_fallback_narrated_text(
                        actor_name=actor_name,
                        speech=speech,
                        action=action,
                        target_name=target_name,
                    ),
                }
            )

        normalized.sort(key=lambda item: item["history_turn"])
        return normalized

    def narrate_story_intro(
        self,
        *,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
        intro_kind: str,
        style_preset: str,
    ) -> str:
        result = self.command(
            instruction=_build_intro_instruction(
                state=state,
                character_profiles=character_profiles,
                intro_kind=intro_kind,
                style_preset=style_preset,
            ),
            response_format=NARRATOR_INTRO_RESPONSE_SCHEMA,
        )
        return " ".join(str(result.get("intro_text", "") or "").strip().split())
