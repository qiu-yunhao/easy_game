from __future__ import annotations

import json
from typing import Any

from BaseAgent import BaseAgent
from History.HistorySchema import (
    HISTORY_CHUNK_SUMMARY_SCHEMA,
    HISTORY_SCORE_RESPONSE_SCHEMA,
)


HISTORY_SUMMARIZER_SYSTEM_PROMPT = """
你是一个多角色对话游戏中的 History Summarizer Agent。
你的职责分成两部分：

1. 为历史记录打 importance_score。
2. 将中低重要度的历史片段压缩成结构化摘要。

要求：
- 只输出 JSON。
- 不要编造未发生的事实。
- 压缩时保留事件顺序、角色关系变化和后续调度所需信息。
"""


class HistorySummarizerAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            system_prompt=HISTORY_SUMMARIZER_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.2),
            max_tokens=kwargs.pop("max_tokens", 1200),
            **kwargs,
        )

    def score_history_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        instruction = (
            "请基于以下场景状态与历史记录，为每条历史记录输出 importance_score 和 score_reason。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        result = self.command(
            instruction=instruction,
            response_format=HISTORY_SCORE_RESPONSE_SCHEMA,
        )
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise ValueError("history score response missing `items` list")
        return items

    def summarize_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        instruction = (
            "请压缩以下历史片段，保留事件顺序、关键角色和可供后续调度使用的信息。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        return self.command(
            instruction=instruction,
            response_format=HISTORY_CHUNK_SUMMARY_SCHEMA,
        )
