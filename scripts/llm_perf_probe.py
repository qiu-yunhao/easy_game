"""One-shot probe: measure the LLM call bill for story init + one player action.

Run: python scripts/llm_perf_probe.py
Prints a per-agent breakdown and phase totals so we can see whether the ~300s
action latency comes from call count, per-call latency, or fallback/repair double-hits.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_session import SessionConfig, WebGameSession

RECORD_RE = re.compile(r"^LLM (\S+) (\d+)ms( \+fallback)?( \+repair)?")


class BillHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[tuple[str, float, bool, bool]] = []

    def emit(self, record: logging.LogRecord) -> None:
        m = RECORD_RE.match(record.getMessage())
        if not m:
            return
        self.records.append(
            (m.group(1), float(m.group(2)), bool(m.group(3)), bool(m.group(4)))
        )


def summarize(label: str, records: list[tuple[str, float, bool, bool]]) -> None:
    total_ms = sum(r[1] for r in records)
    by_agent_ms: dict[str, float] = defaultdict(float)
    by_agent_n: Counter[str] = Counter()
    fallbacks = sum(1 for r in records if r[2])
    repairs = sum(1 for r in records if r[3])
    for agent, ms, _, _ in records:
        by_agent_ms[agent] += ms
        by_agent_n[agent] += 1
    print(f"\n===== {label} =====")
    print(f"total LLM calls: {len(records)}   total LLM wall: {total_ms/1000:.1f}s")
    print(f"fallback hits: {fallbacks}   repair hits: {repairs}")
    print(f"{'agent':<28}{'calls':>6}{'sum_ms':>10}{'avg_ms':>9}")
    for agent, ms in sorted(by_agent_ms.items(), key=lambda kv: -kv[1]):
        n = by_agent_n[agent]
        print(f"{agent:<28}{n:>6}{ms:>10.0f}{ms/n:>9.0f}")


def main() -> None:
    handler = BillHandler()
    perf_logger = logging.getLogger("llm.perf")
    perf_logger.setLevel(logging.INFO)
    perf_logger.addHandler(handler)
    perf_logger.propagate = False

    session = WebGameSession(SessionConfig(mode="agent-first"))

    print("初始化剧情中(agent-first)…")
    t0 = time.perf_counter()
    session.reset(
        player_profile={
            "name": "性能探针",
            "gender": "未定",
            "race": "人族",
            "spiritual_root": "杂灵根",
            "realm": "练气一层",
            "main_technique": "基础吐纳术",
            "background": "一名用于测量流水线耗时的临时修士。",
            "backpack": [],
        }
    )
    init_wall = time.perf_counter() - t0
    init_records = list(handler.records)
    summarize(f"story init (wall {init_wall:.1f}s)", init_records)

    handler.records.clear()
    print("\n提交一次玩家行动…")

    from Graph.story_cast_nodes import _build_story_cast_signature

    chapter_before = str(session.state["plot"].get("chapter_id", "") or "")
    on_stage_before = list(session.state["scene"].get("on_stage", []))
    sig_before = _build_story_cast_signature(session.state, session.deps)
    cached_sig_before = session.deps.actor_create_signature

    entries: list[dict] = []
    t1 = time.perf_counter()
    session.apply_player_action_streaming(
        "我打量四周，向最近的人拱手问好，试着搭上话。",
        on_event=lambda e: entries.append(e),
    )
    action_wall = time.perf_counter() - t1
    action_records = list(handler.records)
    summarize(f"one player action (wall {action_wall:.1f}s)", action_records)
    print(f"\nstreamed entries this action: {len(entries)}")

    chapter_after = str(session.state["plot"].get("chapter_id", "") or "")
    on_stage_after = list(session.state["scene"].get("on_stage", []))
    sig_after = _build_story_cast_signature(session.state, session.deps)

    print("\n===== ActorCreateAgent trigger check =====")
    print(f"chapter_id:  {chapter_before!r} -> {chapter_after!r}  (changed={chapter_before != chapter_after})")
    print(f"on_stage:    {on_stage_before} -> {on_stage_after}")
    print(f"cached-sig at action start == recomputed-before?  {cached_sig_before == sig_before}")
    print(f"sig(before) == sig(after)?  {sig_before == sig_after}")
    actor_calls = sum(1 for r in action_records if r[0] == "ActorCreateAgent")
    if actor_calls == 0:
        print("verdict: ActorCreateAgent did NOT run this action — cast fully reused.")
    elif chapter_before != chapter_after:
        print("verdict: LIKELY LEGITIMATE — action crossed into a new chapter; cast补建 expected.")
    elif sig_before != sig_after:
        print("verdict: SIGNATURE STILL DRIFTING — a node mutated the cast signature mid-action (residual bug).")
    else:
        print("verdict: SUSPICIOUS — ActorCreateAgent ran but chapter & signature unchanged; investigate.")


if __name__ == "__main__":
    main()
