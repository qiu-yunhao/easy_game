from __future__ import annotations

from dataclasses import dataclass

from GameState import GameState


@dataclass(frozen=True)
class RefreshDecision:
    should_compress: bool
    compress_all: bool


def _uncompressed_count(state: GameState) -> int:
    last = state["memory"]["last_compressed_turn"]
    return sum(1 for item in state["history"] if item["turn"] > last)


def decide_refresh(state: GameState, *, trigger_size: int) -> RefreshDecision:
    turn = state["runtime"]["turn_index"]
    has_blocks = bool(state["memory"]["scene_memory"]["compressed_blocks"])

    if turn == 0 and not has_blocks:
        return RefreshDecision(should_compress=False, compress_all=False)
    if state["runtime"].get("scene_finished", False):
        return RefreshDecision(should_compress=True, compress_all=True)
    if _uncompressed_count(state) >= trigger_size:
        return RefreshDecision(should_compress=True, compress_all=False)
    return RefreshDecision(should_compress=False, compress_all=False)
