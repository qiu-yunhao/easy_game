from __future__ import annotations

from CharacterMemory import ensure_character_memory_state, normalize_character_memory_config
from CharacterProfile import CharacterProfile
from GameplayTuning import RelationshipTuning
from GameState import CharacterRuntimeState, GameState, ResolvedAct
from History.GameMemory import HistoryItem


def _clamp_relationship(value: float, tuning: RelationshipTuning) -> float:
    return max(tuning.minimum_delta, min(tuning.maximum_delta, value))


def _merge_float_mapping(
    base: dict[str, float],
    update: dict[str, float],
) -> dict[str, float]:
    merged = dict(base)
    for key, value in update.items():
        merged[key] = float(value)
    return merged


def _merge_additive_mapping(
    base: dict[str, float],
    update: dict[str, float],
    tuning: RelationshipTuning,
) -> dict[str, float]:
    merged = dict(base)
    for key, value in update.items():
        merged[key] = _clamp_relationship(merged.get(key, 0.0) + float(value), tuning)
    return merged


def _append_unique(items: list[str], extra: list[str]) -> list[str]:
    merged = list(items)
    for item in extra:
        if item not in merged:
            merged.append(item)
    return merged


def _consume_pending_beat_actor(pending_beat_actors: list[str], actor_id: str) -> list[str]:
    remaining = list(pending_beat_actors)
    try:
        remaining.remove(actor_id)
    except ValueError:
        return remaining
    return remaining


def _dedupe_character_ids(character_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    for character_id in character_ids:
        if character_id and character_id not in deduped:
            deduped.append(character_id)
    return deduped


def _priority_rank(priority: str) -> int:
    if priority == "critical":
        return 3
    if priority == "high":
        return 2
    return 1


def _resolve_character_profile(
    character_id: str,
    character_profiles: dict[str, CharacterProfile] | None,
) -> CharacterProfile:
    return (character_profiles or {}).get(character_id, {})


def _resolve_memory_config(
    character_id: str,
    character_profiles: dict[str, CharacterProfile] | None,
) -> dict[str, object]:
    profile = _resolve_character_profile(character_id, character_profiles)
    agent_type = str(profile.get("agent_type", "actor") or "actor")
    return normalize_character_memory_config(
        profile.get("memory_profile", {}),
        agent_type=agent_type,
    )


def _resolve_memory_state(
    character_id: str,
    runtime: CharacterRuntimeState,
    character_profiles: dict[str, CharacterProfile] | None,
) -> dict[str, object]:
    return ensure_character_memory_state(
        runtime.get("memory", {}),
        actor_profile=_resolve_character_profile(character_id, character_profiles),
    )


def _update_character_runtime(
    runtime: CharacterRuntimeState,
    *,
    next_intent: str | None = None,
    emotion_update: dict[str, float] | None = None,
    relationship_update: dict[str, float] | None = None,
    revealed_facts: list[str] | None = None,
    turn_index: int | None = None,
    relationship_tuning: RelationshipTuning | None = None,
    memory_state: dict[str, object] | None = None,
) -> CharacterRuntimeState:
    relationship_tuning = relationship_tuning or RelationshipTuning()
    resolved_intent = next_intent if next_intent is not None else runtime.get("intent", "")
    return {
        **runtime,
        "intent": resolved_intent,
        "emotion": _merge_float_mapping(
            runtime.get("emotion", {}),
            emotion_update or {},
        ),
        "relationship_delta": _merge_additive_mapping(
            runtime.get("relationship_delta", {}),
            relationship_update or {},
            relationship_tuning,
        ),
        "known_facts": _append_unique(
            runtime.get("known_facts", []),
            revealed_facts or [],
        ),
        "last_turn": turn_index if turn_index is not None else runtime.get("last_turn", -1),
        "memory": memory_state if memory_state is not None else runtime.get("memory", {}),
    }


def _build_reciprocal_relationship_updates(
    actor_id: str,
    resolved_act: ResolvedAct,
    tuning: RelationshipTuning,
) -> dict[str, dict[str, float]]:
    reciprocal_updates: dict[str, dict[str, float]] = {}
    target_id = resolved_act.get("target")
    mode = resolved_act.get("mode", "speak")

    for other_id, delta in resolved_act["relationship_update"].items():
        if other_id == actor_id:
            continue

        factor = tuning.reciprocity_base_factor
        if other_id == target_id:
            factor = tuning.reciprocity_target_factor
        if mode == "interrupt":
            factor += tuning.reciprocity_interrupt_bonus
        elif mode == "silence":
            factor = tuning.reciprocity_silence_factor

        reciprocal_delta = _clamp_relationship(float(delta) * factor, tuning)
        reciprocal_updates.setdefault(other_id, {})[actor_id] = reciprocal_delta

    return reciprocal_updates


def _build_short_term_memory_event(
    state: GameState,
    resolved_act: ResolvedAct,
    *,
    actor_id: str,
    turn_index: int,
) -> dict[str, object]:
    return {
        "turn": turn_index,
        "chapter_id": str(state["plot"].get("chapter_id", "") or ""),
        "scene_id": str(state["plot"].get("scene_id", "") or ""),
        "location_id": str(state["scene"].get("location_id", "") or ""),
        "actor": actor_id,
        "mode": str(resolved_act.get("mode", "") or ""),
        "summary": str(resolved_act.get("content", "") or ""),
    }


def _derive_long_term_belief(
    character_id: str,
    character_profiles: dict[str, CharacterProfile] | None,
    runtime: CharacterRuntimeState,
) -> str:
    profile = _resolve_character_profile(character_id, character_profiles)
    agent_type = str(profile.get("agent_type", "actor") or "actor")
    if agent_type == "L1":
        l1_profile = profile.get("l1_profile", {})
        return str(
            l1_profile.get("inner_need")
            or l1_profile.get("outer_goal")
            or l1_profile.get("core_conflict")
            or runtime.get("intent", "")
        )
    if agent_type == "L2":
        l2_profile = profile.get("l2_profile", {})
        behavior_rule = list(l2_profile.get("behavior_rule", [])) if isinstance(l2_profile, dict) else []
        return str((behavior_rule[0] if behavior_rule else "") or l2_profile.get("core_drive", "") or runtime.get("intent", ""))
    return str(runtime.get("intent", "") or profile.get("story_role", "") or "")


def _should_record_long_term_memory(resolved_act: ResolvedAct) -> bool:
    relation_delta = sum(abs(float(value)) for value in resolved_act.get("relationship_update", {}).values())
    return bool(
        resolved_act.get("revealed_facts")
        or relation_delta >= 1.5
        or resolved_act.get("should_end_scene", False)
        or resolved_act.get("should_end_chapter", False)
        or resolved_act.get("mode") in {"interrupt", "event"}
    )


def _build_long_term_memory_event(
    resolved_act: ResolvedAct,
    *,
    perspective_id: str,
    actor_id: str,
    player_id: str,
    runtime: CharacterRuntimeState,
    character_profiles: dict[str, CharacterProfile] | None,
    turn_index: int,
) -> dict[str, object]:
    target_id = str(resolved_act.get("target", "") or "")
    if perspective_id == actor_id:
        interpretation = "A decisive moment that reshaped the role's next choices."
    elif perspective_id == target_id:
        interpretation = "An encounter that changed how this scene should be judged."
    else:
        interpretation = "A scene shift important enough to outlast the current exchange."
    relation_delta = sum(abs(float(value)) for value in resolved_act.get("relationship_update", {}).values())
    linked_characters = _dedupe_character_ids(
        [actor_id, target_id, *[str(key) for key in resolved_act.get("relationship_update", {}).keys()]]
    )
    tags: list[str] = []
    pin_reasons: list[str] = []
    if resolved_act.get("revealed_facts"):
        tags.extend(["revealed_fact", "truth_shift"])
        pin_reasons.append("revealed_facts")
    if resolved_act.get("triggered_plot_flags"):
        tags.append("plot_flag")
        pin_reasons.append("plot_flag")
    if resolved_act.get("should_end_chapter", False):
        tags.append("chapter_turn")
        pin_reasons.append("chapter_end")
    elif resolved_act.get("should_end_scene", False):
        tags.append("scene_turn")
    if relation_delta >= 2.0:
        tags.append("relationship_shift")
        pin_reasons.append("major_relationship_shift")
    elif relation_delta >= 1.5:
        tags.append("relationship_shift")
    mode = str(resolved_act.get("mode", "") or "")
    if mode in {"interrupt", "event"}:
        tags.append(mode)
    if player_id and player_id in linked_characters:
        tags.append("player")
        if relation_delta >= 1.0:
            pin_reasons.append("player_turning_point")

    profile = _resolve_character_profile(perspective_id, character_profiles)
    agent_type = str(profile.get("agent_type", "actor") or "actor")
    if agent_type == "L1":
        tags.append("l1_perspective")
        if any(tag in tags for tag in ("plot_flag", "revealed_fact")):
            pin_reasons.append("l1_core_arc")
        elif player_id and player_id in linked_characters and relation_delta >= 1.0:
            pin_reasons.append("l1_player_turn")

    priority = "critical"
    if not pin_reasons:
        priority = "high" if relation_delta >= 1.5 or mode in {"interrupt", "event"} else "medium"
    elif not any(reason in {"plot_flag", "chapter_end", "l1_core_arc"} for reason in pin_reasons):
        priority = "high"

    return {
        "turn_recorded": turn_index,
        "event_summary": str(resolved_act.get("content", "") or ""),
        "subjective_interpretation": interpretation,
        "belief_formed": _derive_long_term_belief(
            perspective_id,
            character_profiles,
            runtime,
        ),
        "priority": priority,
        "tags": _dedupe_character_ids(tags),
        "pin_candidate": bool(pin_reasons),
        "pin_reason": pin_reasons[0] if pin_reasons else "",
        "linked_characters": linked_characters,
    }


def _player_impression_text(relation_delta: float) -> str:
    if relation_delta >= 1.0:
        return "The player feels more trustworthy and useful."
    if relation_delta <= -1.0:
        return "The player feels risky and should be handled carefully."
    return "The player deserves further observation."


def _player_memory_targets(
    state: GameState,
    resolved_act: ResolvedAct,
    *,
    actor_id: str,
    player_id: str,
) -> list[str]:
    target_id = str(resolved_act.get("target", "") or "")
    on_stage = [
        str(character_id or "").strip()
        for character_id in state["scene"].get("on_stage", [])
        if str(character_id or "").strip()
    ]
    if actor_id == player_id:
        return [character_id for character_id in on_stage if character_id != player_id]
    if target_id == player_id and actor_id != player_id:
        return [actor_id]
    if player_id in resolved_act.get("relationship_update", {}) and actor_id != player_id:
        return [actor_id]
    return []


def _relation_delta_toward_player(
    character_id: str,
    *,
    player_id: str,
    actor_id: str,
    resolved_act: ResolvedAct,
    reciprocal_updates: dict[str, dict[str, float]],
) -> float:
    if character_id == actor_id:
        return float(resolved_act.get("relationship_update", {}).get(player_id, 0.0) or 0.0)
    return float(reciprocal_updates.get(character_id, {}).get(player_id, 0.0) or 0.0)


def _append_short_term_memory(
    memory_state: dict[str, object],
    entry: dict[str, object],
    *,
    limit: int,
) -> dict[str, object]:
    items = list(memory_state.get("short_term_memory", []))
    items.append(entry)
    return {
        **memory_state,
        "short_term_memory": items[-limit:],
    }


def _append_long_term_memory(
    memory_state: dict[str, object],
    entry: dict[str, object],
    *,
    limit: int,
    pinned_limit: int,
    consolidated_limit: int,
    consolidation_batch_size: int,
) -> dict[str, object]:
    raw_items = list(memory_state.get("long_term_memory", []))
    pinned_items = list(memory_state.get("pinned_long_term_memory", []))
    consolidated_items = list(memory_state.get("consolidated_memory", []))

    if bool(entry.get("pin_candidate", False)):
        pinned_items.append(entry)
    else:
        raw_items.append(entry)

    while len(raw_items) > limit:
        overflow = len(raw_items) - limit
        take_count = max(2, min(consolidation_batch_size, overflow + 1))
        take_count = min(take_count, len(raw_items))
        chunk = raw_items[:take_count]
        raw_items = raw_items[take_count:]
        topic = _select_consolidation_topic(chunk)
        first_summary = str(chunk[0].get("event_summary", "") or "")
        last_summary = str(chunk[-1].get("event_summary", "") or "")
        topic_summaries = {
            "hidden_truth": "Older clues consolidated into a clearer understanding of hidden truths.",
            "plot_shift": "Several decisive beats pushed the larger situation into a new state.",
            "player_relation": "Repeated exchanges with the player settled into a clearer long-term stance.",
            "relationship_shift": "A series of encounters steadily reshaped the relationship dynamics.",
            "scene_pivot": "Several earlier pivots continued to frame how this role judges the scene.",
            "ongoing_tension": "A cluster of earlier turning points continued to shape the role's outlook.",
        }
        consolidated_items.append(
            {
                "turn_start": int(chunk[0].get("turn_recorded", 0) or 0),
                "turn_end": int(chunk[-1].get("turn_recorded", 0) or 0),
                "topic": topic,
                "event_summary": (
                    f"{topic_summaries.get(topic, topic_summaries['ongoing_tension'])} "
                    f"From '{first_summary}' to '{last_summary}'."
                ).strip(),
                "subjective_interpretation": str(
                    chunk[-1].get("subjective_interpretation", "")
                    or chunk[0].get("subjective_interpretation", "")
                    or "These earlier moments still influence the role's current reading of events."
                ),
                "belief_formed": str(
                    chunk[-1].get("belief_formed", "")
                    or chunk[0].get("belief_formed", "")
                    or ""
                ),
                "linked_characters": _dedupe_character_ids(
                    [
                        str(character_id)
                        for item in chunk
                        for character_id in item.get("linked_characters", [])
                    ]
                ),
                "source_event_count": len(chunk),
                "priority": (
                    "high"
                    if any(_priority_rank(str(item.get("priority", "medium") or "medium")) >= 2 for item in chunk)
                    else "medium"
                ),
            }
        )

    return {
        **memory_state,
        "pinned_long_term_memory": pinned_items[-pinned_limit:],
        "long_term_memory": raw_items[-limit:],
        "consolidated_memory": consolidated_items[-consolidated_limit:],
    }


def _select_consolidation_topic(events: list[dict[str, object]]) -> str:
    scores = {
        "hidden_truth": 0,
        "plot_shift": 0,
        "player_relation": 0,
        "relationship_shift": 0,
        "scene_pivot": 0,
        "ongoing_tension": 1,
    }
    for item in events:
        tags = {str(tag) for tag in item.get("tags", []) if str(tag).strip()}
        if "revealed_fact" in tags:
            scores["hidden_truth"] += 3
        if "plot_flag" in tags or "chapter_turn" in tags:
            scores["plot_shift"] += 3
        if "player" in tags and "relationship_shift" in tags:
            scores["player_relation"] += 3
        elif "player" in tags:
            scores["player_relation"] += 1
        if "relationship_shift" in tags:
            scores["relationship_shift"] += 2
        if {"interrupt", "event", "scene_turn"} & tags:
            scores["scene_pivot"] += 2
    return max(scores.items(), key=lambda item: item[1])[0]


def _append_player_memory(
    memory_state: dict[str, object],
    *,
    player_id: str,
    relation_delta: float,
    event: dict[str, object],
    limit: int,
    tuning: RelationshipTuning,
) -> dict[str, object]:
    player_memory = dict(memory_state.get("player_memory", {}))
    key_events = list(player_memory.get("key_events", []))
    key_events.append(event)
    relation_state = dict(player_memory.get("relation_state", {}))
    relation_state[player_id] = _clamp_relationship(
        float(relation_state.get(player_id, 0.0) or 0.0) + relation_delta,
        tuning,
    )
    return {
        **memory_state,
        "player_memory": {
            **player_memory,
            "overall_impression": event["impression"],
            "relation_state": relation_state,
            "key_events": key_events[-limit:],
        },
    }


def _build_player_memory_event(
    resolved_act: ResolvedAct,
    *,
    relation_delta: float,
    turn_index: int,
) -> dict[str, object]:
    if relation_delta >= 1.0:
        tags = ["trust", "positive"]
    elif relation_delta <= -1.0:
        tags = ["wary", "negative"]
    else:
        tags = ["observe"]
    return {
        "turn": turn_index,
        "summary": str(resolved_act.get("content", "") or ""),
        "impression": _player_impression_text(relation_delta),
        "rationale": str(resolved_act.get("next_intent", "") or "")
        or str((resolved_act.get("revealed_facts") or [""])[0] or "")
        or str(resolved_act.get("mode", "") or ""),
        "relation_delta": relation_delta,
        "tags": tags,
    }


def _apply_memory_updates(
    state: GameState,
    *,
    characters: dict[str, CharacterRuntimeState],
    actor_id: str,
    resolved_act: ResolvedAct,
    turn_index: int,
    character_profiles: dict[str, CharacterProfile] | None,
    reciprocal_updates: dict[str, dict[str, float]],
    relationship_tuning: RelationshipTuning,
) -> dict[str, CharacterRuntimeState]:
    updated = dict(characters)
    player_id = str(state["player"].get("controlled_character", "") or "player")
    short_term_targets = _dedupe_character_ids(
        [
            str(character_id or "").strip()
            for character_id in state["scene"].get("on_stage", [])
            if str(character_id or "").strip() in updated
        ]
        or [actor_id, str(resolved_act.get("target", "") or "")]
    )
    long_term_targets = _dedupe_character_ids([actor_id, str(resolved_act.get("target", "") or "")])
    player_targets = _dedupe_character_ids(
        [
            character_id
            for character_id in _player_memory_targets(
                state,
                resolved_act,
                actor_id=actor_id,
                player_id=player_id,
            )
            if character_id in updated
        ]
    )
    short_term_event = _build_short_term_memory_event(
        state,
        resolved_act,
        actor_id=actor_id,
        turn_index=turn_index,
    )

    for character_id in short_term_targets:
        runtime = updated.get(character_id)
        if runtime is None:
            continue
        memory_state = _resolve_memory_state(character_id, runtime, character_profiles)
        memory_config = _resolve_memory_config(character_id, character_profiles)
        memory_state = _append_short_term_memory(
            memory_state,
            short_term_event,
            limit=int(memory_config["short_term_limit"]),
        )

        if character_id in long_term_targets and _should_record_long_term_memory(resolved_act):
            memory_state = _append_long_term_memory(
                memory_state,
                _build_long_term_memory_event(
                    resolved_act,
                    perspective_id=character_id,
                    actor_id=actor_id,
                    player_id=player_id,
                    runtime=runtime,
                    character_profiles=character_profiles,
                    turn_index=turn_index,
                ),
                limit=int(memory_config["long_term_limit"]),
                pinned_limit=int(memory_config["pinned_long_term_limit"]),
                consolidated_limit=int(memory_config["consolidated_memory_limit"]),
                consolidation_batch_size=int(memory_config["consolidation_batch_size"]),
            )

        if character_id in player_targets and character_id != player_id:
            relation_delta = _relation_delta_toward_player(
                character_id,
                player_id=player_id,
                actor_id=actor_id,
                resolved_act=resolved_act,
                reciprocal_updates=reciprocal_updates,
            )
            memory_state = _append_player_memory(
                memory_state,
                player_id=player_id,
                relation_delta=relation_delta,
                event=_build_player_memory_event(
                    resolved_act,
                    relation_delta=relation_delta,
                    turn_index=turn_index,
                ),
                limit=int(memory_config["player_memory_limit"]),
                tuning=relationship_tuning,
            )

        updated[character_id] = {
            **runtime,
            "memory": memory_state,
        }

    return updated


def apply_resolved_act(
    state: GameState,
    relationship_tuning: RelationshipTuning | None = None,
    *,
    character_profiles: dict[str, CharacterProfile] | None = None,
) -> GameState:
    relationship_tuning = relationship_tuning or RelationshipTuning()
    resolved_act = state["runtime"].get("resolved_act")
    if not resolved_act or resolved_act.get("actor") is None:
        return state

    actor_id = str(resolved_act["actor"])
    next_turn = state["runtime"]["turn_index"] + 1
    history_item: HistoryItem = {
        "turn": next_turn,
        "actor": actor_id,
        "mode": resolved_act["mode"],
        "content": resolved_act["content"],
        "spoken_text": resolved_act.get("spoken_text", ""),
        "nonverbal_action": resolved_act.get("nonverbal_action", ""),
    }

    characters = dict(state["characters"])
    reciprocal_updates = _build_reciprocal_relationship_updates(
        actor_id,
        resolved_act,
        relationship_tuning,
    )

    actor_runtime = characters.get(actor_id)
    if actor_runtime is not None:
        characters[actor_id] = _update_character_runtime(
            runtime=actor_runtime,
            next_intent=resolved_act.get("next_intent") or actor_runtime.get("intent", ""),
            emotion_update=resolved_act["emotion_update"],
            relationship_update=resolved_act["relationship_update"],
            revealed_facts=resolved_act["revealed_facts"],
            turn_index=next_turn,
            relationship_tuning=relationship_tuning,
            memory_state=_resolve_memory_state(actor_id, actor_runtime, character_profiles),
        )

    for other_id, relationship_update in reciprocal_updates.items():
        other_runtime = characters.get(other_id)
        if other_runtime is None:
            continue
        characters[other_id] = _update_character_runtime(
            runtime=other_runtime,
            relationship_update=relationship_update,
            relationship_tuning=relationship_tuning,
            memory_state=_resolve_memory_state(other_id, other_runtime, character_profiles),
        )

    characters = _apply_memory_updates(
        state,
        characters=characters,
        actor_id=actor_id,
        resolved_act=resolved_act,
        turn_index=next_turn,
        character_profiles=character_profiles,
        reciprocal_updates=reciprocal_updates,
        relationship_tuning=relationship_tuning,
    )

    plot_flags = dict(state["plot"].get("plot_flags", {}))
    plot_flags.update(resolved_act["triggered_plot_flags"])
    pending_beat_actors = _consume_pending_beat_actor(
        state["runtime"].get("pending_beat_actors", []),
        actor_id,
    )
    fallback_turns_remaining = int(state["runtime"].get("beat_fallback_turns_remaining", 0) or 0)
    if pending_beat_actors == list(state["runtime"].get("pending_beat_actors", [])) and fallback_turns_remaining > 0:
        fallback_turns_remaining -= 1
    return {
        **state,
        "plot": {
            **state["plot"],
            "plot_flags": plot_flags,
        },
        "characters": characters,
        "history": [*state["history"], history_item],
        "runtime": {
            **state["runtime"],
            "turn_index": next_turn,
            "last_actor": actor_id,
            "last_mode": resolved_act["mode"],
            "pending_beat_actors": pending_beat_actors,
            "beat_fallback_turns_remaining": fallback_turns_remaining,
            "next_act": None,
            "resolved_act": resolved_act,
            "scene_finished": state["runtime"].get("scene_finished", False),
            "chapter_finished": state["runtime"].get("chapter_finished", False),
        },
    }
