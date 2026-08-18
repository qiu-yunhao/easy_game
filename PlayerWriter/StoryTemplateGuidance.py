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
    if not nodes:
        return ""
    lines = ["以下是可参考的情节骨架走向（软指导，可借鉴亦可偏离，不必严格遵循）："]
    for node in nodes:
        title = str(node.get("title", "") or "").strip()
        summary = str(node.get("event_summary", "") or "").strip()
        if not title and not summary:
            continue
        lines.append(f"- {title}：{summary}" if title else f"- {summary}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def format_beat_guidance(beats: list[dict]) -> str:
    if not beats:
        return ""
    lines = ["以下是可参考的桥段素材（作场景候选灵感参考，可借鉴亦可偏离，不必照搬）："]
    for beat in beats:
        label = str(beat.get("label", "") or "").strip()
        summary = str(beat.get("summary", "") or "").strip()
        function = str(beat.get("dramatic_function", "") or "").strip()
        if not label and not summary:
            continue
        segment = f"- {label}：{summary}" if label else f"- {summary}"
        if function:
            segment += f"（戏剧功能：{function}）"
        lines.append(segment)
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
