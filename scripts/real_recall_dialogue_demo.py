"""真实案例:验证角色对话回忆检索端到端(真 pgvector + 真 bge)。

场景:第一幕里角色「甲」在客栈遇袭并记下此事。若干幕后,甲再次回到客栈,
当前意图「警惕四周」。本脚本走真实回忆栈,验证甲在说话时能语义联想到
「上次在此地遇袭」这段跨幕往事,并出现在 actor prompt 的 recalled_memories。

运行:
  HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 scripts/real_recall_dialogue_demo.py
"""
from __future__ import annotations

import os
import sys

# 让脚本能从项目根导入模块。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_bootstrap import ensure_environment
from Recall.service.factory import build_recall_stack
from db import Database
from db.access import DataAccess
from Memory.default_provider import DefaultActorMemoryProvider
from Actor.ActorFormatter import _build_actor_payload
from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state

USER_ID = 1
PLAYER_ID = 2
SCENE_ID = "scene_inn_01"
CHAPTER_ID = "chapter_01"


def _past_scene() -> dict:
    """第一幕:甲在客栈遇袭。history + scene_memory 供索引成双粒度文档。"""
    return {
        "scene_id": SCENE_ID,
        "chapter_id": CHAPTER_ID,
        "history": [
            {"turn": 1, "actor": "甲", "mode": "speak",
             "content": "这客栈看着安稳,先歇一晚。", "importance_score": 0.3},
            {"turn": 2, "actor": "旁白", "mode": "narrate",
             "content": "夜半三更,两名黑衣蒙面人破窗而入,刀锋直取甲的咽喉。",
             "importance_score": 0.9},
            {"turn": 3, "actor": "甲", "mode": "speak",
             "content": "有刺客!我在这客栈里遭人埋伏遇袭了!", "importance_score": 0.95},
            {"turn": 4, "actor": "旁白", "mode": "narrate",
             "content": "甲奋力格挡,肩头中了一刀,刺客见事败仓皇遁走。",
             "importance_score": 0.85},
        ],
        "scene_memory": {
            "summary": "甲夜宿客栈时遭两名黑衣刺客突袭,肩部受伤,刺客逃走。",
            "key_events": ["甲在客栈遇袭受伤", "两名黑衣刺客夜袭后逃遁"],
            "turn_range": "1-4",
            "compressed_blocks": [{"max_score": 0.95}],
        },
    }


def _current_state() -> dict:
    """若干幕后:甲重回同一客栈,当前意图「警惕四周」,最近一条对话。"""
    runtime = create_character_runtime_state(intent="警惕四周,提防再遭埋伏")
    return {
        "plot": {"chapter_id": CHAPTER_ID, "scene_id": "scene_inn_return",
                 "chapter_goal": "", "plot_flags": {}},
        "runtime": {"next_act": None},
        "scene": {"location_id": "inn", "on_stage": ["甲"]},
        "characters": {"甲": runtime},
        "scene_plan": {},
        "director_brief": {},
        "history": [
            {"turn": 20, "actor": "甲", "mode": "speak",
             "content": "又回到了这家客栈……总觉得哪里不对劲。",
             "on_stage": ["甲"], "location_id": "inn"},
        ],
    }


def main() -> int:
    # LLM 本次不需要(只测检索),跳过 llm 检查;其余真实探测。
    ensure_environment(require_llm=False, require_bge=True)

    recall_url = os.environ["PG_URL"]
    access = DataAccess(save_database=Database(os.environ["MYSQL_URL"]), recall_url=recall_url)
    service, indexer = build_recall_stack(access)
    if service is None:
        print("回忆栈未组装(recall_url 缺失),终止。")
        return 1
    print("[1] 真实回忆栈已组装 (pgvector + bge + trgm sparse)")

    # 索引第一幕(真 embedding + 真入库),幂等,可重复运行。
    service.index_completed_scenes([_past_scene()], user_id=USER_ID, player_id=PLAYER_ID)
    print("[2] 已索引第一幕『客栈遇袭』到向量库 (租户 u1:p2)")

    # provider 接真 service,设租户,构建甲的对话上下文。
    profiles = {"甲": ensure_character_profile({
        "character_id": "甲", "name": "甲", "persona": [], "base_style": "",
        "base_relationship": {}, "secrets": [], "spiritual_root": "", "realm": "炼气一层",
        "main_technique": "", "agent_type": "actor", "story_layer": "core",
        "storage_mode": "inline",
    })}
    provider = DefaultActorMemoryProvider(character_profiles=profiles, recall_service=service)
    provider.set_tenant(user_id=USER_ID, player_id=PLAYER_ID)

    state = _current_state()
    print(f"[3] 甲当前意图: {state['characters']['甲']['intent']!r}")
    print(f"    最近对话: {state['history'][-1]['content']!r}")

    ctx = provider.build("甲", state)
    print(f"\n[4] provider.build 检索到 {len(ctx.retrieved)} 条往事:")
    for i, scored in enumerate(ctx.retrieved, 1):
        print(f"    #{i} score={scored.score:.4f} scene={scored.doc.metadata.get('scene_id')} "
              f"type={scored.doc.doc_type}")
        print(f"        {scored.doc.text!r}")

    payload = _build_actor_payload(state, ctx)
    print(f"\n[5] 注入 actor prompt 的 recalled_memories ({len(payload['recalled_memories'])} 条):")
    for rec in payload["recalled_memories"]:
        print(f"    - [{rec['chapter_id']}/{rec['scene_id']}] score={rec['score']:.4f}")
        print(f"      {rec['text']!r}")

    hit = any("遇袭" in s.doc.text or "刺客" in s.doc.text for s in ctx.retrieved)
    print(f"\n[结果] 甲{'成功' if hit else '未能'}联想到『上次在此地遇袭』这段跨幕往事。")
    return 0 if hit else 2


if __name__ == "__main__":
    raise SystemExit(main())
