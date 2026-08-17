from __future__ import annotations

from typing import Any, Optional

from Recall.indexing.scene_indexer import _parse_turn_range

"""从游戏运行时 state 里提取「当前这一幕」的可索引数据。

为什么需要它：引擎的 history 是全局扁平列表、HistoryItem 无 scene_id，且
scene_memory 只保留「当前幕」并随进程覆盖。所以只能在幕刚结束（scene_finished
翻 True）的当下，就地把当前幕切出来——scene_id/chapter_id 取自 plot，
scene_memory 取自 memory，history 用 scene_memory 的 turn_range 按回合区间筛。
事后无法回溯，故本提取器必须在触发点即时调用。
"""


def extract_current_scene(state: dict[str, Any]) -> Optional[dict[str, Any]]:
    """把当前幕切成 build_scene_docs 所需的四元组，无可索引内容时返回 None。

    返回 ``{history, scene_memory, scene_id, chapter_id}``。history 仅保留 turn
    落在 scene_memory.turn_range 区间内的条目（剔除前后幕混入的记录）。

    以下情形视为「无可索引内容」返回 None，避免向量库注入空召回：
      - 缺 scene_id（幕尚未成形）；
      - 摘要、关键事件、落区间的 history 三者皆空。
    注意：turn_range 脏导致 history 切空、但摘要非空时仍会产出——此时可建
    scene_summary 文档，与索引层「空摘要才跳过」的口径保持一致。
    """
    plot = state.get("plot") or {}
    scene_id = str(plot.get("scene_id", "") or "")
    if not scene_id:
        return None
    chapter_id = str(plot.get("chapter_id", "") or "")

    scene_memory = (state.get("memory") or {}).get("scene_memory") or {}
    turn_start, turn_end = _parse_turn_range(scene_memory.get("turn_range", ""))

    history = [
        item
        for item in (state.get("history") or [])
        if turn_start <= int(item.get("turn", 0) or 0) <= turn_end
    ]

    summary = str(scene_memory.get("summary", "") or "").strip()
    key_events = [e for e in (scene_memory.get("key_events") or []) if str(e).strip()]
    if not summary and not key_events and not history:
        return None

    return {
        "history": history,
        "scene_memory": scene_memory,
        "scene_id": scene_id,
        "chapter_id": chapter_id,
    }
