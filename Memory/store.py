from __future__ import annotations

from GameplayTuning import RelationshipTuning


def _clamp_relationship(value: float, tuning: RelationshipTuning) -> float:
    return max(tuning.minimum_delta, min(tuning.maximum_delta, value))


class MemoryStore:
    """写侧记忆管理器(spec 4.6)。纯函数:接收 state/记忆片段,返回新片段。

    读侧仍在 DefaultActorMemoryProvider。本类从不 mutate 入参,也不持有任何记忆状态。
    逻辑逐字搬移自 Actor/ActorRuntime.py 的 _append_player_memory + _clamp_relationship。
    """

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
