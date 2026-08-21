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


def run_async_refresh(state, *, manager, store, compactor):
    """记忆刷新的单一实现:轮首 join 后台压缩结果(合并 blocks+推进游标+驱逐 history),
    同步从现有 blocks derive Agent 视图(不压缩),policy 判定则 enqueue 后台(非阻塞)。
    hook 与准备期图节点共用此函数,保证同源、无双写。三者缺任一即整体降级返回原 state。
    """
    if manager is None or store is None or compactor is None:
        return state

    merged_state = state
    pending = compactor.take_pending()
    if pending is not None:
        blocks, new_last = pending
        evicted_history = manager.evict_compressed_history(state["history"], new_last)
        merged_state = {
            **state,
            "history": evicted_history,
            "memory": {
                **state["memory"],
                "scene_memory": {
                    **state["memory"]["scene_memory"],
                    "compressed_blocks": blocks,
                },
                "last_compressed_turn": new_last,
            },
        }

    existing_blocks = merged_state["memory"]["scene_memory"]["compressed_blocks"]
    merged_state = {**merged_state, "memory": store.derive_views(merged_state, existing_blocks)}

    decision = decide_refresh(merged_state, trigger_size=manager.compression_trigger_size)
    if decision.should_compress:
        compactor.enqueue(merged_state)

    return merged_state
