"""回忆(Recall)评测编排器:把检索指标与生成指标串起来,对回忆服务逐样本打分并汇总。

流程:先把评测场景语料灌入 recall 服务(独立租户 u9001:p9002),再对每条 QA 样本
调用 query_recall 得到召回,计算 context precision/recall;可选地用 qa_generator
生成答案、用 judge 打 faithfulness / answer_relevancy。最后聚合成 EvalReport
(四项指标均值 + 分桶分布),可用 write_report 导出 Markdown。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eval_rag.dataset import (
    EVAL_PLAYER_ID, EVAL_USER_ID, EvalSample, EvalScene,
)
from eval_rag.retrieval_metrics import (
    context_precision, context_recall, context_recall_grouped,
)

_METRICS = ("context_precision", "context_recall",
            "faithfulness", "answer_relevancy", "answer_correctness")


@dataclass
class SampleResult:
    question: str
    scene_id: str
    gold_answer: str
    retrieved_ids: list[str]
    contexts: list[str]
    answer: str | None
    context_precision: float
    context_recall: float
    faithfulness: float | None
    answer_relevancy: float | None
    answer_correctness: float | None


@dataclass
class EvalReport:
    samples: list[SampleResult]
    mean_context_precision: float
    mean_context_recall: float
    mean_faithfulness: float | None
    mean_answer_relevancy: float | None
    mean_answer_correctness: float | None
    buckets: dict = field(default_factory=dict)


def _bucket(value: float) -> str:
    if value < 0.5:
        return "<0.5"
    if value <= 0.8:
        return "0.5-0.8"
    return ">0.8"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _distribution(values: list[float]) -> dict[str, int]:
    counts = {"<0.5": 0, "0.5-0.8": 0, ">0.8": 0}
    for v in values:
        counts[_bucket(v)] += 1
    return counts


class RecallEvaluator:
    """对回忆服务做端到端评测:灌库 → 逐样本检索/生成打分 → 汇总报告。"""

    def __init__(self, *, recall_service, qa_generator=None, judge=None):
        self._recall = recall_service
        self._qa = qa_generator
        self._judge = judge

    def index(self, scenes: list[EvalScene], *, step: int | None = None) -> None:
        dicts = [
            {
                "scene_id": s.scene_id,
                "chapter_id": s.chapter_id,
                "history": s.history,
                "scene_memory": s.scene_memory,
            }
            for s in scenes
        ]
        self._recall.index_completed_scenes(
            dicts, user_id=EVAL_USER_ID, player_id=EVAL_PLAYER_ID, step=step)

    def evaluate(
        self,
        samples: list[EvalSample],
        *,
        top_k: int = 10,
        with_generation: bool = True,
    ) -> EvalReport:
        results: list[SampleResult] = []
        gen_on = bool(with_generation and self._qa and self._judge)
        for sample in samples:
            scored = self._recall.query_recall(
                sample.question,
                user_id=EVAL_USER_ID,
                player_id=EVAL_PLAYER_ID,
                top_k=top_k,
            )
            retrieved_ids = [s.doc.doc_id for s in scored]
            contexts = [s.doc.text for s in scored]
            precision = context_precision(retrieved_ids, sample.gold_doc_ids)
            # 有分组时按 any-hit（重叠邻窗组内命中任一即覆盖）；无分组退化为扁平集合召回。
            if sample.gold_groups:
                recall = context_recall_grouped(retrieved_ids, sample.gold_groups)
            else:
                recall = context_recall(retrieved_ids, sample.gold_doc_ids)

            if gen_on:
                answer = self._qa.answer(sample.question, contexts)
                faith = self._judge.faithfulness(answer, contexts)
                rel = self._judge.answer_relevancy(sample.question, answer)
                correct = self._judge.answer_correctness(
                    sample.question, answer, sample.gold_answer)
            else:
                answer = None
                faith = None
                rel = None
                correct = None

            results.append(SampleResult(
                question=sample.question,
                scene_id=sample.scene_id,
                gold_answer=sample.gold_answer,
                retrieved_ids=retrieved_ids,
                contexts=contexts,
                answer=answer,
                context_precision=precision,
                context_recall=recall,
                faithfulness=faith,
                answer_relevancy=rel,
                answer_correctness=correct,
            ))
        return self.summarize(results, with_generation=gen_on)

    def summarize(
        self, results: list[SampleResult], *, with_generation: bool
    ) -> EvalReport:
        precisions = [r.context_precision for r in results]
        recalls = [r.context_recall for r in results]
        faiths = [r.faithfulness for r in results if r.faithfulness is not None]
        rels = [r.answer_relevancy for r in results if r.answer_relevancy is not None]
        corrects = [r.answer_correctness for r in results if r.answer_correctness is not None]

        buckets: dict[str, dict[str, int]] = {
            "context_precision": _distribution(precisions),
            "context_recall": _distribution(recalls),
        }
        if with_generation:
            buckets["faithfulness"] = _distribution(faiths)
            buckets["answer_relevancy"] = _distribution(rels)
            buckets["answer_correctness"] = _distribution(corrects)

        return EvalReport(
            samples=results,
            mean_context_precision=_mean(precisions),
            mean_context_recall=_mean(recalls),
            mean_faithfulness=_mean(faiths) if with_generation else None,
            mean_answer_relevancy=_mean(rels) if with_generation else None,
            mean_answer_correctness=_mean(corrects) if with_generation else None,
            buckets=buckets,
        )


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _truncate(text: str, limit: int = 80) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def write_report(report: EvalReport, path: str) -> None:
    lines: list[str] = []
    lines.append("# Recall 评测报告")
    lines.append("")
    lines.append(f"样本数: {len(report.samples)}")
    lines.append("")

    lines.append("## 指标均值")
    lines.append("")
    lines.append("| 指标 | 均值 |")
    lines.append("| --- | --- |")
    lines.append(f"| context_precision | {_fmt(report.mean_context_precision)} |")
    lines.append(f"| context_recall | {_fmt(report.mean_context_recall)} |")
    lines.append(f"| faithfulness | {_fmt(report.mean_faithfulness)} |")
    lines.append(f"| answer_relevancy | {_fmt(report.mean_answer_relevancy)} |")
    lines.append(f"| answer_correctness | {_fmt(report.mean_answer_correctness)} |")
    lines.append("")

    lines.append("## 分数分布")
    lines.append("")
    for metric in _METRICS:
        dist = report.buckets.get(metric)
        if not dist:
            continue
        lines.append(f"### {metric}")
        lines.append("")
        lines.append("| 区间 | 数量 |")
        lines.append("| --- | --- |")
        for bucket in ("<0.5", "0.5-0.8", ">0.8"):
            lines.append(f"| {bucket} | {dist.get(bucket, 0)} |")
        lines.append("")

    lines.append("## 逐样本明细")
    lines.append("")
    for i, r in enumerate(report.samples, 1):
        lines.append(f"### 样本 {i}: {r.question}")
        lines.append("")
        lines.append(f"- scene_id: {r.scene_id}")
        lines.append(f"- retrieved_ids: {r.retrieved_ids}")
        lines.append("- contexts:")
        for c in r.contexts:
            lines.append(f"  - {_truncate(c)}")
        lines.append(f"- 标准答案(gold): {r.gold_answer}")
        lines.append(f"- 系统回答(answer): {r.answer if r.answer is not None else 'N/A'}")
        lines.append(f"- context_precision: {_fmt(r.context_precision)}")
        lines.append(f"- context_recall: {_fmt(r.context_recall)}")
        lines.append(f"- faithfulness: {_fmt(r.faithfulness)}")
        lines.append(f"- answer_relevancy: {_fmt(r.answer_relevancy)}")
        lines.append(f"- answer_correctness: {_fmt(r.answer_correctness)}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
