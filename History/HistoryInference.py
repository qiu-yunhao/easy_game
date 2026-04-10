from __future__ import annotations

from typing import Literal, Optional

from GameState import GameState
from History.GameMemory import (
    CompressedHistoryBlock,
    DirectorMemory,
    PlaywrightMemory,
    SceneMemory,
    SchedulerMemory,
    empty_memory_state,
)


def get_visible_blocks(
    state: GameState,
    blocks: list[CompressedHistoryBlock],
    summary_horizon_turns: int,
) -> list[CompressedHistoryBlock]:
    if not blocks:
        return []
    window_start = max(0, state["runtime"]["turn_index"] - summary_horizon_turns + 1)
    visible_blocks = [block for block in blocks if block["turn_end"] >= window_start]
    return visible_blocks or blocks[-8:]


def infer_revealed_facts(blocks: list[CompressedHistoryBlock]) -> list[str]:
    facts: list[str] = []
    for block in blocks:
        for point in block["key_points"]:
            if any(token in point.lower() for token in ("truth", "secret", "know", "discover", "admit")):
                facts.append(point)
    return facts[-8:]


def infer_active_conflicts(state: GameState) -> list[str]:
    conflicts: list[str] = []
    for cid, runtime in state["characters"].items():
        intent = runtime.get("intent", "")
        if intent:
            conflicts.append(f"{cid}:{intent}")
    return list(dict.fromkeys(conflicts))[:8]


def infer_open_loops(state: GameState) -> list[str]:
    plot_flags = state["plot"].get("plot_flags", {})
    current_must_happen = state["scene_plan"].get("must_happen", [])
    return [item for item in current_must_happen if item not in plot_flags][:8]


def infer_response_pressure(
    state: GameState,
    blocks: list[CompressedHistoryBlock],
) -> list[str]:
    on_stage = state["scene"].get("on_stage", [])
    if not blocks:
        return on_stage[:3]

    last_actors = set(blocks[-1]["actors"])
    pressure = [
        cid
        for cid in state["director_brief"].get("who_should_respond", [])
        if cid in on_stage
    ]
    for cid in on_stage:
        if cid not in last_actors and cid not in pressure:
            pressure.append(cid)
    return pressure[:3]


def infer_tension_trend(state: GameState) -> Literal["stable", "rising", "high"]:
    tension = state["scene"].get("tension", 0.0)
    if tension >= 0.75:
        return "high"
    if tension >= 0.45:
        return "rising"
    return "stable"


def infer_focus_suggestion(
    state: GameState,
    blocks: list[CompressedHistoryBlock],
) -> Optional[str]:
    response_pressure = infer_response_pressure(state, blocks)
    if response_pressure:
        return response_pressure[0]
    return state["scene"].get("focus_character")


def build_scene_memory_from_blocks(
    state: GameState,
    blocks: list[CompressedHistoryBlock],
    summary_horizon_turns: int,
) -> SceneMemory:
    visible_blocks = get_visible_blocks(state, blocks, summary_horizon_turns)
    if not visible_blocks:
        return empty_memory_state()["scene_memory"]

    all_key_points: list[str] = []
    recent_speakers: list[str] = []
    for block in visible_blocks:
        all_key_points.extend(block["key_points"])
        recent_speakers.extend(block["actors"])

    summary_text = " ".join(block["summary"] for block in visible_blocks[-8:])
    turn_start = visible_blocks[0]["turn_start"]
    turn_end = visible_blocks[-1]["turn_end"]

    return {
        "turn_range": f"{turn_start}-{turn_end}",
        "summary": summary_text,
        "key_events": all_key_points[-8:],
        "revealed_facts": infer_revealed_facts(visible_blocks),
        "active_conflicts": infer_active_conflicts(state),
        "open_loops": infer_open_loops(state),
        "recent_speakers": recent_speakers[-8:],
        "response_pressure": infer_response_pressure(state, visible_blocks),
        "tension_trend": infer_tension_trend(state),
        "focus_suggestion": infer_focus_suggestion(state, visible_blocks),
        "compressed_blocks": blocks,
    }


def build_playwright_memory(
    state: GameState,
    scene_memory: SceneMemory,
) -> PlaywrightMemory:
    return {
        "scene_summary": scene_memory["summary"],
        "key_events": scene_memory["key_events"],
        "revealed_facts": scene_memory["revealed_facts"],
        "active_conflicts": scene_memory["active_conflicts"],
        "open_loops": scene_memory["open_loops"],
        "protected_secrets": state["scene_plan"].get("must_not_happen", []),
        "character_objectives_hint": state["scene_plan"].get("character_objectives", {}),
    }


def build_director_memory(
    state: GameState,
    scene_memory: SceneMemory,
) -> DirectorMemory:
    recent_stage_dynamics = [
        f"{block['turn_start']}-{block['turn_end']}:{block['bucket']}:{block['summary']}"
        for block in scene_memory["compressed_blocks"][-6:]
    ]

    beat_suggestion: Optional[str] = None
    if scene_memory["tension_trend"] == "high":
        beat_suggestion = "escalate_conflict"
    elif scene_memory["tension_trend"] == "rising":
        beat_suggestion = "probe_and_pressure"
    elif scene_memory["open_loops"]:
        beat_suggestion = "advance_open_loop"

    return {
        "scene_summary": scene_memory["summary"],
        "recent_stage_dynamics": recent_stage_dynamics,
        "current_focus": state["scene"].get("focus_character")
        or scene_memory.get("focus_suggestion"),
        "tension_trend": scene_memory["tension_trend"],
        "who_needs_response": scene_memory["response_pressure"],
        "active_conflicts": scene_memory["active_conflicts"],
        "beat_suggestion": beat_suggestion,
    }


def build_scheduler_memory(
    state: GameState,
    scene_memory: SceneMemory,
    scheduler_round_window: int,
) -> SchedulerMemory:
    last_rounds = [
        f"{block['turn_start']}-{block['turn_end']}[{block['bucket']}/{block['kind']}]: {block['summary']}"
        for block in scene_memory["compressed_blocks"][-scheduler_round_window:]
    ]
    unanswered_prompts = [
        block["summary"]
        for block in scene_memory["compressed_blocks"][-4:]
        if "?" in block["summary"]
    ]

    return {
        "scene_summary": scene_memory["summary"],
        "last_rounds": last_rounds,
        "recent_speakers": scene_memory["recent_speakers"],
        "unanswered_prompts": unanswered_prompts[-3:],
        "on_stage": state["scene"]["on_stage"],
        "focus_character": state["scene"].get("focus_character")
        or scene_memory.get("focus_suggestion"),
        "response_pressure": scene_memory["response_pressure"],
    }
