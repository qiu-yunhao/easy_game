from Recall.indexing.block_indexer import build_block_docs


def _block(turn_start, turn_end, on_stage_per_item):
    return {
        "kind": "summary",
        "bucket": "mid",
        "turn_start": turn_start,
        "turn_end": turn_end,
        "raw_items": [
            {"turn": turn_start + i, "content": f"c{i}", "on_stage": on_stage}
            for i, on_stage in enumerate(on_stage_per_item)
        ],
        "summary": "a summary",
        "key_points": ["kp1", "kp2"],
        "actors": ["hero", "npc"],
        "avg_score": 0.5,
        "max_score": 0.9,
    }


def test_doc_type_and_id_stable():
    block = _block(1, 3, [["hero"], ["hero", "npc"], ["npc"]])
    docs = build_block_docs([block], user_id=7, player_id=2)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_type == "memory_block"
    assert doc.doc_id == "u7:p2:memory_block:1-3"
    again = build_block_docs([block], user_id=7, player_id=2)
    assert again[0].doc_id == doc.doc_id


def test_metadata_carries_turn_bounds_and_on_stage_union():
    block = _block(1, 3, [["hero"], ["hero", "npc"], ["npc"]])
    doc = build_block_docs([block], user_id=7, player_id=2)[0]
    assert doc.metadata["turn_start"] == 1
    assert doc.metadata["turn_end"] == 3
    assert doc.metadata["on_stage_union"] == ["hero", "npc"]
    assert doc.metadata["user_id"] == 7
    assert doc.metadata["player_id"] == 2


def test_text_combines_summary_and_key_points():
    block = _block(1, 2, [["hero"], ["hero"]])
    doc = build_block_docs([block], user_id=1, player_id=1)[0]
    assert "a summary" in doc.text
    assert "kp1" in doc.text


def test_empty_text_block_skipped():
    block = _block(1, 2, [["hero"], ["hero"]])
    block["summary"] = ""
    block["key_points"] = []
    docs = build_block_docs([block], user_id=1, player_id=1)
    assert docs == []
