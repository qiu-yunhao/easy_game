from History.HistoryCompression import (
    build_raw_block,
    build_summary_block,
    summarize_chunk_payload,
)


def _scored(turn, *, on_stage, actor="hero", bucket="low", score=0.25):
    return {
        "turn": turn,
        "actor": actor,
        "mode": "speak",
        "content": f"line {turn}",
        "on_stage": list(on_stage),
        "location_id": "loc",
        "importance_score": score,
        "importance_bucket": bucket,
        "score_reason": "test",
    }


def _state():
    return {
        "plot": {"plot_flags": {}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "scene": {
            "beat": "",
            "tension": 0.0,
            "focus_character": "",
            "on_stage": ["hero"],
        },
    }


def test_build_raw_block_preserves_on_stage_and_block_union():
    chunk = [
        _scored(1, on_stage=["hero"], bucket="high", score=0.9),
        _scored(2, on_stage=["hero", "npc"], bucket="high", score=0.9),
    ]
    block = build_raw_block(chunk)
    # 逐条 on_stage 被保留在 raw_items 里(存储路径专用 helper)。
    assert block["raw_items"][0]["on_stage"] == ["hero"]
    assert block["raw_items"][1]["on_stage"] == ["hero", "npc"]
    # 块级并集也被填充。
    assert block["on_stage_union"] == ["hero", "npc"]


def test_build_summary_block_populates_on_stage_union_despite_empty_raw_items():
    chunk = [
        _scored(1, on_stage=["hero"]),
        _scored(2, on_stage=["npc"]),
    ]
    summary_result = {"summary": "s", "key_points": ["kp"], "actors": ["hero"]}
    block = build_summary_block(chunk, summary_result)
    # summary 块刻意不留逐条明细,但块级并集非空,才能支撑归属过滤。
    assert block["raw_items"] == []
    assert block["on_stage_union"] == ["hero", "npc"]


def test_summarize_chunk_payload_does_not_leak_on_stage():
    # 守护 split:summarizer 载荷路径不得混入 on_stage,避免污染提示词。
    chunk = [_scored(1, on_stage=["hero"]), _scored(2, on_stage=["npc"])]
    payload = summarize_chunk_payload(_state(), chunk)
    for entry in payload["history_items"]:
        assert "on_stage" not in entry
        assert "location_id" not in entry
