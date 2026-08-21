from __future__ import annotations

from typing import Any

from datatypes import VectorDoc, tenant_prefix

"""压缩块索引层:把 CompressedHistoryBlock 转成 doc_type="memory_block" 的
VectorDoc,与场景级 scene_summary/act_chunk 隔离,并行存在互不干扰。

归属过滤:把块内逐条 on_stage 的并集落 metadata.on_stage_union,召回时只返回
「该角色当时在台」的块,与短期 filter_history_by_presence 在场语义对称。
去重:metadata 带 turn_start/turn_end,召回时按 turn_end < window_start 限定。
幂等 doc_id:tenant 前缀 + turn 区间,重复 upsert 覆盖同一行不产生副本。
"""


def _on_stage_union(block: dict[str, Any]) -> list[str]:
    # 优先用块级 on_stage_union(summary 块无 raw_items 时唯一的归属信号);
    # 缺失时回退到 raw_items 逐条 on_stage 的并集。
    block_level = block.get("on_stage_union")
    if block_level:
        return sorted({str(c).strip() for c in block_level if str(c).strip()})
    union: set[str] = set()
    for item in block.get("raw_items", []) or []:
        for cid in item.get("on_stage", []) or []:
            cid = str(cid or "").strip()
            if cid:
                union.add(cid)
    return sorted(union)


def build_block_docs(
    blocks: list[dict[str, Any]],
    *,
    user_id: int,
    player_id: int,
) -> list[VectorDoc]:
    docs: list[VectorDoc] = []
    prefix = tenant_prefix(user_id, player_id)
    for block in blocks:
        summary = str(block.get("summary", "") or "")
        key_points = [str(p) for p in block.get("key_points", []) or []]
        text = "\n".join([summary, *key_points]).strip()
        if not text:
            continue
        turn_start = int(block.get("turn_start", 0) or 0)
        turn_end = int(block.get("turn_end", turn_start) or turn_start)
        docs.append(
            VectorDoc(
                doc_id=f"{prefix}memory_block:{turn_start}-{turn_end}",
                doc_type="memory_block",
                text=text,
                metadata={
                    "user_id": user_id,
                    "player_id": player_id,
                    "turn_start": turn_start,
                    "turn_end": turn_end,
                    "on_stage_union": _on_stage_union(block),
                    "actors": [str(a) for a in block.get("actors", []) or []],
                    "importance": float(block.get("max_score", 0.0) or 0.0),
                    "recency": float(turn_end),
                },
            )
        )
    return docs
