from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent
from CharacterProfile import CharacterProfile
from GameState import GameState
from Narrator.NarrationPresets import resolve_narration_style_guidance
from Narrator.NarratorTypes import NarratedSegment
from PromptUtils import render_json_instruction
from StylisticPolish.StylisticPolishSchema import (
    STYLISTIC_NARRATION_BATCH_RESPONSE_SCHEMA,
    STYLISTIC_POLISH_RESPONSE_SCHEMA,
)


STYLISTIC_POLISH_SYSTEM_PROMPT = """
You are the Stylistic Polish Agent for a Chinese roleplay game.
Your job is to polish scene prose while preserving meaning.

Goals:
- keep the prose natural, concrete, and low on AI-sounding phrasing
- preserve the factual meaning, chronology, and intensity
- keep the prose grounded in the immediate scene

Rules:
1. Do not add new plot facts, powers, outcomes, or character knowledge.
2. If the task is nonverbal-only, do not rewrite dialogue.
3. If the task is narration-batch polishing, preserve the actor order and response links.
3. Prefer physical detail, breath, gaze, posture, force, distance, and sensory pressure.
4. Avoid empty abstraction, grandiose metaphors, templated cadence, and generic \"AI prose\".
5. Respect the requested style guidance without changing facts.
6. Keep it concise: usually one sentence per line, at most two.
7. Return strict JSON only.
"""


def _build_instruction(
    draft_action: str,
    actor_id: str,
    mode: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> str:
    payload = {
        "draft_nonverbal_action": draft_action,
        "actor_id": actor_id,
        "mode": mode,
        "actor_profile": character_profiles.get(actor_id, {}),
        "scene": state["scene"],
        "scene_plan": state["scene_plan"],
        "director_brief": state["director_brief"],
        "recent_history": state["history"][-6:],
        "constraints": [
            "Preserve facts and immediate intent.",
            "Do not add dialogue.",
            "Reduce AI-sounding prose.",
        ],
    }
    return render_json_instruction(
        "Polish the following nonverbal action into natural Chinese prose as strict JSON.",
        payload,
    )


def _build_batch_instruction(
    segments: list[NarratedSegment],
    *,
    style_preset: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> str:
    actor_ids = {segment["actor"] for segment in segments}
    payload = {
        "task": "narration_batch",
        "style_guidance": resolve_narration_style_guidance(style_preset),
        "scene": state["scene"],
        "scene_plan": state["scene_plan"],
        "director_brief": state["director_brief"],
        "actor_profiles": {
            actor_id: profile
            for actor_id, profile in character_profiles.items()
            if actor_id in actor_ids
        },
        "segments": segments,
    }
    return render_json_instruction(
        "Polish the following batch of narrated scene lines as strict JSON.",
        payload,
    )


def deterministic_nonverbal_cleanup(action_text: str) -> str:
    cleaned = " ".join(str(action_text or "").strip().split())
    return cleaned.strip("“”\"")


class StylisticPolishAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=STYLISTIC_POLISH_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.35),
            max_tokens=kwargs.pop("max_tokens", 400),
            **kwargs,
        )

    def polish_nonverbal_action(
        self,
        draft_action: str,
        *,
        actor_id: str,
        mode: str,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
    ) -> str:
        draft = deterministic_nonverbal_cleanup(draft_action)
        if not draft:
            return ""

        result = self.command(
            instruction=_build_instruction(
                draft_action=draft,
                actor_id=actor_id,
                mode=mode,
                state=state,
                character_profiles=character_profiles,
            ),
            response_format=STYLISTIC_POLISH_RESPONSE_SCHEMA,
        )
        polished = deterministic_nonverbal_cleanup(result.get("polished_action", ""))
        return polished or draft

    def polish_narration_batch(
        self,
        segments: list[NarratedSegment],
        *,
        style_preset: str,
        state: GameState,
        character_profiles: dict[str, CharacterProfile],
    ) -> list[NarratedSegment]:
        if not segments:
            return []

        result = self.command(
            instruction=_build_batch_instruction(
                segments=segments,
                style_preset=style_preset,
                state=state,
                character_profiles=character_profiles,
            ),
            response_format=STYLISTIC_NARRATION_BATCH_RESPONSE_SCHEMA,
        )

        polished_map = {
            int(item.get("history_turn", 0) or 0): deterministic_nonverbal_cleanup(
                item.get("polished_text", "")
            )
            for item in result.get("segments", [])
            if int(item.get("history_turn", 0) or 0) > 0
        }
        return [
            {
                **segment,
                "narrated_text": polished_map.get(segment["history_turn"], segment["narrated_text"]),
            }
            for segment in segments
        ]
