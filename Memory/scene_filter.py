from __future__ import annotations

from typing import Literal

from History.GameMemory import HistoryItem

# 在场判定粒度:严格在台上 vs 同地点即可见。
PresenceGranularity = Literal["on_stage", "location"]


def _is_present(
    item: HistoryItem,
    *,
    actor_id: str,
    current_location_id: str,
    granularity: PresenceGranularity,
) -> bool:
    if granularity == "location":
        # 地点粒度:条目发生地点 == 角色当前所在地点。缺快照则不可见。
        return item.get("location_id", "") == current_location_id
    # 严格 on_stage 粒度(默认):角色当时在台上。缺快照则不可见。
    return actor_id in item.get("on_stage", [])


def filter_history_by_presence(
    history: list[HistoryItem],
    *,
    actor_id: str,
    current_location_id: str,
    recent_rounds: int = 3,
    granularity: PresenceGranularity = "on_stage",
) -> list[HistoryItem]:
    """按「角色当时是否在场」过滤 history,再取最近 recent_rounds 条。

    决策 D:默认严格 on_stage;granularity="location" 时改为同地点可见。
    决策 A:逐条依赖 item 自带的 on_stage/location_id 快照;缺快照即不可见。
    工厂只读,不修改入参。
    """
    kept = [
        item
        for item in history
        if _is_present(
            item,
            actor_id=actor_id,
            current_location_id=current_location_id,
            granularity=granularity,
        )
    ]
    if recent_rounds <= 0:
        return kept
    return kept[-recent_rounds:]
