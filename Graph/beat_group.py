from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from Actor.ActorRuntime import apply_resolved_act

logger = logging.getLogger(__name__)

# Programming errors that must surface instead of being retried/swallowed as a
# "generation failure". IO/API errors (timeout, rate limit, bad LLM output) fall
# through to the retry path.
_PROGRAMMING_ERRORS = (
    AttributeError,
    KeyError,
    IndexError,
    NameError,
    TypeError,
    ImportError,
    AssertionError,
)


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
    provider: Any,
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
    # 每个 actor 各自基于其 actor_state build 记忆上下文(与串行路径一致)。
    memory_ctx = provider.build(actor_id, actor_state)
    last_error: Exception | None = None
    for _attempt in range(max_retries + 1):
        try:
            agent = resolve_agent(actor_id)
            return agent.perform_turn(state=actor_state, memory_ctx=memory_ctx)
        except _PROGRAMMING_ERRORS:
            # A code bug, not a transient generation failure — surface it.
            logger.exception("actor %s raised a programming error; not retrying", actor_id)
            raise
        except Exception as exc:  # noqa: BLE001 - retry transient generation failures
            last_error = exc
            logger.warning(
                "actor %s generation attempt %d failed: %s", actor_id, _attempt + 1, exc
            )
    raise last_error if last_error is not None else RuntimeError("unknown actor failure")


def run_actor_group(
    group_start_state: dict[str, Any],
    *,
    group: list[str],
    resolve_agent: Callable[[str], Any],
    provider: Any,
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
                provider,
                max_retries,
            ): actor_id
            for actor_id in group
        }
        for future, actor_id in future_map.items():
            try:
                results[actor_id] = future.result()
            except _PROGRAMMING_ERRORS:
                # Let a code bug from any worker fail the whole beat loudly.
                raise
            except Exception as exc:  # noqa: BLE001 - transient failure → skip this actor
                errors[actor_id] = str(exc)

    successes = [(aid, results[aid]) for aid in group if aid in results]
    failures = [(aid, errors[aid]) for aid in group if aid in errors]
    return successes, failures


def apply_group_results(
    state: dict[str, Any],
    *,
    successes: list[tuple[str, dict[str, Any]]],
    failures: list[tuple[str, str]],
    relationship_tuning: Any = None,
    character_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = state
    for _actor_id, resolved_act in successes:
        current = {
            **current,
            "runtime": {**current["runtime"], "resolved_act": resolved_act},
        }
        current = apply_resolved_act(
            current,
            relationship_tuning,
            character_profiles=character_profiles,
        )

    flags = merge_group_flags(successes)
    resolved_after = dict(current["runtime"].get("resolved_act") or {})
    if resolved_after:
        resolved_after["should_end_scene"] = flags["should_end_scene"]
        resolved_after["should_end_chapter"] = flags["should_end_chapter"]
        merged_plot_flags = dict(resolved_after.get("triggered_plot_flags") or {})
        merged_plot_flags.update(flags["triggered_plot_flags"])
        resolved_after["triggered_plot_flags"] = merged_plot_flags
        current = {
            **current,
            "runtime": {**current["runtime"], "resolved_act": resolved_after},
        }

    if failures:
        failed_ids = "、".join(actor_id for actor_id, _err in failures)
        next_turn = int(current["runtime"].get("turn_index", 0) or 0) + 1
        current = {
            **current,
            "history": [
                *current["history"],
                {
                    "turn": next_turn,
                    "actor": None,
                    "mode": "event",
                    "content": f"（系统）以下角色本轮生成失败，已跳过：{failed_ids}。",
                    "spoken_text": "",
                    "nonverbal_action": "",
                    "message_kind": "system",
                    # 补记当前 scene 的在场快照,供后续逐条在场过滤精确使用
                    "on_stage": list(current["scene"].get("on_stage", [])),
                    "location_id": current["scene"].get("location_id", ""),
                },
            ],
            "runtime": {**current["runtime"], "turn_index": next_turn},
        }

    return current
