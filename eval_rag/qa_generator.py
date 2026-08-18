from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent

"""薄层 QA 生成包装器:回忆检索 chunk + 用户问题 → LLM 生成中文答案。

系统本身无「问题→基于上下文的答案」链路,本包装器专为评测 faithfulness /
answer relevancy 而建:严格要求只依据给定上下文作答,不得编造,便于忠诚度评判。
无上下文时直接降级返回,不空耗 LLM。
"""

_SYSTEM = (
    "你是回忆问答助手。只依据【上下文】中的信息回答用户问题;"
    "上下文没有提到的内容绝不能编造或臆测,若上下文不足以回答就直说「无法从回忆中确定」。"
    "用简洁中文回答。"
)
_NO_CONTEXT = "未检索到相关信息,无法从回忆中确定。"


class RecallQAGenerator:
    def __init__(self, *, agent: Any | None = None) -> None:
        self._agent = agent if agent is not None else BaseAgent(system_prompt=_SYSTEM)

    def answer(self, question: str, contexts: list[str]) -> str:
        if not contexts:
            return _NO_CONTEXT
        joined = "\n".join(f"- {c}" for c in contexts)
        instruction = f"【上下文】\n{joined}\n\n【问题】{question}\n\n请依据上下文作答:"
        return self._agent.command(instruction)
