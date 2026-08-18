from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent

"""生成质量指标:LLM-as-judge 评 faithfulness / answer relevancy / answer correctness。

- faithfulness(忠诚度):答案是否只基于上下文、不编造;诚实拒答(无据可依时明说
  「无法确定」)本身不算不忠诚,应判满分。只看有没有编造,不比对标准答案措辞。
- answer relevancy(答案相关性):答案是否真正回答了问题(只看切题,不评对错)。
- answer correctness(答案正确性):系统回答与人工标准答案是否一致(这才评「答对没有」)。
裁判经 BaseAgent(response_format="json")返回 {score,reason};解析失败降级为 0。
"""

_JUDGE_SYSTEM = "你是严格的 RAG 评测裁判,只输出 JSON。"

_FAITH_TMPL = (
    "判断【答案】是否忠于【上下文】——即答案里出现的每条事实主张都能在上下文中找到依据,"
    "没有编造上下文之外的信息(例如上下文写「三到七日到账」而答案说「当日到账」即属编造,应扣分)。\n"
    "两条重要规则:\n"
    "1. 若答案是诚实拒答(如「无法从回忆中确定」「上下文未提及」),这不是编造,反而完全忠于上下文,判 1.0;\n"
    "2. 只评「有没有编造」,不要拿答案去比对任何标准答案的措辞;答案简短或只抽取关键词也不扣分。\n"
    "完全有据或诚实拒答=1.0,大量编造=0.0。\n\n"
    "【上下文】\n{contexts}\n\n【答案】{answer}\n\n"
    '只输出 JSON: {{"score": 0到1的小数, "reason": "简短中文理由"}}'
)

_REL_TMPL = (
    "判断【答案】是否真正回答了【问题】(只看是否切题、答到点上,不评判对错)。"
    "完全切题=1.0,答非所问=0.0。\n\n"
    "【问题】{question}\n\n【答案】{answer}\n\n"
    '只输出 JSON: {{"score": 0到1的小数, "reason": "简短中文理由"}}'
)

_CORRECT_TMPL = (
    "判断【系统答案】与【标准答案】在事实上是否一致(这是评「答对没有」)。"
    "关键事实一致即高分,措辞不同不扣分;遗漏关键信息或答错扣分;"
    "系统答「无法确定」而标准答案有明确内容,视为未答对,应判低分。"
    "完全答对=1.0,完全答错或漏答=0.0。\n\n"
    "【问题】{question}\n\n【系统答案】{answer}\n\n【标准答案】{gold}\n\n"
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

    def answer_correctness(self, question: str, answer: str, gold_answer: str) -> float:
        return self._score(
            _CORRECT_TMPL.format(question=question, answer=answer, gold=gold_answer))

    def _score(self, instruction: str) -> float:
        try:
            raw = self._agent.command(instruction, response_format="json")
            score = float(raw["score"])
        except (KeyError, TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))
