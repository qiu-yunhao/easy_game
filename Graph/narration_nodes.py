from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from Graph.component_resolution import (
    resolve_narrator_agent as _resolve_narrator_agent,
    resolve_stylistic_polish_agent as _resolve_stylistic_polish_agent,
)
from GameState import GameState
from Narrator.NarrationFallback import build_fallback_intro_text
from Narrator.NarratorRuntime import (
    apply_narrated_segments,
    build_heuristic_narrated_segments,
    ingest_narration_queue,
    select_narration_batch,
)
from Narrator.NarratorTypes import NarratedSegment, NarrationQueueItem
from StoryStateUtils import clean_text as _clean_text
from StylisticPolish import deterministic_nonverbal_cleanup

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


INTRO_DUMP_PATTERN = re.compile(
    r"\b\d+:[A-Za-z_][A-Za-z0-9_]*:(?:speak|action|event|interrupt|silence|observe)\b"
)
INTRO_POLLUTION_MARKERS = (
    "Heuristic scene-end",
    "response_pressure",
    "must_happen",
    "recent_history",
    "director_brief",
)


def _narration_style_preset(deps: "GraphDependencies") -> str:
    return str(deps.gameplay_tuning.narration.style_preset or "xianxia_default").strip()


def _build_story_intro_text(
    state: GameState,
    deps: "GraphDependencies",
    *,
    intro_kind: str,
) -> tuple[str, str]:
    style_preset = _narration_style_preset(deps)
    narrator_agent = _resolve_narrator_agent(deps)
    if narrator_agent is None:
        return (
            build_fallback_intro_text(
                state=state,
                character_profiles=deps.character_profiles,
                intro_kind=intro_kind,
                style_preset=style_preset,
            ),
            "heuristic",
        )
    try:
        intro_text = narrator_agent.narrate_story_intro(
            state=state,
            character_profiles=deps.character_profiles,
            intro_kind=intro_kind,
            style_preset=style_preset,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        intro_text = ""
    if not _clean_text(intro_text) or _looks_like_polluted_intro_text(intro_text):
        return (
            build_fallback_intro_text(
                state=state,
                character_profiles=deps.character_profiles,
                intro_kind=intro_kind,
                style_preset=style_preset,
            ),
            "heuristic",
        )
    return intro_text, "narrator_agent"


def _append_narration_event(
    state: GameState,
    *,
    content: str,
    source: str,
    style_preset: str,
) -> GameState:
    normalized_content = _clean_text(content)
    if not normalized_content:
        return {
            **state,
            "runtime": {
                **state["runtime"],
                "pending_intro_kind": "",
            },
        }
    next_turn = int(state["runtime"].get("turn_index", 0) or 0) + 1
    return {
        **state,
        "history": [
            *state["history"],
            {
                "turn": next_turn,
                "actor": None,
                "mode": "event",
                "content": normalized_content,
                "narration_source": source,
                "narration_style_preset": style_preset,
                # 补记当前 scene 的在场快照,供后续逐条在场过滤精确使用
                "on_stage": list(state["scene"].get("on_stage", [])),
                "location_id": state["scene"].get("location_id", ""),
            },
        ],
        "runtime": {
            **state["runtime"],
            "turn_index": next_turn,
            "last_actor": None,
            "last_mode": "event",
            "pending_intro_kind": "",
        },
    }


def _normalize_intro_similarity_text(value: str) -> str:
    return "".join(
        character
        for character in _clean_text(value)
        if character not in " \t\r\n，。！？!?；;：:,、\"'“”‘’（）()[]【】"
    )


def _looks_like_polluted_intro_text(value: str) -> bool:
    cleaned = _clean_text(value)
    return bool(cleaned) and (
        bool(INTRO_DUMP_PATTERN.search(cleaned))
        or any(marker.lower() in cleaned.lower() for marker in INTRO_POLLUTION_MARKERS)
    )


def _is_redundant_scene_intro(state: GameState, intro_text: str) -> bool:
    latest_history = state["history"][-1] if state["history"] else None
    if latest_history is None or latest_history.get("actor") is None:
        return False
    normalized_intro = _normalize_intro_similarity_text(intro_text)
    normalized_latest = _normalize_intro_similarity_text(str(latest_history.get("content", "") or ""))
    if not normalized_intro or not normalized_latest:
        return False
    if normalized_intro == normalized_latest:
        return True
    if SequenceMatcher(None, normalized_intro, normalized_latest).ratio() >= 0.84:
        return True
    shorter, longer = sorted((normalized_intro, normalized_latest), key=len)
    return len(shorter) >= 18 and shorter in longer


def _emit_pending_intro(
    state: GameState,
    deps: "GraphDependencies",
    *,
    intro_kind: str,
) -> GameState:
    if str(state["runtime"].get("pending_intro_kind", "") or "").strip() != intro_kind:
        return state
    intro_text, source = _build_story_intro_text(state=state, deps=deps, intro_kind=intro_kind)
    if intro_kind == "scene" and _is_redundant_scene_intro(state, intro_text):
        return {
            **state,
            "runtime": {
                **state["runtime"],
                "pending_intro_kind": "",
            },
        }
    return _append_narration_event(
        state=state,
        content=intro_text,
        source=source,
        style_preset=_narration_style_preset(deps),
    )


def story_intro_node(state: GameState, deps: "GraphDependencies") -> GameState:
    return _emit_pending_intro(state, deps, intro_kind="opening")


def chapter_intro_node(state: GameState, deps: "GraphDependencies") -> GameState:
    pending_intro_kind = str(state["runtime"].get("pending_intro_kind", "") or "").strip()
    if pending_intro_kind not in {"chapter", "scene"}:
        return state
    return _emit_pending_intro(state, deps, intro_kind=pending_intro_kind)


def narration_generate_node(
    state: GameState,
    deps: "GraphDependencies",
    *,
    batch: list[NarrationQueueItem],
) -> tuple[list[NarratedSegment], str]:
    narrator_agent = _resolve_narrator_agent(deps)
    if narrator_agent is not None:
        segments = narrator_agent.narrate_action_batch(
            state=state,
            character_profiles=deps.character_profiles,
            batch=batch,
            style_preset=_narration_style_preset(deps),
        )
        if segments:
            return segments, "narrator_agent"
    if deps.agent_first:
        raise RuntimeError("Agent-first mode requires NarratorAgent output for narration batches.")
    return build_heuristic_narrated_segments(batch, deps.character_profiles), "heuristic"


def narration_polish_node(
    state: GameState,
    deps: "GraphDependencies",
    *,
    segments: list[NarratedSegment],
) -> list[NarratedSegment]:
    if not segments:
        return []
    stylistic_polish_agent = _resolve_stylistic_polish_agent(deps)
    if stylistic_polish_agent is None:
        return [
            {
                **segment,
                "narrated_text": deterministic_nonverbal_cleanup(segment["narrated_text"]),
            }
            for segment in segments
        ]
    return stylistic_polish_agent.polish_narration_batch(
        segments,
        style_preset=_narration_style_preset(deps),
        state=state,
        character_profiles=deps.character_profiles,
    )


def narration_subgraph_node(
    state: GameState,
    deps: "GraphDependencies",
    *,
    force_flush: bool = False,
) -> GameState:
    current = ingest_narration_queue(state)
    should_force = force_flush
    while True:
        tuning = deps.gameplay_tuning.narration
        batch = select_narration_batch(
            list(current["runtime"].get("narration_queue", [])),
            min_batch_actors=tuning.min_batch_actors,
            max_batch_actors=tuning.max_batch_actors,
            force_flush=should_force,
        )
        if not batch:
            return current
        segments, source = narration_generate_node(current, deps, batch=batch)
        current = apply_narrated_segments(
            current,
            batch=batch,
            segments=narration_polish_node(current, deps, segments=segments),
            source=source,
            style_preset=_narration_style_preset(deps),
        )
        should_force = force_flush


def _latest_narration_by_source(state: GameState, source: str) -> str:
    """最近一条同源(director_lead_in / director_wrap_up)旁白的正文,没有则空串。"""
    for entry in reversed(state.get("history", [])):
        if str(entry.get("narration_source", "") or "") == source:
            return str(entry.get("content", "") or "")
    return ""


def _is_redundant_transition(new_text: str, prior_text: str) -> bool:
    """新过渡旁白与上一条同源旁白是否近乎重复(含内容雷同的写死兜底段)。"""
    normalized_new = _normalize_intro_similarity_text(new_text)
    normalized_prior = _normalize_intro_similarity_text(prior_text)
    if not normalized_new or not normalized_prior:
        return False
    if normalized_new == normalized_prior:
        return True
    if SequenceMatcher(None, normalized_new, normalized_prior).ratio() >= 0.84:
        return True
    shorter, longer = sorted((normalized_new, normalized_prior), key=len)
    return len(shorter) >= 18 and shorter in longer


def _consume_director_brief_text(
    state: GameState,
    deps: "GraphDependencies",
    *,
    text_key: str,
    source: str,
) -> GameState:
    text = _clean_text(state["director_brief"].get(text_key, ""))
    if not text:
        return state
    # 与上一条同源过渡旁白近乎重复则跳过落库(仍清空 brief 字段,避免下拍再消费)。
    if _is_redundant_transition(text, _latest_narration_by_source(state, source)):
        return {
            **state,
            "director_brief": {
                **state["director_brief"],
                text_key: "",
            },
        }
    next_state = _append_narration_event(
        state=state,
        content=text,
        source=source,
        style_preset=_narration_style_preset(deps),
    )
    return {
        **next_state,
        "director_brief": {
            **next_state["director_brief"],
            text_key: "",
        },
    }


def director_lead_in_node(state: GameState, deps: "GraphDependencies") -> GameState:
    next_actor = str((state["runtime"].get("next_act") or {}).get("actor", "") or "").strip()
    player_actor = str(state["player"].get("controlled_character", "") or "").strip()
    if not next_actor or next_actor == player_actor:
        return state
    return _consume_director_brief_text(
        state,
        deps,
        text_key="lead_in_text",
        source="director_lead_in",
    )


def director_wrap_up_node(state: GameState, deps: "GraphDependencies") -> GameState:
    last_actor = str(state["runtime"].get("last_actor", "") or "").strip()
    player_actor = str(state["player"].get("controlled_character", "") or "").strip()
    next_actor = str((state["runtime"].get("next_act") or {}).get("actor", "") or "").strip()
    should_emit = bool(state["runtime"].get("scene_finished", False)) or bool(
        state["runtime"].get("chapter_finished", False)
    )
    if not should_emit:
        should_emit = not next_actor or next_actor == player_actor
    if not should_emit or not last_actor or last_actor == player_actor:
        return state
    return _consume_director_brief_text(
        state,
        deps,
        text_key="wrap_up_text",
        source="director_wrap_up",
    )
