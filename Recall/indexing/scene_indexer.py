from __future__ import annotations

from typing import Any, Optional

from datatypes import VectorDoc, tenant_prefix

"""场景索引层：把一整幕游戏历史转换为可入库的 ``VectorDoc`` 双粒度文档。

对齐基础模块的通用契约 ``datatypes.VectorDoc``：稳定字段只留 doc_id / doc_type /
text，业务字段（user_id/player_id/scene_id/chapter_id/turn_start/turn_end/
importance/recency）统一下沉到 ``metadata``，供 ``PgVectorStore`` 入库、
``HybridRetrieval`` 过滤与重排消费。租户前缀复用 ``datatypes.tenant_prefix``，
不再各自实现。
"""


def _parse_turn_range(turn_range: str) -> tuple[int, int]:
    """解析 ``SceneMemory.turn_range`` 字符串为起止回合元组。

    支持两种形态：区间 "10-15" 解析为 (10, 15)；单回合 "12" 解析为 (12, 12)。
    容错：格式非法或缺失时返回 (0, 0)，避免上层因脏数据崩溃。
    """
    raw = str(turn_range or "").strip()
    if not raw:
        return (0, 0)
    parts = raw.split("-")
    try:
        if len(parts) == 1:
            single = int(parts[0])
            return (single, single)
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
    except (TypeError, ValueError):
        return (0, 0)
    return (0, 0)


def _build_metadata(
    *,
    user_id: int,
    player_id: int,
    scene_id: str,
    chapter_id: str,
    turn_start: int,
    turn_end: int,
    importance: float,
) -> dict[str, Any]:
    """组装 ``VectorDoc.metadata``，集中一处保证各粒度文档字段口径一致。

    recency（新近度）在索引期先取 ``turn_end`` 作单调代理——回合越大越新；
    真正的相对衰减需要「当前 turn」，只能在查询期计算，届时可覆盖此值。
    """
    return {
        "user_id": user_id,
        "player_id": player_id,
        "scene_id": scene_id,
        "chapter_id": chapter_id,
        "turn_start": turn_start,
        "turn_end": turn_end,
        "importance": importance,
        "recency": float(turn_end),
    }


def build_scene_summary_doc(
    scene_memory: dict[str, Any],
    *,
    scene_id: str,
    chapter_id: str,
    user_id: int,
    player_id: int,
) -> Optional[VectorDoc]:
    """把一整幕的 SceneMemory 压缩为一条「整幕摘要」粒度的回忆文档。

    这是粗粒度文档，用于回答「我经历过什么」这类概括性回忆：正文取场景摘要
    加关键事件，重要度取各压缩块 max_score 的最大值，作为整幕的显著度代表。

    当 summary 与 key_events 均为空时返回 None——空文本向量化毫无意义，且会向
    检索结果注入无内容的召回项，故直接跳过。
    """
    summary = str(scene_memory.get("summary", "") or "")
    key_events = [str(e) for e in scene_memory.get("key_events", []) or []]
    text = "\n".join([summary, *key_events]).strip()
    if not text:
        return None

    blocks = scene_memory.get("compressed_blocks", []) or []
    importance = max((float(b.get("max_score", 0.0) or 0.0) for b in blocks), default=0.0)

    turn_start, turn_end = _parse_turn_range(scene_memory.get("turn_range", ""))

    return VectorDoc(
        doc_id=f"{tenant_prefix(user_id, player_id)}{scene_id}:scene_summary",
        doc_type="scene_summary",
        text=text,
        metadata=_build_metadata(
            user_id=user_id,
            player_id=player_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            turn_start=turn_start,
            turn_end=turn_end,
            importance=importance,
        ),
    )


def build_act_chunk_docs(
    history: list[dict[str, Any]],
    *,
    scene_id: str,
    chapter_id: str,
    user_id: int,
    player_id: int,
    chunk_size: int = 4,
    step: int | None = None,
) -> list[VectorDoc]:
    """把一整幕的历史记录按固定条数切块，产出「行动片段」粒度的回忆文档。

    这是细粒度文档，用于回答「某某说过什么细节」这类精确回忆：每 chunk_size 条
    history 合成一块，重要度取块内 importance_score 的最大值（与整幕摘要口径一致，
    避免单条高分台词被同块的过场记录稀释），回合区间取块内首尾回合。

    正文按「角色: content」逐行拼接。只取 content 而不额外拼 spoken_text /
    nonverbal_action：content 是引擎内公认的完整文本表示（History 压缩逻辑也仅依赖
    它），另拼会与 content 内容重复。历史为空时返回空列表。

    step 为滑动步长：默认(None)等于 chunk_size，即相邻块不重叠(历史行为)；step <
    chunk_size 时相邻块共享 chunk_size-step 条 history，让跨块的连续/双向语义被同一
    窗口完整覆盖，减少边界割裂导致的回忆漏召。doc_id 用窗口顺序号，重叠下不碰撞；
    末尾内容已被前一窗口完全覆盖的子集窗口不再产出，避免冗余块。
    """
    size = max(1, int(chunk_size))
    stride = max(1, int(step)) if step is not None else size
    n = len(history)
    docs: list[VectorDoc] = []
    seq = 0
    for index in range(0, n, stride):
        chunk = history[index : index + size]
        if not chunk:
            break
        turns = [int(item.get("turn", 0) or 0) for item in chunk]
        scores = [
            float(item.get("importance_score", 0.0) or 0.0)
            for item in chunk
            if "importance_score" in item
        ]
        importance = max(scores) if scores else 0.0
        text = "\n".join(
            f"{item.get('actor') or '旁白'}: {item.get('content', '') or ''}"
            for item in chunk
        )
        turn_start = min(turns) if turns else 0
        turn_end = max(turns) if turns else 0
        docs.append(
            VectorDoc(
                doc_id=f"{tenant_prefix(user_id, player_id)}{scene_id}:act_chunk:{seq}",
                doc_type="act_chunk",
                text=text,
                metadata=_build_metadata(
                    user_id=user_id,
                    player_id=player_id,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    turn_start=turn_start,
                    turn_end=turn_end,
                    importance=importance,
                ),
            )
        )
        seq += 1
        if index + size >= n:
            break  # 已覆盖到末尾，后续起点只会产出被本窗口包含的子集
    return docs


def build_scene_docs(
    *,
    history: list[dict[str, Any]],
    scene_memory: dict[str, Any],
    scene_id: str,
    chapter_id: str,
    user_id: int,
    player_id: int,
    chunk_size: int = 4,
    step: int | None = None,
) -> list[VectorDoc]:
    """索引层对外主入口：把一整幕转换为双粒度回忆文档集合。

    组合「整幕摘要」与若干「行动片段」两类文档，统一挂上场景元数据，供上层一次性
    向量化并写入存储。摘要为空时会被跳过，此时返回列表仅含行动片段文档。

    step 透传给 build_act_chunk_docs：默认(None)act_chunk 不重叠；传入更小的 step
    可让行动片段滑动重叠，减少跨块语义割裂。
    """
    summary_doc = build_scene_summary_doc(
        scene_memory,
        scene_id=scene_id,
        chapter_id=chapter_id,
        user_id=user_id,
        player_id=player_id,
    )
    chunk_docs = build_act_chunk_docs(
        history,
        scene_id=scene_id,
        chapter_id=chapter_id,
        user_id=user_id,
        player_id=player_id,
        chunk_size=chunk_size,
        step=step,
    )
    if summary_doc is None:
        return list(chunk_docs)
    return [summary_doc, *chunk_docs]
