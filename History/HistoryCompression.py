from __future__ import annotations

from typing import Any, Literal

from GameState import GameState
from History.GameMemory import (
    CompressedHistoryBlock,
    HistoryItem,
    ScoredHistoryItem,
)


def build_history_score_payload(
    state: GameState,
    history_items: list[HistoryItem],
) -> dict[str, Any]:
    return {
        "plot": {
            "chapter_id": state["plot"]["chapter_id"],
            "scene_id": state["plot"]["scene_id"],
            "chapter_goal": state["plot"]["chapter_goal"],
            "plot_flags": state["plot"]["plot_flags"],
        },
        "scene_plan": state["scene_plan"],
        "scene": {
            "location_id": state["scene"]["location_id"],
            "time_tag": state["scene"]["time_tag"],
            "beat": state["scene"]["beat"],
            "tension": state["scene"]["tension"],
            "focus_character": state["scene"]["focus_character"],
            "on_stage": state["scene"]["on_stage"],
            "suppressed": state["scene"].get("suppressed", []),
        },
        "runtime": {
            "turn_index": state["runtime"]["turn_index"],
            "last_actor": state["runtime"]["last_actor"],
            "last_mode": state["runtime"]["last_mode"],
        },
        "history_items": history_items,
    }


def score_to_bucket(score: float) -> Literal["high", "mid", "low"]:
    if score > 0.7:
        return "high"
    if score >= 0.3:
        return "mid"
    return "low"


def merge_scores_with_history(
    history_items: list[HistoryItem],
    score_items: list[dict[str, Any]],
) -> list[ScoredHistoryItem]:
    score_map = {int(item["turn"]): item for item in score_items}
    merged: list[ScoredHistoryItem] = []

    for item in history_items:
        score_info = score_map.get(
            item["turn"],
            {
                "importance_score": 0.5,
                "score_reason": "missing_score_fallback",
            },
        )
        score = float(score_info["importance_score"])
        merged.append(
            {
                **item,
                "importance_score": score,
                "importance_bucket": score_to_bucket(score),
                "score_reason": str(score_info["score_reason"]),
            }
        )

    return merged


def build_compression_chunks(
    scored_items: list[ScoredHistoryItem],
) -> list[list[ScoredHistoryItem]]:
    chunks: list[list[ScoredHistoryItem]] = []
    buffer: list[ScoredHistoryItem] = []
    buffer_bucket: str | None = None

    def flush() -> None:
        nonlocal buffer, buffer_bucket
        if buffer:
            chunks.append(buffer)
            buffer = []
            buffer_bucket = None

    for item in scored_items:
        bucket = item["importance_bucket"]
        if bucket == "high":
            flush()
            chunks.append([item])
            continue

        limit = 5 if bucket == "mid" else 10
        if not buffer or buffer_bucket != bucket or len(buffer) >= limit:
            flush()
            buffer = [item]
            buffer_bucket = bucket
            continue

        buffer.append(item)

    flush()
    return chunks


def _strip_score_fields(item: ScoredHistoryItem) -> HistoryItem:
    return {
        "turn": item["turn"],
        "actor": item["actor"],
        "mode": item["mode"],
        "content": item["content"],
    }


def _strip_score_fields_with_presence(item: ScoredHistoryItem) -> HistoryItem:
    # 存储路径专用:在剥离评分字段的同时保留在场/地点快照,供块索引归属过滤。
    # 不改 _strip_score_fields 本体,以免 on_stage 泄漏进摘要文本与 summarizer 载荷。
    stripped = _strip_score_fields(item)
    on_stage = item.get("on_stage")
    if on_stage:
        stripped["on_stage"] = list(on_stage)
    location_id = item.get("location_id")
    if location_id:
        stripped["location_id"] = location_id
    return stripped


def _chunk_on_stage_union(chunk: list[ScoredHistoryItem]) -> list[str]:
    return sorted({
        str(cid).strip()
        for item in chunk
        for cid in (item.get("on_stage") or [])
        if str(cid).strip()
    })


def _format_history_item(item: HistoryItem) -> str:
    actor = item["actor"] or "system"
    return f"{item['turn']}:{actor}:{item['mode']}:{item['content']}"


def build_raw_block(chunk: list[ScoredHistoryItem]) -> CompressedHistoryBlock:
    actors = [item["actor"] for item in chunk if item["actor"]]
    summary = " / ".join(_format_history_item(_strip_score_fields(item)) for item in chunk[:3])
    if len(chunk) > 3:
        summary = f"{summary} / ..."
    scores = [item["importance_score"] for item in chunk]

    return {
        "kind": "raw",
        "bucket": chunk[0]["importance_bucket"],
        "turn_start": chunk[0]["turn"],
        "turn_end": chunk[-1]["turn"],
        "raw_items": [_strip_score_fields_with_presence(item) for item in chunk],
        "summary": summary,
        "key_points": [_format_history_item(_strip_score_fields(item)) for item in chunk[:3]],
        "actors": list(dict.fromkeys(str(actor) for actor in actors)),
        "avg_score": sum(scores) / len(scores),
        "max_score": max(scores),
        "on_stage_union": _chunk_on_stage_union(chunk),
    }


def summarize_chunk_payload(
    state: GameState,
    chunk: list[ScoredHistoryItem],
) -> dict[str, Any]:
    return {
        "plot": {"plot_flags": state["plot"]["plot_flags"]},
        "scene_plan": state["scene_plan"],
        "scene": {
            "beat": state["scene"]["beat"],
            "tension": state["scene"]["tension"],
            "focus_character": state["scene"]["focus_character"],
            "on_stage": state["scene"]["on_stage"],
        },
        "history_items": [_strip_score_fields(item) for item in chunk],
    }


def build_summary_block(
    chunk: list[ScoredHistoryItem],
    summary_result: dict[str, Any],
) -> CompressedHistoryBlock:
    actors = [str(actor) for actor in summary_result.get("actors", []) if str(actor).strip()]
    if not actors:
        actors = [str(item["actor"]) for item in chunk if item["actor"]]

    key_points = [
        str(point) for point in summary_result.get("key_points", []) if str(point).strip()
    ]
    scores = [item["importance_score"] for item in chunk]

    return {
        "kind": "summary",
        "bucket": chunk[0]["importance_bucket"],
        "turn_start": chunk[0]["turn"],
        "turn_end": chunk[-1]["turn"],
        "raw_items": [],
        "summary": str(summary_result.get("summary", "")).strip(),
        "key_points": key_points,
        "actors": list(dict.fromkeys(actors)),
        "avg_score": sum(scores) / len(scores),
        "max_score": max(scores),
        "on_stage_union": _chunk_on_stage_union(chunk),
    }


def heuristic_score_items(history_items: list[HistoryItem]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in history_items:
        score = 0.25
        content = item["content"]
        if item["mode"] == "event":
            score += 0.25
        if "?" in content:
            score += 0.10
        if len(content) >= 40:
            score += 0.10
        if any(
            token in content.lower()
            for token in ("secret", "truth", "decide", "must", "cannot", "leave", "discover")
        ):
            score += 0.30

        score = max(0.0, min(1.0, score))
        results.append(
            {
                "turn": item["turn"],
                "importance_score": score,
                "score_reason": "heuristic_fallback",
            }
        )
    return results


def heuristic_chunk_summary(chunk: list[ScoredHistoryItem]) -> dict[str, Any]:
    key_points = [_format_history_item(_strip_score_fields(item)) for item in chunk[:3]]
    actors = [str(item["actor"]) for item in chunk if item["actor"]]
    summary = " / ".join(key_points)
    return {
        "summary": summary,
        "key_points": key_points,
        "actors": list(dict.fromkeys(actors)),
    }
