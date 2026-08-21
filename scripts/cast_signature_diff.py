"""Diagnose why _ensure_story_cast's signature keeps changing between turns,
which defeats its idempotent short-circuit and re-runs ActorCreateAgent (~20s)
on every player action.

Run: python scripts/cast_signature_diff.py
"""
from __future__ import annotations

import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_session import SessionConfig, WebGameSession
from Graph.story_cast_nodes import _build_story_cast_signature


def snap(session):
    return _build_story_cast_signature(session.state, session.deps)


def main() -> None:
    session = WebGameSession(SessionConfig(mode="agent-first"))
    session.reset(
        player_profile={
            "name": "签名探针",
            "gender": "未定",
            "race": "人族",
            "spiritual_root": "杂灵根",
            "realm": "练气一层",
            "main_technique": "基础吐纳术",
            "background": "用于诊断 cast 签名漂移的临时修士。",
            "backpack": [],
        }
    )

    sig_after_init = snap(session)
    cached = session.deps.actor_create_signature
    print("=== after init ===")
    print("cached signature == recomputed?  ->", cached == sig_after_init)

    session.apply_player_action_streaming(
        "我打量四周，向最近的人拱手问好。", on_event=lambda e: None
    )

    sig_after_action = snap(session)
    cached2 = session.deps.actor_create_signature
    print("\n=== after one action ===")
    print("cached signature == recomputed?  ->", cached2 == sig_after_action)
    print("sig(init) == sig(action)?        ->", sig_after_init == sig_after_action)

    if sig_after_init != sig_after_action:
        a = json.dumps(json.loads(sig_after_init), ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        b = json.dumps(json.loads(sig_after_action), ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        print("\n=== signature diff (init -> action) ===")
        for line in difflib.unified_diff(a, b, lineterm="", n=1):
            print(line)


if __name__ == "__main__":
    main()
