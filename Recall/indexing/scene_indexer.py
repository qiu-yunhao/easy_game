from __future__ import annotations

from typing import Any, Optional

from Recall.domain.documents import RecallDoc


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


def _tenant_prefix(user_id: int, player_id: int, scene_id: str) -> str:
    """构造带租户隔离的 doc_id 前缀。

    云端多用户下 scene_id 由 chapter+序号拼成、各玩家共用同一套，若不加租户前缀，
    不同玩家的同名场景会生成相同 doc_id，upsert 时互相覆盖造成跨租户数据丢失。
    """
    return f"u{user_id}:p{player_id}:{scene_id}"


def build_scene_summary_doc(
    scene_memory: dict[str, Any],
    *,
    scene_id: str,
    chapter_id: str,
    user_id: int,
    player_id: int,
) -> Optional[RecallDoc]:
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

    return RecallDoc(
        doc_id=f"{_tenant_prefix(user_id, player_id, scene_id)}:scene_summary",
        doc_type="scene_summary",
        user_id=user_id,
        player_id=player_id,
        scene_id=scene_id,
        chapter_id=chapter_id,
        turn_start=turn_start,
        turn_end=turn_end,
        importance=importance,
        text=text,
    )


def build_act_chunk_docs(
    history: list[dict[str, Any]],
    *,
    scene_id: str,
    chapter_id: str,
    user_id: int,
    player_id: int,
    chunk_size: int = 4,
) -> list[RecallDoc]:
    """把一整幕的历史记录按固定条数切块，产出「行动片段」粒度的回忆文档。

    这是细粒度文档，用于回答「某某说过什么细节」这类精确回忆：每 chunk_size 条
    history 合成一块，重要度取块内 importance_score 的最大值（与整幕摘要口径一致，
    避免单条高分台词被同块的过场记录稀释），回合区间取块内首尾回合。

    正文按「角色: content」逐行拼接。只取 content 而不额外拼 spoken_text /
    nonverbal_action：content 是引擎内公认的完整文本表示（History 压缩逻辑也仅依赖
    它），另拼会与 content 内容重复。历史为空时返回空列表。
    """
    size = max(1, int(chunk_size))
    docs: list[RecallDoc] = []
    for index in range(0, len(history), size):
        chunk = history[index : index + size]
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
        docs.append(
            RecallDoc(
                doc_id=f"{_tenant_prefix(user_id, player_id, scene_id)}:act_chunk:{index // size}",
                doc_type="act_chunk",
                user_id=user_id,
                player_id=player_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                turn_start=min(turns) if turns else 0,
                turn_end=max(turns) if turns else 0,
                importance=importance,
                text=text,
            )
        )
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
) -> list[RecallDoc]:
    """索引层对外主入口：把一整幕转换为双粒度回忆文档集合。

    组合「整幕摘要」与若干「行动片段」两类文档，统一挂上场景元数据，供上层一次性
    向量化并写入存储。摘要为空时会被跳过，此时返回列表仅含行动片段文档。
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
    )
    if summary_doc is None:
        return list(chunk_docs)
    return [summary_doc, *chunk_docs]
