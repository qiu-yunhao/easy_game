"""情节模板软指导：把检索到的骨架/桥段格式化成提示词参考素材。

纯函数，无副作用、不依赖 LLM/DB。build_template_query 拼检索线索；
format_* 把检索结果转成软指导文本，空输入返回 ""（formatter 据此判断是否注入）。
"""

from __future__ import annotations

from typing import Any

from StoryStateUtils import current_outline_entry

_RECENT_HISTORY_LIMIT = 3


def build_template_query(state: dict[str, Any], history: list[dict] | None) -> str:
    plot = state.get("plot", {})
    parts: list[str] = []
    chapter_goal = str(plot.get("chapter_goal", "") or "").strip()
    if chapter_goal:
        parts.append(chapter_goal)
    outline = current_outline_entry(state)
    title = str(outline.get("title", "") or "").strip()
    main_goal = str(outline.get("main_goal", "") or "").strip()
    if title:
        parts.append(title)
    if main_goal:
        parts.append(main_goal)
    if history:
        recent = history[-_RECENT_HISTORY_LIMIT:]
        for message in recent:
            content = str(message.get("content", "") or "").strip()
            if content:
                parts.append(content)
    return " ".join(parts)


def format_skeleton_guidance(nodes: list[dict]) -> str:
    return ""  # 见 Task 2


def format_beat_guidance(beats: list[dict]) -> str:
    return ""  # 见 Task 2
