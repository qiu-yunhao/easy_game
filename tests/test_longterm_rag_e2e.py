from __future__ import annotations

"""端到端：写侧压缩 → 索引 memory_block → L1 读侧长期召回，走同一个共享向量库。

后台压缩器把旧历史压成 block 并索引进 fake 向量库；随后 L1 actor 的记忆工厂
在同一个 RecallService 上做长期召回，只应召回「已滑出可见窗口且当时在台」的旧 block。
这条链路必须真的把压缩器写入的 block 召回，才算通过（不能因断言被跳过而空过）。

刻意用低重要度内容让压缩产出 summary block（raw_items 为空），正是历史上归属
过滤失效的那条路径：修复后 build_summary_block 计算块级 on_stage_union，
indexer 优先采用该字段，召回才能放行。
"""

from GameState import create_character_runtime_state
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.default_provider import DefaultActorMemoryProvider
from Memory.store import MemoryStore
from Recall.service.recall_service import RecallService
from datatypes import ScoredDoc


class _MemStore:
    """极简 fake 向量库：按 doc_id 存 VectorDoc，忽略向量。"""

    def __init__(self) -> None:
        self.docs: dict[str, object] = {}

    def upsert(self, rows) -> None:
        for doc, _vec in rows:
            self.docs[doc.doc_id] = doc


class _MemHybrid:
    """极简 fake 混合检索：返回库里 doc_type 匹配 filters 的全部文档，score 恒 1。"""

    def __init__(self, store: _MemStore) -> None:
        self._store = store

    def search(self, query, *, top_k=10, filters=None, **kwargs):
        want = (filters or {}).get("doc_type")
        return [
            ScoredDoc(doc=d, score=1.0)
            for d in self._store.docs.values()
            if d.doc_type == want
        ]


class _Emb:
    """极简 fake embedding：每条文本编码成单维零向量。"""

    def encode(self, texts):
        return [[0.0] for _ in texts]


def _snapshot(n):
    # 镜像 tests/test_async_memory_compactor.py 的 known-good 最小快照，
    # 保证 build_history_score_payload 读到的 plot/scene/runtime 字段齐全。
    # tension 用 float 0.0。低重要度内容("line t")→ low 桶 → summary block，
    # raw_items 为空；只有修复后的块级 on_stage_union 才能让召回过滤放行。
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}",
         "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "time_tag": "",
                  "beat": "", "tension": 0.0, "focus_character": ""},
        "runtime": {"turn_index": n, "last_actor": "", "last_mode": ""},
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def _read_state():
    # 读侧 state：turn_index=100 → window_start=max(0,100-45+1)=56，
    # 压缩块 turn_end=5 < 56，落在窗口外 → 命中长期召回。hero 当前在台。
    runtime = create_character_runtime_state(intent="回想旧事")
    return {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": runtime},
        "runtime": {"turn_index": 100},
        "history": [
            {"turn": 100, "actor": "hero", "mode": "speak", "content": "此刻的对话",
             "on_stage": ["hero"], "location_id": "loc"},
        ],
    }


def test_write_then_l1_recall_round_trip():
    store = _MemStore()
    svc = RecallService(embedding=_Emb(), vector_store=store, hybrid=_MemHybrid(store))

    compactor = AsyncMemoryCompactor(
        memory_store=MemoryStore(history_manager=HistoryManager(compression_trigger_size=30)),
        recall_service=svc,
        user_id=1,
        player_id=1,
    )
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        result = compactor.take_pending()
        assert result is not None, "压缩应产出 pending 结果"
        blocks, new_last = result
        assert blocks and new_last == 5
        # 确认走的是 summary block 路径（raw_items 空）——正是历史上归属失效的分支。
        assert any(b["kind"] == "summary" and not b["raw_items"] for b in blocks)
    finally:
        compactor.stop()

    # 压缩块确实被索引进了共享向量库（round-trip 的写侧）。
    assert store.docs, "压缩器应把 memory_block 写入向量库"
    assert all(d.doc_type == "memory_block" for d in store.docs.values())

    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recall_service=svc,
        user_id=1,
        player_id=1,
        recent_rounds=3,
        granularity="on_stage",
        summary_horizon_turns=45,
    )

    ctx = provider.build("hero", _read_state())

    # round-trip 的读侧：L1 actor 从同一个库召回到了压缩器写入的旧 block。
    assert ctx.retrieved, "L1 应召回到压缩器写入的旧 memory_block"
    assert all(r.doc.doc_type == "memory_block" for r in ctx.retrieved)
