from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from GameplayTuning import RelationshipTuning
from History.GameMemory import empty_memory_state

if TYPE_CHECKING:
    from History.HistoryManager import HistoryManager, MemoryState


# 存档时每个角色只保留 player_memory;主观记忆队列已从模型移除,序列化时丢弃。
_KEPT_CHARACTER_MEMORY_KEYS = ("player_memory",)


def _clamp_relationship(value: float, tuning: RelationshipTuning) -> float:
    return max(tuning.minimum_delta, min(tuning.maximum_delta, value))


class MemoryStore:
    """写侧记忆管理器(spec 4.6)。纯函数:接收 state/记忆片段,返回新片段。

    读侧仍在 DefaultActorMemoryProvider。record_player_impression 从不 mutate 入参,
    也不持有任何记忆状态。逻辑逐字搬移自 Actor/ActorRuntime.py 的
    _append_player_memory + _clamp_relationship。

    压缩与视图派生(spec 4.6「工厂写侧」)委托给持有的 HistoryManager,
    本类不重复计算逻辑,只作为守护线程/轮首 hook 的写侧 API。
    """

    def __init__(self, history_manager: "HistoryManager | None" = None) -> None:
        self._history_manager = history_manager

    def compact(self, state: dict[str, object]) -> tuple[list[dict[str, Any]], int]:
        """委托 HistoryManager.compact_snapshot,返回 (all_blocks, new_last_compressed_turn)。"""
        assert self._history_manager is not None, (
            "MemoryStore.compact requires a history_manager; construct with "
            "MemoryStore(history_manager=...)"
        )
        return self._history_manager.compact_snapshot(state)

    def derive_views(
        self, state: dict[str, object], blocks: list[dict[str, Any]]
    ) -> "MemoryState":
        """委托 HistoryManager.derive_views,从已压缩的 blocks 派生各智能体记忆视图。"""
        assert self._history_manager is not None, (
            "MemoryStore.derive_views requires a history_manager; construct with "
            "MemoryStore(history_manager=...)"
        )
        return self._history_manager.derive_views(state, blocks)

    def record_player_impression(
        self,
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

    def serialize_memory(self, state: dict) -> dict:
        raw_memory = state.get("memory") or {}
        memory_fragment = {key: deepcopy(raw_memory[key]) for key in raw_memory}
        character_memory: dict = {}
        for character_id, character in (state.get("characters") or {}).items():
            if not isinstance(character, dict):
                continue
            char_mem = character.get("memory")
            if not isinstance(char_mem, dict):
                continue
            kept = {
                key: deepcopy(char_mem[key])
                for key in _KEPT_CHARACTER_MEMORY_KEYS
                if key in char_mem
            }
            if kept:
                character_memory[character_id] = kept
        return {"memory": memory_fragment, "character_memory": character_memory}
