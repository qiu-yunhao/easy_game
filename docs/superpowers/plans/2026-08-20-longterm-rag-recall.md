# Long-term RAG Recall (L1 only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist compressed history blocks to pgvector as `doc_type="memory_block"` with per-item `on_stage` attribution metadata, and make long-term memory = objective RAG recall of those blocks — filtered by attribution (the actor was on-stage) and bounded by turn (only blocks that slid out of the visible window), wired into Pipeline A's `retrieved` and enabled for L1 characters only.

**Architecture:** Step 2's `AsyncMemoryCompactor` produces `CompressedHistoryBlock`s. This plan adds (1) `build_block_docs` mapping each block to a `VectorDoc` with `doc_type="memory_block"` and per-item `on_stage` snapshots in metadata; (2) upsert on the compactor's success path (parallel to `AsyncSceneIndexer`, isolated by doc_type); (3) a `recall_memory_blocks` query on `RecallService` that filters by tenant + `doc_type="memory_block"` + `turn_end < window_start` (turn-bound dedup vs. the visible window) + on-stage attribution; (4) provider wiring so L1 actors get `retrieved` populated, NPC-Actors get `[]`.

**Tech Stack:** Python 3.12, pgvector via existing `RecallService`/`PgVectorStore`/`HybridRetrieval`, pytest with fake vector store. No new dependencies. Reuses `datatypes.VectorDoc`, `datatypes.tenant_prefix`.

**Reference spec:** `docs/superpowers/specs/2026-08-20-memory-architecture-consolidation-design.md` sections 4.2 (long-term = RAG, L1 only), 4.4 (objective RAG, per-item on_stage attribution, turn-bound dedup), 5 (step 3). Also `docs/superpowers/specs/2026-08-20-async-memory-compaction-longterm-rag-design.md` units 3–4.

**Depends on:** `2026-08-20-memory-factory-consolidation.md` (Step 1 — `ActorMemoryContext` shape, L1 tier) and `2026-08-20-async-memory-compaction.md` (Step 2 — `AsyncMemoryCompactor`, `CompressedHistoryBlock` production). Both must land first.

---

## File Structure

**Create:**
- `Recall/indexing/block_indexer.py` — `build_block_docs(blocks, *, user_id, player_id) -> list[VectorDoc]` with `doc_type="memory_block"`, per-item `on_stage` in metadata, idempotent `doc_id`.
- `tests/test_block_indexer.py`
- `tests/test_recall_memory_blocks.py`
- `tests/test_provider_l1_recall.py`

**Modify:**
- `Recall/service/recall_service.py` — add `index_memory_blocks(...)` and `recall_memory_blocks(query, *, user_id, player_id, actor_id, window_start, on_stage_of, top_k)`.
- `History/AsyncMemoryCompactor.py` — on success, also upsert block docs to the recall service (optional injection; degrade if absent).
- `Memory/default_provider.py` — `retrieve` becomes L1-gated and routes to `recall_memory_blocks` with `window_start` + attribution; NPC-Actor returns `[]`.

---

## Task 1: build_block_docs — compressed blocks → memory_block VectorDocs

**Files:**
- Create: `Recall/indexing/block_indexer.py`
- Test: `tests/test_block_indexer.py`

**Context:** A `CompressedHistoryBlock` has `raw_items` (each a `HistoryItem` carrying per-item `on_stage`), `summary`, `key_points`, `actors`, `turn_start`, `turn_end`, `max_score`. The doc text = summary + key_points; metadata carries the union of per-item `on_stage` for attribution AND the per-item on_stage list so recall can filter by "was this actor on-stage during any covered turn". Idempotent `doc_id` = tenant prefix + turn range.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_block_indexer.py
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
    # re-running yields the same id (idempotent upsert)
    again = build_block_docs([block], user_id=7, player_id=2)
    assert again[0].doc_id == doc.doc_id


def test_metadata_carries_turn_bounds_and_on_stage_union():
    block = _block(1, 3, [["hero"], ["hero", "npc"], ["npc"]])
    doc = build_block_docs([block], user_id=7, player_id=2)[0]
    assert doc.metadata["turn_start"] == 1
    assert doc.metadata["turn_end"] == 3
    # union of per-item on_stage, sorted, for attribution filtering
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_block_indexer.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement build_block_docs**

```python
# Recall/indexing/block_indexer.py
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
            continue  # 空文本向量化无意义,跳过
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_block_indexer.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add Recall/indexing/block_indexer.py tests/test_block_indexer.py
git commit -m "feat(recall): build_block_docs — compressed blocks to memory_block VectorDocs"
```

---

## Task 2: RecallService.index_memory_blocks + recall_memory_blocks

**Files:**
- Modify: `Recall/service/recall_service.py`
- Test: `tests/test_recall_memory_blocks.py`

**Context:** `index_memory_blocks` mirrors `index_completed_scenes` but uses `build_block_docs`. `recall_memory_blocks` is a single-stage search (blocks are already summary-grained — no coarse/fine split): filter tenant + `doc_type="memory_block"`, then in Python drop any hit with `turn_end >= window_start` (turn-bound dedup) or whose `on_stage_union` excludes `actor_id` (attribution). Because `PgVectorStore` filters are single-value equality, turn-bound and on-stage filtering happen post-search in the service.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recall_memory_blocks.py
from datatypes import VectorDoc, ScoredDoc
from Recall.service.recall_service import RecallService


class _FakeHybrid:
    def __init__(self, docs):
        self._docs = docs

    def search(self, query, *, top_k=10, filters=None, weights=None, fetch_k=200):
        # returns everything matching doc_type; ignores semantic scoring for the test
        return [ScoredDoc(doc=d, score=1.0) for d in self._docs if d.metadata.get("doc_type_match", True)]


class _FakeEmbedding:
    def encode(self, texts):
        return [[0.0] for _ in texts]


class _FakeStore:
    def __init__(self):
        self.rows = []

    def upsert(self, rows):
        self.rows.extend(rows)


def _doc(turn_start, turn_end, on_stage_union):
    return VectorDoc(
        doc_id=f"u1:p1:memory_block:{turn_start}-{turn_end}",
        doc_type="memory_block",
        text="t",
        metadata={"turn_start": turn_start, "turn_end": turn_end, "on_stage_union": on_stage_union},
    )


def test_recall_excludes_visible_window_and_offstage():
    docs = [
        _doc(1, 3, ["hero"]),     # old + hero on-stage → recalled
        _doc(4, 6, ["npc"]),      # old but hero NOT on-stage → filtered
        _doc(40, 45, ["hero"]),   # inside visible window → filtered by turn bound
    ]
    svc = RecallService(embedding=_FakeEmbedding(), vector_store=_FakeStore(), hybrid=_FakeHybrid(docs))
    results = svc.recall_memory_blocks(
        "q", user_id=1, player_id=1, actor_id="hero", window_start=40, top_k=10
    )
    ids = [r.doc.doc_id for r in results]
    assert ids == ["u1:p1:memory_block:1-3"]


def test_index_memory_blocks_upserts():
    store = _FakeStore()
    svc = RecallService(embedding=_FakeEmbedding(), vector_store=store, hybrid=_FakeHybrid([]))
    block = {
        "turn_start": 1, "turn_end": 2, "summary": "s", "key_points": ["k"],
        "actors": ["hero"], "raw_items": [{"turn": 1, "on_stage": ["hero"]}], "max_score": 0.5,
    }
    svc.index_memory_blocks([block], user_id=1, player_id=1)
    assert len(store.rows) == 1
    assert store.rows[0][0].doc_type == "memory_block"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recall_memory_blocks.py -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement the two methods**

Add the import at the top of `Recall/service/recall_service.py`:

```python
from Recall.indexing.block_indexer import build_block_docs
```

Add to `RecallService`:

```python
    def index_memory_blocks(
        self,
        blocks: Sequence[dict[str, Any]],
        *,
        user_id: int,
        player_id: int,
    ) -> None:
        """把压缩块批量索引进向量库(doc_type=memory_block,与场景级隔离)。"""
        docs = build_block_docs(list(blocks), user_id=user_id, player_id=player_id)
        if not docs:
            return
        vectors = self._embedding.encode([doc.text for doc in docs])
        self._vector_store.upsert(list(zip(docs, vectors)))

    def recall_memory_blocks(
        self,
        query: str,
        *,
        user_id: int,
        player_id: int,
        actor_id: str,
        window_start: int,
        top_k: int = 5,
    ) -> list[ScoredDoc]:
        """长期召回:只返回滑出可见窗口(turn_end < window_start)且该角色当时在台
        (on_stage_union 含 actor_id)的压缩块。归属 + turn 双过滤在服务层完成,
        因为 PgVectorStore 只支持单值等值 filter。检索失败/无命中返回空。
        """
        tenant_filters = {"user_id": user_id, "player_id": player_id}
        hits = self._hybrid.search(
            query,
            top_k=max(top_k * 4, top_k),  # 多取,过滤后截断
            filters={**tenant_filters, "doc_type": "memory_block"},
        )
        results: list[ScoredDoc] = []
        for scored in hits:
            meta = scored.doc.metadata or {}
            turn_end = int(meta.get("turn_end", 0) or 0)
            if turn_end >= window_start:
                continue  # 落在可见窗口内,短期已覆盖,去重
            on_stage_union = meta.get("on_stage_union", []) or []
            if actor_id not in on_stage_union:
                continue  # 该角色当时不在台,不该记得
            results.append(scored)
        results.sort(key=lambda s: s.score, reverse=True)
        return results[:top_k]
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_recall_memory_blocks.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add Recall/service/recall_service.py tests/test_recall_memory_blocks.py
git commit -m "feat(recall): index + recall memory_blocks with turn-bound + on-stage attribution"
```

---

## Task 3: Upsert block docs on compaction success

**Files:**
- Modify: `History/AsyncMemoryCompactor.py`
- Test: `tests/test_compactor_indexes_blocks.py`

**Context:** The compactor already produces blocks in `_run`. Inject an optional recall service + tenant; on success, upsert the *newly produced* blocks (those with `turn_end > previous last_compressed_turn`). Degrade silently if no service/tenant. Only new blocks are indexed to avoid re-embedding old ones (idempotent doc_id makes re-index harmless but wasteful).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compactor_indexes_blocks.py
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager


class _RecordingRecall:
    def __init__(self):
        self.indexed = []

    def index_memory_blocks(self, blocks, *, user_id, player_id):
        self.indexed.append((list(blocks), user_id, player_id))


def _snapshot(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1"},
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "runtime": {"turn_index": n},
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_compactor_indexes_new_blocks_on_success():
    recall = _RecordingRecall()
    compactor = AsyncMemoryCompactor(
        history_manager=HistoryManager(compression_trigger_size=30),
        recall_service=recall,
        user_id=1,
        player_id=1,
    )
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        compactor.take_pending()
        assert recall.indexed  # at least one index call happened
        blocks, uid, pid = recall.indexed[0]
        assert blocks and uid == 1 and pid == 1
    finally:
        compactor.stop()


def test_compactor_without_recall_still_works():
    compactor = AsyncMemoryCompactor(history_manager=HistoryManager(compression_trigger_size=30))
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        assert compactor.take_pending() is not None  # no crash without recall service
    finally:
        compactor.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compactor_indexes_blocks.py -v`
Expected: FAIL — `AsyncMemoryCompactor.__init__` does not accept `recall_service`.

- [ ] **Step 3: Add optional recall injection + upsert on success**

In `History/AsyncMemoryCompactor.py`, update `__init__`:

```python
    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        recall_service: Any = None,
        user_id: Optional[int] = None,
        player_id: Optional[int] = None,
    ) -> None:
        self._manager = history_manager
        self._recall = recall_service
        self._user_id = user_id
        self._player_id = player_id
        self._queue = queue.Queue()
        self._pending = None
        self._lock = threading.Lock()
        self._worker = None
        self._started = False
```

Add a `set_tenant` mirror (session may bind tenant after construction):

```python
    def set_tenant(self, *, user_id: Optional[int], player_id: Optional[int]) -> None:
        self._user_id = user_id
        self._player_id = player_id
```

In `_run`, after computing `blocks, new_last`, index the newly produced blocks (those beyond the snapshot's prior cursor) before storing pending:

```python
                prior_cursor = int(snapshot["memory"]["last_compressed_turn"])
                blocks, new_last = self._manager.compact_snapshot(snapshot)
                self._index_new_blocks(blocks, prior_cursor)
                with self._lock:
                    self._pending = (blocks, new_last)
```

Add the helper:

```python
    def _index_new_blocks(self, blocks: list[Any], prior_cursor: int) -> None:
        if self._recall is None or self._user_id is None or self._player_id is None:
            return
        new_blocks = [b for b in blocks if int(b.get("turn_end", 0) or 0) > prior_cursor]
        if not new_blocks:
            return
        try:
            self._recall.index_memory_blocks(
                new_blocks, user_id=self._user_id, player_id=self._player_id
            )
        except Exception:  # 索引失败不影响压缩结果落地
            _logger.exception("memory_block 索引失败")
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_compactor_indexes_blocks.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add History/AsyncMemoryCompactor.py tests/test_compactor_indexes_blocks.py
git commit -m "feat(recall): compactor upserts new memory_blocks to pgvector on success"
```

---

## Task 4: L1-gated recall in the provider

**Files:**
- Modify: `Memory/default_provider.py`
- Test: `tests/test_provider_l1_recall.py`

**Context:** After Step 1, the provider's `retrieve` degrades to `[]` when no service. Now: for L1 actors with a service + tenant, call `recall_memory_blocks` with the computed `window_start` and `actor_id` attribution. NPC-Actors always get `[]` (spec 4.2: NPC has no long-term). `window_start = max(0, turn_index - summary_horizon_turns + 1)` — must match `get_visible_blocks`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_l1_recall.py
from datatypes import VectorDoc, ScoredDoc
from Memory.default_provider import DefaultActorMemoryProvider


class _StubRecall:
    def __init__(self):
        self.calls = []

    def recall_memory_blocks(self, query, *, user_id, player_id, actor_id, window_start, top_k=5):
        self.calls.append({"actor_id": actor_id, "window_start": window_start})
        return [ScoredDoc(doc=VectorDoc(doc_id="d1", doc_type="memory_block", text="old", metadata={}), score=1.0)]


def _state(turn_index=100):
    return {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": {"intent": "explore", "memory": {"player_memory": {}}}},
        "history": [{"turn": 99, "actor": "hero", "content": "recent", "on_stage": ["hero"], "location_id": "loc"}],
        "runtime": {"turn_index": turn_index},
    }


def test_l1_gets_recall_with_correct_window_start():
    recall = _StubRecall()
    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recent_rounds=3,
        recall_service=recall,
        user_id=1,
        player_id=1,
        summary_horizon_turns=45,
    )
    ctx = provider.build("hero", _state(turn_index=100))
    assert ctx.retrieved  # L1 gets recalled blocks
    assert recall.calls[0]["actor_id"] == "hero"
    assert recall.calls[0]["window_start"] == max(0, 100 - 45 + 1)  # == 56


def test_npc_gets_no_recall():
    recall = _StubRecall()
    provider = DefaultActorMemoryProvider(
        character_profiles={"npc": {"agent_type": "actor", "memory_profile": {}}},
        recent_rounds=3,
        recall_service=recall,
        user_id=1,
        player_id=1,
        summary_horizon_turns=45,
    )
    state = {
        "scene": {"location_id": "loc", "on_stage": ["npc"]},
        "characters": {"npc": {"intent": "", "memory": {"player_memory": {}}}},
        "history": [{"turn": 1, "actor": "npc", "content": "x", "on_stage": ["npc"], "location_id": "loc"}],
        "runtime": {"turn_index": 100},
    }
    ctx = provider.build("npc", state)
    assert ctx.retrieved == []
    assert recall.calls == []  # NPC never queries long-term
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_provider_l1_recall.py -v`
Expected: FAIL — provider `__init__` lacks `summary_horizon_turns`; `retrieve` still calls `query_recall` (two-stage scene recall) instead of `recall_memory_blocks`, and is not L1-gated.

- [ ] **Step 3: Update the provider**

In `Memory/default_provider.py`:

Add `summary_horizon_turns` to `__init__`:

```python
    def __init__(
        self,
        *,
        character_profiles: Mapping[str, CharacterProfile],
        recent_rounds: int = 3,
        granularity: PresenceGranularity = "on_stage",
        recall_service: Any = None,
        user_id: Optional[int] = None,
        player_id: Optional[int] = None,
        summary_horizon_turns: int = 45,
    ) -> None:
        self._character_profiles = character_profiles
        self._recent_rounds = recent_rounds
        self._granularity = granularity
        self.recall_service = recall_service
        self._user_id = user_id
        self._player_id = player_id
        self._summary_horizon_turns = summary_horizon_turns
```

Add a tier helper:

```python
    def _is_l1(self, actor_id: str) -> bool:
        profile = self._character_profiles.get(actor_id) or {}
        return str(profile.get("agent_type", "actor") or "actor") == "L1"
```

Rewrite `retrieve` to be L1-gated and route to `recall_memory_blocks`:

```python
    def retrieve(
        self,
        actor_id: str,
        query: str,
        state: GameState,
        *,
        user_id: Optional[int],
        player_id: Optional[int],
        top_k: int = 5,
    ) -> list[Any]:
        # 长期记忆仅 L1;NPC-Actor 无长期(spec 4.2)。
        if not self._is_l1(actor_id):
            return []
        if self.recall_service is None or user_id is None or player_id is None:
            return []
        if not query.strip():
            return []
        turn_index = int(state["runtime"].get("turn_index", 0) or 0)
        window_start = max(0, turn_index - self._summary_horizon_turns + 1)
        try:
            return self.recall_service.recall_memory_blocks(
                query,
                user_id=user_id,
                player_id=player_id,
                actor_id=actor_id,
                window_start=window_start,
                top_k=top_k,
            )
        except Exception:  # noqa: BLE001 - 任何检索后端异常都降级为空
            return []
```

Update the `build` call to `retrieve` (it now needs `state`):

```python
            retrieved=self.retrieve(
                actor_id, query, state, user_id=self._user_id, player_id=self._player_id
            ),
```

Add `from GameState import GameState` to imports if not already present (it is — line 6). Ensure `Optional` is imported (it is — line 3).

- [ ] **Step 4: Run test + full recall/provider suite**

Run: `python -m pytest tests/test_provider_l1_recall.py tests/test_default_provider_slim.py -v`
Expected: PASS. (`test_default_provider_slim` from Plan 1 still passes: no service → `retrieved == []`.)

- [ ] **Step 5: Commit**

```bash
git add Memory/default_provider.py tests/test_provider_l1_recall.py
git commit -m "feat(recall): L1-only long-term recall via memory_blocks with turn window + attribution"
```

---

## Task 5: Wire recall service + tenant into compactor at session bind

**Files:**
- Modify: `web_session.py`
- Test: `tests/test_session_binds_compactor_recall.py`

**Context:** `web_session.py` already binds the recall service to the provider (`bind_recall_service`, lines 282–289) and sets tenant (`set_tenant`, 271–272). Extend those bind points so the `AsyncMemoryCompactor` (created in Step 2 bootstrap, accessible via `deps.memory_compactor`) also receives the recall service + tenant, enabling the write side. Also pass `summary_horizon_turns` from the history manager to the provider at construction (bootstrap) so recall's `window_start` matches compaction's window.

- [ ] **Step 1: Read the current bind points**

Run: `grep -n "bind_recall_service\|set_tenant\|memory_compactor\|_recall_service\|actor_memory_provider" web_session.py | head -30`
Read the `bind_recall_service` method (282–289) and the tenant-setting path (271–272).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_session_binds_compactor_recall.py
from session_bootstrap import build_graph_dependencies


class _FakeRecall:
    def index_memory_blocks(self, blocks, *, user_id, player_id):
        pass

    def recall_memory_blocks(self, *a, **k):
        return []


def test_bootstrap_provider_has_summary_horizon():
    deps = build_graph_dependencies(mode="mock", interactive=False)
    provider = deps.actor_memory_provider
    # provider window must match the history manager horizon (45)
    assert getattr(provider, "_summary_horizon_turns", None) == deps.history_manager.summary_horizon_turns
```

(Full compactor-bind coverage requires a live session; this unit test locks the horizon-alignment invariant. The web_session bind is covered by the e2e task.)

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_session_binds_compactor_recall.py -v`
Expected: FAIL — provider constructed without `summary_horizon_turns`.

- [ ] **Step 4: Pass horizon at bootstrap + bind compactor recall in session**

In `session_bootstrap.py` `build_runtime_dependencies`, update the `DefaultActorMemoryProvider(...)` construction (383–387) to pass the horizon:

```python
        actor_memory_provider=DefaultActorMemoryProvider(
            character_profiles=character_profiles,
            recent_rounds=3,
            granularity="on_stage",
            summary_horizon_turns=45,
        ),
```

In `web_session.py` `bind_recall_service` (282–289), after binding to the provider, also bind to the compactor if present:

```python
    def bind_recall_service(self, service):
        self._recall_service = service
        deps = getattr(self, "deps", None)
        provider = getattr(deps, "actor_memory_provider", None) if deps else None
        if provider is not None and hasattr(provider, "recall_service"):
            provider.recall_service = service
        compactor = getattr(deps, "memory_compactor", None) if deps else None
        if compactor is not None:
            compactor._recall = service  # or add a set_recall_service method
            compactor.set_tenant(user_id=self.active_user_id, player_id=self.active_player_id)
```

Prefer adding a small `set_recall_service` method to `AsyncMemoryCompactor` rather than touching `_recall` directly:

```python
    def set_recall_service(self, service: Any) -> None:
        self._recall = service
```

And in the tenant-set path (271–272), also update the compactor tenant:

```python
        compactor = getattr(self.deps, "memory_compactor", None)
        if compactor is not None:
            compactor.set_tenant(user_id=self.active_user_id, player_id=self.active_player_id)
```

Confirm exact surrounding lines by reading before editing (line numbers may have shifted after prior plans).

- [ ] **Step 5: Run test + full suite**

Run: `python -m pytest tests/test_session_binds_compactor_recall.py -v && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add session_bootstrap.py web_session.py History/AsyncMemoryCompactor.py tests/test_session_binds_compactor_recall.py
git commit -m "feat(recall): bind recall service + tenant to compactor, align provider window"
```

---

## Task 6: End-to-end — write then recall round-trip

**Files:**
- Test: `tests/test_longterm_rag_e2e.py`

**Context:** With a fake vector store shared between compactor (write) and recall service (read), verify: compact old history → index memory_blocks → an L1 actor recalls only the old, on-stage, out-of-window block.

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_longterm_rag_e2e.py
from datatypes import VectorDoc, ScoredDoc
from Recall.service.recall_service import RecallService
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.default_provider import DefaultActorMemoryProvider


class _MemStore:
    def __init__(self):
        self.docs = {}

    def upsert(self, rows):
        for doc, _vec in rows:
            self.docs[doc.doc_id] = doc


class _MemHybrid:
    def __init__(self, store):
        self._store = store

    def search(self, query, *, top_k=10, filters=None, weights=None, fetch_k=200):
        dtype = (filters or {}).get("doc_type")
        return [
            ScoredDoc(doc=d, score=1.0)
            for d in self._store.docs.values()
            if d.doc_type == dtype
        ]


class _Emb:
    def encode(self, texts):
        return [[0.0] for _ in texts]


def _snapshot(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1"},
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "runtime": {"turn_index": n},
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_write_then_l1_recall_round_trip():
    store = _MemStore()
    svc = RecallService(embedding=_Emb(), vector_store=store, hybrid=_MemHybrid(store))
    compactor = AsyncMemoryCompactor(
        history_manager=HistoryManager(compression_trigger_size=30),
        recall_service=svc, user_id=1, player_id=1,
    )
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))  # turns 1-5 compacted + indexed
        compactor.join()
        compactor.take_pending()
    finally:
        compactor.stop()

    assert store.docs  # a memory_block was written

    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recall_service=svc, user_id=1, player_id=1, summary_horizon_turns=45,
    )
    # turn_index large enough that turns 1-5 are out of the 45-window
    state = {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": {"intent": "explore", "memory": {"player_memory": {}}}},
        "history": [{"turn": 100, "actor": "hero", "content": "now", "on_stage": ["hero"], "location_id": "loc"}],
        "runtime": {"turn_index": 100},
    }
    ctx = provider.build("hero", state)
    assert ctx.retrieved  # recalled the old block
    assert all(r.doc.doc_type == "memory_block" for r in ctx.retrieved)
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_longterm_rag_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_longterm_rag_e2e.py
git commit -m "test(recall): long-term RAG write-then-L1-recall round trip"
```

---

## Self-Review Checklist (run before handoff)

1. **Spec coverage:** 4.2 (long-term = RAG, L1 only; NPC none) → Tasks 4,6. 4.4 (objective RAG, no subjective queue; per-item on_stage attribution; turn-bound dedup `turn_end < window_start`) → Tasks 1 (on_stage_union metadata), 2 (both filters), 4 (window_start). Write side (compressed_blocks → memory_block, doc_type isolated) → Tasks 1,3. Recall wired to Pipeline A `retrieved` → Task 4. Step 3 scope (write + recall, L1-only) → all tasks.
2. **Placeholder scan:** `mode="mock"` flagged in Tasks 5 with a grep-first instruction. `compactor._recall = service  # or add a set_recall_service method` — resolved in the same step by adding `set_recall_service`; the private-attr line is the fallback, the method is the instruction. No TODOs left in code.
3. **Type consistency:** `build_block_docs(blocks, *, user_id, player_id) -> list[VectorDoc]` (Task 1) matches the call in `RecallService.index_memory_blocks` (Task 2) and `AsyncMemoryCompactor._index_new_blocks` (Task 3). `recall_memory_blocks(query, *, user_id, player_id, actor_id, window_start, top_k)` signature identical across service def (Task 2), stub (Task 4 test), and provider call (Task 4). `doc_id` format `u{u}:p{p}:memory_block:{start}-{end}` consistent (Task 1) and idempotent.
4. **Window alignment:** `window_start = max(0, turn_index - summary_horizon_turns + 1)` in provider (Task 4) is byte-identical to `get_visible_blocks` in `History/HistoryInference.py:23` — guarantees recall (turn_end < window_start) and visible blocks (turn_end >= window_start) never overlap. Task 5 enforces the provider horizon equals the history-manager horizon (45).
5. **Degradation:** no service / no tenant / empty query / non-L1 → `retrieved == []`, never raises (Task 4). Compactor without recall still compacts (Task 3 test).
