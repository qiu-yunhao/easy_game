"""评测 Recall 回忆系统的 RAG 质量(检索 precision/recall + 生成 faithfulness/answer relevancy)。

独立租户 u9001:p9002,只灌入评测场景语料,不污染真实玩家数据。
默认走完整四指标(真 DeepSeek 生成 + 打分);加 --no-generation 降级为只检索两指标,
免 LLM、跑得快,适合快速回归检索质量。

用法:
  # 降级模式(只检索两指标,免 LLM,快)
  HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 \
    scripts/run_rag_eval.py --no-generation --limit 10
  # 完整模式(四指标,真 DeepSeek)
  HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 \
    scripts/run_rag_eval.py
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_bootstrap import ensure_environment
from Recall.service.factory import build_recall_stack
from db import Database
from db.access import DataAccess
from eval_rag.dataset import build_samples, build_scenes
from eval_rag.runner import RecallEvaluator, write_report
from eval_rag.qa_generator import RecallQAGenerator
from eval_rag.generation_metrics import GenerationJudge


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall 回忆系统 RAG 质量评测")
    parser.add_argument("--top-k", type=int, default=10,
                        help="每个样本召回条数(默认 10)")
    parser.add_argument("--limit", type=int, default=0,
                        help="只评测前 N 个样本;0 表示全部")
    parser.add_argument("--report-path", default="docs/rag_eval_report.md",
                        help="Markdown 报告输出路径")
    parser.add_argument("--no-generation", action="store_true",
                        help="降级为只检索两指标,跳过 LLM 生成/打分")
    args = parser.parse_args()

    with_generation = not args.no_generation

    # 生成模式才需要 LLM;bge/MySQL/PG 始终真实探测。
    ensure_environment(require_llm=with_generation, require_bge=True)

    access = DataAccess(
        save_database=Database(os.environ["MYSQL_URL"]),
        recall_url=os.environ["PG_URL"],
    )
    service, _ = build_recall_stack(access)
    if service is None:
        print("回忆栈未组装:PG_URL/recall 库缺失,无法评测,请检查 .env。")
        return 1
    print("[1] 真实回忆栈已组装 (pgvector + bge + trgm sparse)")

    scenes = build_scenes()
    samples = build_samples()
    if args.limit > 0:
        samples = samples[:args.limit]
    print(f"[2] 场景 {len(scenes)} 个,样本 {len(samples)} 条 "
          f"(top_k={args.top_k}, 生成={'开' if with_generation else '关'})")

    if with_generation:
        qa = RecallQAGenerator()
        judge = GenerationJudge()
    else:
        qa = None
        judge = None
    ev = RecallEvaluator(recall_service=service, qa_generator=qa, judge=judge)

    ev.index(scenes)
    print(f"[3] 已索引 {len(scenes)} 个评测场景到向量库 (租户 u9001:p9002)")

    report = ev.evaluate(samples, top_k=args.top_k, with_generation=with_generation)
    print("[4] 逐样本检索/生成打分完成")

    def _fmt(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.3f}"

    print("\n[指标均值]")
    print(f"    context_precision = {_fmt(report.mean_context_precision)}")
    print(f"    context_recall    = {_fmt(report.mean_context_recall)}")
    print(f"    faithfulness      = {_fmt(report.mean_faithfulness)}")
    print(f"    answer_relevancy  = {_fmt(report.mean_answer_relevancy)}")

    print("\n[分档分布]")
    for metric, dist in report.buckets.items():
        parts = "  ".join(f"{k}={v}" for k, v in dist.items())
        print(f"    {metric}: {parts}")

    write_report(report, args.report_path)
    print(f"\n[5] 报告已写入 {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
