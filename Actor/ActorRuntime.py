from __future__ import annotations

from CharacterMemory import ensure_character_memory_state, normalize_character_memory_config
from CharacterProfile import CharacterProfile
from GameplayTuning import RelationshipTuning
from GameState import CharacterRuntimeState, GameState, ResolvedAct
from History.GameMemory import HistoryItem
from Memory.store import MemoryStore

_MEMORY_STORE = MemoryStore()


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


def _is_l1(character_id: str, character_profiles: dict[str, CharacterProfile] | None) -> bool:
    profile = _resolve_character_profile(character_id, character_profiles)
    return str(profile.get("agent_type", "actor") or "actor") == "L1"


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
    for character_id in _dedupe_character_ids(
        [
            str(character_id or "").strip()
            for character_id in state["scene"].get("on_stage", [])
            if str(character_id or "").strip() in updated
        ]
    ):
        runtime = updated.get(character_id)
        if runtime is None:
            continue
        updated[character_id] = {
            **runtime,
            "memory": _resolve_memory_state(character_id, runtime, character_profiles),
        }
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
            and character_id != player_id
            and _is_l1(character_id, character_profiles)
        ]
    )

    for character_id in player_targets:
        runtime = updated.get(character_id)
        if runtime is None:
            continue
        memory_state = _resolve_memory_state(character_id, runtime, character_profiles)
        memory_config = _resolve_memory_config(character_id, character_profiles)
        relation_delta = _relation_delta_toward_player(
            character_id,
            player_id=player_id,
            actor_id=actor_id,
            resolved_act=resolved_act,
            reciprocal_updates=reciprocal_updates,
        )
        memory_state = _MEMORY_STORE.record_player_impression(
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
        updated[character_id] = {**runtime, "memory": memory_state}

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
        # 补记当前 scene 的在场快照,供后续逐条在场过滤精确使用
        "on_stage": list(state["scene"].get("on_stage", [])),
        "location_id": state["scene"].get("location_id", ""),
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
