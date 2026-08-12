from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


def merge_group_flags(
    ordered_acts: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Deterministically merge cross-actor global flags for a parallel group.

    ordered_acts is sorted by director priority (highest first).
    - should_end_scene/chapter: only the highest-priority actor's value counts.
    - triggered_plot_flags: first non-empty value per key, scanning by priority.
    """
    should_end_scene = False
    should_end_chapter = False
    if ordered_acts:
        _, top_act = ordered_acts[0]
        should_end_scene = bool(top_act.get("should_end_scene", False))
        should_end_chapter = bool(top_act.get("should_end_chapter", False))

    triggered_plot_flags: dict[str, str] = {}
    for _actor_id, act in ordered_acts:
        for key, value in (act.get("triggered_plot_flags") or {}).items():
            if key not in triggered_plot_flags and str(value).strip():
                triggered_plot_flags[key] = str(value)

    return {
        "should_end_scene": should_end_scene,
        "should_end_chapter": should_end_chapter,
        "triggered_plot_flags": triggered_plot_flags,
    }


def _perform_with_retry(
    group_start_state: dict[str, Any],
    actor_id: str,
    resolve_agent: Callable[[str], Any],
    character_profiles: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    # Each actor reads the group-start history (no intra-group pre-reading).
    actor_state = {
        **group_start_state,
        "runtime": {
            **group_start_state["runtime"],
            "next_act": {
                **(group_start_state["runtime"].get("next_act") or {}),
                "actor": actor_id,
            },
        },
    }
    last_error: Exception | None = None
    for _attempt in range(max_retries + 1):
        try:
            agent = resolve_agent(actor_id)
            return agent.perform_turn(state=actor_state, character_profiles=character_profiles)
        except Exception as exc:  # noqa: BLE001 - retry any generation failure
            last_error = exc
    raise last_error if last_error is not None else RuntimeError("unknown actor failure")


def run_actor_group(
    group_start_state: dict[str, Any],
    *,
    group: list[str],
    resolve_agent: Callable[[str], Any],
    character_profiles: dict[str, Any],
    max_retries: int = 3,
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str]]]:
    if not group:
        return [], []

    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(group)) as executor:
        future_map = {
            executor.submit(
                _perform_with_retry,
                group_start_state,
                actor_id,
                resolve_agent,
                character_profiles,
                max_retries,
            ): actor_id
            for actor_id in group
        }
        for future, actor_id in future_map.items():
            try:
                results[actor_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                errors[actor_id] = str(exc)

    successes = [(aid, results[aid]) for aid in group if aid in results]
    failures = [(aid, errors[aid]) for aid in group if aid in errors]
    return successes, failures
