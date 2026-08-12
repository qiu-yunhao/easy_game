from __future__ import annotations

from typing import Any


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
