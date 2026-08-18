from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent

"""生成质量指标:LLM-as-judge 评 faithfulness / answer relevancy。

- faithfulness(忠诚度):答案是否完全基于上下文;编造上下文没有的信息即扣分。
- answer relevancy(答案相关性):答案是否真正回答了问题(只看切题,不评对错)。
裁判经 BaseAgent(response_format="json")返回 {score,reason};解析失败降级为 0。
"""

_JUDGE_SYSTEM = "你是严格的 RAG 评测裁判,只输出 JSON。"

_FAITH_TMPL = (
    "判断【答案】是否完全基于【上下文】。答案里每一条主张都必须能在上下文中找到依据;"
    "凡上下文未提及却出现在答案里的信息(例如上下文写「三到七日到账」而答案说「当日到账」)"
    "均属不忠诚,应扣分。完全有据=1.0,大量编造=0.0。\n\n"
    "【上下文】\n{contexts}\n\n【答案】{answer}\n\n"
    '只输出 JSON: {{"score": 0到1的小数, "reason": "简短中文理由"}}'
)

_REL_TMPL = (
    "判断【答案】是否真正回答了【问题】(只看是否切题、答到点上,不评判对错)。"
    "完全切题=1.0,答非所问=0.0。\n\n"
    "【问题】{question}\n\n【答案】{answer}\n\n"
    '只输出 JSON: {{"score": 0到1的小数, "reason": "简短中文理由"}}'
)


class GenerationJudge:
    def __init__(self, *, agent: Any | None = None) -> None:
        self._agent = agent if agent is not None else BaseAgent(system_prompt=_JUDGE_SYSTEM)

    def faithfulness(self, answer: str, contexts: list[str]) -> float:
        joined = "\n".join(f"- {c}" for c in contexts)
        return self._score(_FAITH_TMPL.format(contexts=joined, answer=answer))

    def answer_relevancy(self, question: str, answer: str) -> float:
        return self._score(_REL_TMPL.format(question=question, answer=answer))

    def _score(self, instruction: str) -> float:
        try:
            raw = self._agent.command(instruction, response_format="json")
            score = float(raw["score"])
        except (KeyError, TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))
