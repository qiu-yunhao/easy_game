from __future__ import annotations

from typing import Any

from WorldSetting.schema import AdvanceCondition


def can_advance(condition: AdvanceCondition, state: dict[str, Any]) -> bool | None:
    """判定当前 tier 的晋升条件是否满足。

    返回 True/False;`narrative` 条件返回 None 表示交给叙事层(Director)决定。
    composite 中的 narrative 子条件无法自动判定,按未满足(False)处理,避免误放行。
    """
    ctype = condition.get("type")
    if ctype == "event":
        markers = set(state.get("completed_markers", []) or [])
        return str(condition.get("completion_marker", "") or "") in markers
    if ctype == "threshold":
        counters = state.get("counters", {}) or {}
        current = int(counters.get(str(condition.get("counter_key", "") or ""), 0) or 0)
        return current >= int(condition.get("target_value", 0) or 0)
    if ctype == "narrative":
        return None
    if ctype == "composite":
        op = condition.get("op", "AND")
        results = []
        for sub in condition.get("sub_conditions", []) or []:
            verdict = can_advance(sub, state)
            results.append(bool(verdict) if verdict is not None else False)
        return all(results) if op == "AND" else any(results)
    return False
