"""Diagnose streaming granularity: does one player action emit multiple history
entries progressively over the ~42s, or dump everything at the end (or emit
just one)?

Prints each streamed entry with its arrival time relative to action start, plus
scene on_stage so we can tell whether the scene even has NPCs to respond.

Run: python scripts/stream_granularity_probe.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_session import SessionConfig, WebGameSession


def _brief(entry: dict) -> str:
    speaker = entry.get("speaker") or entry.get("actor") or "?"
    mode = entry.get("mode", "")
    src = entry.get("narration_source", "")
    content = (entry.get("content") or "").replace("\n", " ")
    if len(content) > 40:
        content = content[:40] + "…"
    tag = f"[{mode}{'/' + src if src else ''}]"
    return f"{speaker} {tag} {content}"


def main() -> None:
    session = WebGameSession(SessionConfig(mode="agent-first"))
    session.reset(
        player_profile={
            "name": "流式探针",
            "gender": "未定",
            "race": "人族",
            "spiritual_root": "杂灵根",
            "realm": "练气一层",
            "main_technique": "基础吐纳术",
            "background": "用于诊断流式颗粒度的临时修士。",
            "backpack": [],
        }
    )

    print(f"on_stage after init: {session.state['scene'].get('on_stage', [])}")
    print(f"eligible_actors:     {session.state['runtime'].get('eligible_actors', [])}")
    print(f"opening history len: {len(session.state.get('history', []))}")

    # Track which PlaywrightAgent methods actually fire during the action, so we
    # can tell whether the mid-action Playwright cost is new planning or repeat.
    pw = session.deps.playwright_agent
    pw_calls: list[str] = []
    if pw is not None:
        for meth in ("plan_story_premise", "plan_story_outline_brief",
                     "expand_current_chapter", "generate_scene_candidates"):
            orig = getattr(pw, meth)
            def _wrap(name, fn):
                def inner(*a, **k):
                    pw_calls.append(name)
                    return fn(*a, **k)
                return inner
            setattr(pw, meth, _wrap(meth, orig))

    print("\n提交一次玩家行动… (逐条到达时间戳)")
    t0 = time.perf_counter()
    arrivals: list[tuple[float, str]] = []

    # Time the two main stages of apply_player_action_streaming so we can see
    # whether the 14s lives in resolve_story_turn (player-action narration) or
    # in controller.advance (NPC/Narrator beats after the action).
    stage_times: list[tuple[str, float, float]] = []  # (name, start_dt, dur)
    import Graph.builder as _gb

    _orig_resolve = _gb.resolve_story_turn

    def _timed_resolve(*a, **k):
        s = time.perf_counter() - t0
        r = _orig_resolve(*a, **k)
        stage_times.append(("resolve_story_turn", s, time.perf_counter() - t0 - s))
        return r

    _gb.resolve_story_turn = _timed_resolve
    # web_session imported the symbol directly, so patch it there too.
    import web_session as _ws
    _ws.resolve_story_turn = _timed_resolve

    _controller = session._controller
    _orig_advance = _controller.advance

    def _timed_advance(*a, **k):
        s = time.perf_counter() - t0
        r = _orig_advance(*a, **k)
        stage_times.append(("controller.advance", s, time.perf_counter() - t0 - s))
        return r

    _controller.advance = _timed_advance

    # Break resolve_story_turn into beat_resolution_node vs transition steps.
    _orig_beat = _gb.beat_resolution_node

    def _timed_beat(*a, **k):
        s = time.perf_counter() - t0
        r = _orig_beat(*a, **k)
        stage_times.append(("beat_resolution_node", s, time.perf_counter() - t0 - s))
        return r

    _gb.beat_resolution_node = _timed_beat

    # Break the beat loop into scheduler / execution_subgraph / flush / wrap,
    # then further break execution_subgraph into its 5 HookableNode steps.
    import Graph.beat_subgraph as _bs

    _orig_run_beat_loop = _bs.run_beat_loop

    def _timed_run_beat_loop(state, deps, *, scheduler_step, execution_subgraph,
                             flush_step, wrap_step, group_step=None, on_event=None):
        def _wrap_step(label, fn):
            def inner(cur):
                s = time.perf_counter() - t0
                r = fn(cur)
                stage_times.append((label, s, time.perf_counter() - t0 - s))
                return r
            return inner
        return _orig_run_beat_loop(
            state, deps,
            scheduler_step=_wrap_step("  beat:scheduler", scheduler_step),
            execution_subgraph=_wrap_step("  beat:execution_subgraph", execution_subgraph),
            flush_step=_wrap_step("  beat:flush(narration)", flush_step),
            wrap_step=_wrap_step("  beat:wrap(director)", wrap_step),
            group_step=group_step,
            on_event=on_event,
        )

    _bs.run_beat_loop = _timed_run_beat_loop
    # beat_resolution_node references run_beat_loop via its own module global.
    import Graph.dialogue_nodes as _dn
    _dn.run_beat_loop = _timed_run_beat_loop

    # Break narration flush into generate (Narrator) vs polish (StylisticPolish),
    # and count how many batches the while-loop runs.
    import Graph.narration_nodes as _nn
    narr_calls: list[tuple[str, float]] = []  # (kind, dur)

    _orig_gen = _nn.narration_generate_node

    def _timed_gen(*a, **k):
        s = time.perf_counter()
        r = _orig_gen(*a, **k)
        narr_calls.append(("generate", time.perf_counter() - s))
        return r

    _orig_pol = _nn.narration_polish_node

    def _timed_pol(*a, **k):
        s = time.perf_counter()
        r = _orig_pol(*a, **k)
        narr_calls.append(("polish", time.perf_counter() - s))
        return r

    _nn.narration_generate_node = _timed_gen
    _nn.narration_polish_node = _timed_pol

    # Break execution_subgraph into its 5 HookableNode steps by name, so we can
    # see how much the actor node (player-intent / NPC-line LLM) costs.
    import Graph.beat_nodes as _bn
    node_calls: list[tuple[str, float]] = []  # (node_name, dur)
    for _cls_name in ("DirectorLeadInNode", "ActorNode", "NarrationNode",
                      "CultivationProgressNode", "SceneEndNode"):
        _cls = getattr(_bn, _cls_name)
        _orig_run = _cls.run
        def _mk(orig):
            def _timed_node_run(self, state):
                s = time.perf_counter()
                r = orig(self, state)
                node_calls.append((self.name, time.perf_counter() - s))
                return r
            return _timed_node_run
        _cls.run = _mk(_orig_run)

    # Time hook emits (actor.after / narration.after) to find the ~3.4s gap that
    # lives outside the node.run() calls.
    import Graph.hooks as _hk
    hook_calls: list[tuple[str, float]] = []  # (hook_point, dur)
    _orig_emit = _hk.HookRegistry.emit

    def _timed_emit(self, hook_point, state):
        s = time.perf_counter()
        r = _orig_emit(self, hook_point, state)
        dur = time.perf_counter() - s
        if dur > 0.05:
            hook_calls.append((hook_point, dur))
        return r

    _hk.HookRegistry.emit = _timed_emit



    def on_event(entry: dict) -> None:
        dt = time.perf_counter() - t0
        arrivals.append((dt, _brief(entry)))
        print(f"  +{dt:6.1f}s  {_brief(entry)}")

    session.apply_player_action_streaming(
        "我环顾四周，主动向在场修士开口攀谈，想打听这里的情况。",
        on_event=on_event,
    )
    total = time.perf_counter() - t0

    print(f"\ntotal action wall: {total:.1f}s   entries emitted: {len(arrivals)}")
    if len(arrivals) >= 2:
        gaps = [arrivals[i][0] - arrivals[i - 1][0] for i in range(1, len(arrivals))]
        last_gap_ratio = (total - arrivals[-1][0]) / total if total else 0
        print(f"first entry at +{arrivals[0][0]:.1f}s, last at +{arrivals[-1][0]:.1f}s")
        print(f"inter-entry gaps: {[round(g,1) for g in gaps]}")
        print(f"silent tail after last entry: {total - arrivals[-1][0]:.1f}s ({last_gap_ratio*100:.0f}% of total)")
    print(f"\non_stage after action: {session.state['scene'].get('on_stage', [])}")

    print(f"\nPlaywright calls during action: {len(pw_calls)}")
    from collections import Counter
    for name, n in Counter(pw_calls).items():
        print(f"  {name}: {n}")

    print("\nstage timing (start@ / duration):")
    for name, start_dt, dur in stage_times:
        print(f"  {name}: start +{start_dt:.1f}s  dur {dur:.1f}s")

    print(f"\nnarration LLM calls: {len(narr_calls)}")
    gen = [d for k, d in narr_calls if k == "generate"]
    pol = [d for k, d in narr_calls if k == "polish"]
    print(f"  generate (Narrator):  {len(gen)} calls, total {sum(gen):.1f}s, each {[round(d,1) for d in gen]}")
    print(f"  polish (Stylistic):   {len(pol)} calls, total {sum(pol):.1f}s, each {[round(d,1) for d in pol]}")

    print(f"\nexecution_subgraph node timing ({len(node_calls)} node runs):")
    from collections import defaultdict
    agg: dict[str, list[float]] = defaultdict(list)
    for name, dur in node_calls:
        agg[name].append(dur)
    for name in ("director_lead_in", "actor", "narration", "cultivation_progress", "scene_end"):
        durs = agg.get(name, [])
        if durs:
            print(f"  {name}: {len(durs)} runs, total {sum(durs):.1f}s, each {[round(d,1) for d in durs]}")

    print(f"\nhook emit timing (>0.05s only), {len(hook_calls)} slow emits:")
    hagg: dict[str, list[float]] = defaultdict(list)
    for name, dur in hook_calls:
        hagg[name].append(dur)
    for name, durs in hagg.items():
        print(f"  {name}: {len(durs)} emits, total {sum(durs):.1f}s, each {[round(d,1) for d in durs]}")


if __name__ == "__main__":
    main()
