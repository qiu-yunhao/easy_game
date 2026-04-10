from __future__ import annotations

from typing import Iterable

from CharacterProfile import CharacterProfile
from GameState import GameState
from Narrator.NarrationFallback import build_fallback_narrated_text
from Narrator.NarrationPresets import DEFAULT_NARRATION_STYLE_PRESET
from Narrator.NarratorTypes import NarratedSegment, NarrationQueueItem


def build_narration_queue_item(state: GameState) -> NarrationQueueItem | None:
    resolved_act = state["runtime"].get("resolved_act")
    if not resolved_act:
        return None

    actor = str(resolved_act.get("actor", "") or "").strip()
    if not actor:
        return None

    latest_history = state["history"][-1] if state["history"] else None
    if latest_history is None:
        return None

    return {
        "history_turn": int(latest_history["turn"]),
        "actor": actor,
        "target": resolved_act.get("target"),
        "mode": str(resolved_act.get("mode", "speak") or "speak"),
        "raw_content": str(latest_history.get("content", "") or "").strip(),
        "raw_spoken_text": str(latest_history.get("spoken_text", "") or "").strip(),
        "raw_nonverbal_action": str(latest_history.get("nonverbal_action", "") or "").strip(),
    }


def ingest_narration_queue(state: GameState) -> GameState:
    queue_item = build_narration_queue_item(state)
    if queue_item is None:
        return state

    narration_queue = list(state["runtime"].get("narration_queue", []))
    if any(item["history_turn"] == queue_item["history_turn"] for item in narration_queue):
        return state

    return {
        **state,
        "runtime": {
            **state["runtime"],
            "narration_queue": [*narration_queue, queue_item],
        },
    }


def _unique_actor_count(items: Iterable[NarrationQueueItem]) -> int:
    seen: list[str] = []
    for item in items:
        actor = str(item["actor"]).strip()
        if actor and actor not in seen:
            seen.append(actor)
    return len(seen)


def should_select_narration_batch(
    queue: list[NarrationQueueItem],
    *,
    min_batch_actors: int,
    force_flush: bool,
) -> bool:
    if not queue:
        return False
    if _unique_actor_count(queue) >= min_batch_actors:
        return True
    return force_flush


def select_narration_batch(
    queue: list[NarrationQueueItem],
    *,
    min_batch_actors: int,
    max_batch_actors: int,
    force_flush: bool,
) -> list[NarrationQueueItem]:
    if not should_select_narration_batch(
        queue,
        min_batch_actors=min_batch_actors,
        force_flush=force_flush,
    ):
        return []

    selected: list[NarrationQueueItem] = []
    seen_actors: list[str] = []
    for item in queue:
        actor = str(item["actor"]).strip()
        if not actor or actor in seen_actors:
            continue
        selected.append(item)
        seen_actors.append(actor)
        if len(seen_actors) >= max_batch_actors:
            break

    if len(seen_actors) < min_batch_actors and not force_flush:
        return []
    return selected


def build_heuristic_narrated_segments(
    batch: list[NarrationQueueItem],
    character_profiles: dict[str, CharacterProfile],
) -> list[NarratedSegment]:
    segments: list[NarratedSegment] = []
    for index, item in enumerate(batch):
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
        segments.append(
            {
                "history_turn": item["history_turn"],
                "actor": item["actor"],
                "narrated_text": build_fallback_narrated_text(
                    actor_name=actor_name,
                    speech=speech,
                    action=action,
                    target_name=target_name,
                    connective="与此同时" if index > 0 else "",
                ),
            }
        )
    return segments


def apply_narrated_segments(
    state: GameState,
    *,
    batch: list[NarrationQueueItem],
    segments: list[NarratedSegment],
    source: str,
    style_preset: str = DEFAULT_NARRATION_STYLE_PRESET,
) -> GameState:
    updates = {segment["history_turn"]: segment for segment in segments}
    if not updates:
        return state

    selected_turns = {item["history_turn"] for item in batch}
    updated_history = []
    for item in state["history"]:
        history_turn = int(item.get("turn", 0) or 0)
        segment = updates.get(history_turn)
        if segment is None:
            updated_history.append(item)
            continue

        updated_item = dict(item)
        updated_item["raw_content"] = str(item.get("raw_content", item.get("content", "")) or "").strip()
        updated_item["raw_spoken_text"] = str(
            item.get("raw_spoken_text", item.get("spoken_text", "")) or ""
        ).strip()
        updated_item["raw_nonverbal_action"] = str(
            item.get("raw_nonverbal_action", item.get("nonverbal_action", "")) or ""
        ).strip()
        updated_item["content"] = segment["narrated_text"]
        updated_item["narration_source"] = source
        updated_item["narration_style_preset"] = style_preset
        updated_history.append(updated_item)

    remaining_queue = [
        item
        for item in state["runtime"].get("narration_queue", [])
        if item["history_turn"] not in selected_turns
    ]
    return {
        **state,
        "history": updated_history,
        "runtime": {
            **state["runtime"],
            "narration_queue": remaining_queue,
        },
    }
