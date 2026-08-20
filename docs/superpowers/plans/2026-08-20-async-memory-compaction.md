# Async Memory Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move history compaction off the player-action critical path — fix the `compression_trigger_size=1` misconfiguration, extract the refresh decision into a pure `MemoryRefreshPolicy`, run compaction in a background daemon (`AsyncMemoryCompactor`), join the previous turn's result at the next turn's head, and evict compressed originals from `state["history"]` only after the background job succeeds.

**Architecture:** The `narration.after` hook (`_refresh_history`) currently runs `HistoryManager.build_memory` synchronously (~4.3s, every turn because trigger is misset to 1). Split it: at turn head, join the prior turn's pending compaction result (no timeout), merge new blocks, advance `last_compressed_turn`, and evict now-compressed originals from `state["history"]`; then derive the fast Agent memory views from *existing* blocks synchronously; then, if the policy says compact, enqueue a snapshot to the background daemon. The daemon mimics `Recall/service/async_indexer.py` (single daemon thread, non-blocking enqueue, no-timeout join, idempotent). Block-internal `raw_items` copies are preserved on eviction.

**Tech Stack:** Python 3.12 (threading, queue), pytest. No new dependencies. Mirrors `AsyncSceneIndexer` patterns.

**Reference spec:** `docs/superpowers/specs/2026-08-20-async-memory-compaction-longterm-rag-design.md` (units 1, 2, and the eviction/join behavior). Also `docs/superpowers/specs/2026-08-20-memory-architecture-consolidation-design.md` section 4.5.

**Depends on:** Plan `2026-08-20-memory-factory-consolidation.md` (Step 1) landing first is preferred but not strictly required — this plan only touches history/compaction, not the per-character memory queues. If run independently, keep the existing `HistoryManager.build_memory` behavior intact.

---

## File Structure

**Create:**
- `History/MemoryRefreshPolicy.py` — pure decision function `decide_refresh(state, *, trigger_size, ...) -> RefreshDecision`.
- `History/AsyncMemoryCompactor.py` — background daemon; `enqueue(snapshot)`, `join()`, `start()`, `stop()`, `take_pending()`.
- `tests/test_memory_refresh_policy.py`
- `tests/test_async_memory_compactor.py`
- `tests/test_compaction_eviction.py`

**Modify:**
- `session_bootstrap.py` — line 388 `compression_trigger_size=1` → `30`, `summary_horizon_turns=45`; rework `register_default_hooks` `_refresh_history` into turn-head join + sync-derive + background enqueue; construct + start the compactor.
- `History/HistoryManager.py` — factor the compaction step (score→chunk→blocks) into a reusable `compact_snapshot(...)` the daemon can call on an isolated snapshot; keep `build_memory` deriving views from existing blocks.
- `Memory/store.py` — add write-side wrappers `compact(state) -> (blocks, new_last)` and `derive_views(state, blocks) -> MemoryState` that delegate to a held `HistoryManager` (spec 4.6: compaction/derivation live under the Factory's write side; `HistoryManager` stays the pure computation engine). Created in Plan `2026-08-20-memory-factory-consolidation.md` (Step 1); this plan extends it.

**Dependency note on MemoryStore:** Step 1 creates `Memory/store.py` with `MemoryStore`. This plan adds `compact`/`derive_views` to it and points the daemon + hooks at the store. If this plan is run BEFORE Step 1 lands, create a minimal `Memory/store.py` with just these two methods (the `record_player_impression` method from Step 1 is independent and can be added later without conflict).

---

## Task 1: MemoryRefreshPolicy (pure function)

**Files:**
- Create: `History/MemoryRefreshPolicy.py`
- Test: `tests/test_memory_refresh_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_refresh_policy.py
from History.MemoryRefreshPolicy import decide_refresh


def _state(*, turn_index, last_compressed_turn, history_turns, scene_finished=False, has_blocks=False):
    return {
        "runtime": {"turn_index": turn_index, "scene_finished": scene_finished},
        "memory": {
            "last_compressed_turn": last_compressed_turn,
            "scene_memory": {"compressed_blocks": ([{"turn_end": 1}] if has_blocks else [])},
        },
        "history": [{"turn": t} for t in history_turns],
    }


def test_opening_no_compress():
    d = decide_refresh(_state(turn_index=0, last_compressed_turn=-1, history_turns=[], has_blocks=False), trigger_size=30)
    assert d.should_compress is False
    assert d.compress_all is False


def test_below_threshold_no_compress():
    hist = list(range(1, 11))  # 10 uncompressed
    d = decide_refresh(_state(turn_index=10, last_compressed_turn=0, history_turns=hist, has_blocks=True), trigger_size=30)
    assert d.should_compress is False


def test_at_threshold_compresses():
    hist = list(range(1, 31))  # 30 uncompressed
    d = decide_refresh(_state(turn_index=30, last_compressed_turn=0, history_turns=hist, has_blocks=True), trigger_size=30)
    assert d.should_compress is True
    assert d.compress_all is False


def test_scene_finished_flushes_all():
    hist = list(range(1, 6))  # 5 uncompressed, below threshold
    d = decide_refresh(_state(turn_index=5, last_compressed_turn=0, history_turns=hist, scene_finished=True, has_blocks=True), trigger_size=30)
    assert d.should_compress is True
    assert d.compress_all is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_refresh_policy.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the policy**

```python
# History/MemoryRefreshPolicy.py
from __future__ import annotations

from dataclasses import dataclass

from GameState import GameState


@dataclass(frozen=True)
class RefreshDecision:
    should_compress: bool
    compress_all: bool


def _uncompressed_count(state: GameState) -> int:
    last = state["memory"]["last_compressed_turn"]
    return sum(1 for item in state["history"] if item["turn"] > last)


def decide_refresh(state: GameState, *, trigger_size: int) -> RefreshDecision:
    turn = state["runtime"]["turn_index"]
    has_blocks = bool(state["memory"]["scene_memory"]["compressed_blocks"])

    if turn == 0 and not has_blocks:
        return RefreshDecision(should_compress=False, compress_all=False)
    if state["runtime"].get("scene_finished", False):
        return RefreshDecision(should_compress=True, compress_all=True)
    if _uncompressed_count(state) >= trigger_size:
        return RefreshDecision(should_compress=True, compress_all=False)
    return RefreshDecision(should_compress=False, compress_all=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_refresh_policy.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add History/MemoryRefreshPolicy.py tests/test_memory_refresh_policy.py
git commit -m "feat(memory): MemoryRefreshPolicy pure decision function"
```

---

## Task 2: Factor `compact_snapshot` out of HistoryManager

**Files:**
- Modify: `History/HistoryManager.py`
- Test: `tests/test_async_memory_compactor.py` (added in Task 3; here add a direct unit test inline)

**Context:** `build_memory` (58–102) does two things: (a) compaction (score → chunk → build blocks), and (b) view derivation. The daemon needs to run (a) on an isolated snapshot without touching live state. Extract (a) into `compact_snapshot`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_history_manager_compact_snapshot.py
from History.HistoryManager import HistoryManager


def _state_with_uncompressed(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1"},
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "runtime": {"turn_index": n},
        "history": history,
        "memory": {
            "last_compressed_turn": 0,
            "scene_memory": {"compressed_blocks": []},
        },
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_compact_snapshot_produces_blocks_and_cursor():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    state = _state_with_uncompressed(5)
    new_blocks, new_last = mgr.compact_snapshot(state)
    assert new_blocks  # at least one block
    assert new_last == 5  # turn_end of the last compressed item
    # snapshot compaction must NOT mutate the input state
    assert state["memory"]["scene_memory"]["compressed_blocks"] == []
    assert state["memory"]["last_compressed_turn"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_history_manager_compact_snapshot.py -v`
Expected: FAIL — `compact_snapshot` not defined.

- [ ] **Step 3: Add `compact_snapshot` and refactor `build_memory` to reuse it**

In `History/HistoryManager.py`, add:

```python
    def compact_snapshot(self, state: GameState) -> tuple[list, int]:
        """Compact uncompressed history into new blocks WITHOUT mutating state.

        Returns (all_blocks, new_last_compressed_turn). all_blocks = existing +
        newly produced. Safe to run on a snapshot in a background thread.
        """
        base_memory = state.get("memory") or empty_memory_state()
        existing_blocks = list(base_memory["scene_memory"]["compressed_blocks"])
        new_history_items = self.get_uncompressed_history_items(state)
        compressed_blocks = list(existing_blocks)

        if new_history_items:
            score_payload = build_history_score_payload(state, new_history_items)
            score_items = self._score_history_items(new_history_items, score_payload)
            scored_items = merge_scores_with_history(new_history_items, score_items)
            chunks = build_compression_chunks(scored_items)
            for chunk in chunks:
                bucket = chunk[0]["importance_bucket"]
                if bucket == "high":
                    compressed_blocks.append(build_raw_block(chunk))
                else:
                    summary_result = self._summarize_chunk(state, chunk)
                    compressed_blocks.append(build_summary_block(chunk, summary_result))

        last_compressed_turn = (
            compressed_blocks[-1]["turn_end"]
            if compressed_blocks
            else base_memory["last_compressed_turn"]
        )
        return compressed_blocks, last_compressed_turn
```

Then refactor `build_memory` (58–102) to call it for the compaction half:

```python
    def build_memory(self, state: GameState) -> MemoryState:
        compressed_blocks, last_compressed_turn = self.compact_snapshot(state)
        scene_memory = build_scene_memory_from_blocks(
            state,
            compressed_blocks,
            self.summary_horizon_turns,
        )
        playwright_memory = build_playwright_memory(state, scene_memory)
        director_memory = build_director_memory(state, scene_memory)
        scheduler_memory = build_scheduler_memory(
            state,
            scene_memory,
            self.scheduler_round_window,
        )
        return {
            "last_compressed_turn": last_compressed_turn,
            "scene_memory": scene_memory,
            "playwright_memory": playwright_memory,
            "director_memory": director_memory,
            "scheduler_memory": scheduler_memory,
        }
```

Also add a `derive_views` method the turn-head path uses AFTER merging joined blocks (derivation from existing blocks, no compaction):

```python
    def derive_views(self, state: GameState, blocks: list) -> MemoryState:
        """Derive Agent memory views from ALREADY-EXISTING blocks (no compaction)."""
        scene_memory = build_scene_memory_from_blocks(state, blocks, self.summary_horizon_turns)
        return {
            "last_compressed_turn": (blocks[-1]["turn_end"] if blocks else state["memory"]["last_compressed_turn"]),
            "scene_memory": scene_memory,
            "playwright_memory": build_playwright_memory(state, scene_memory),
            "director_memory": build_director_memory(state, scene_memory),
            "scheduler_memory": build_scheduler_memory(state, scene_memory, self.scheduler_round_window),
        }
```

- [ ] **Step 4: Run test + existing HistoryManager tests**

Run: `python -m pytest tests/test_history_manager_compact_snapshot.py -v && python -m pytest tests/ -k history -q`
Expected: PASS; existing history tests unaffected (build_memory behavior preserved).

- [ ] **Step 5: Commit**

```bash
git add History/HistoryManager.py tests/test_history_manager_compact_snapshot.py
git commit -m "refactor(memory): extract compact_snapshot + derive_views from build_memory"
```

---

## Task 3: MemoryStore write-side wrappers for compaction

**Files:**
- Modify: `Memory/store.py` (created in Step 1; if running standalone, create it with just these methods)
- Test: `tests/test_memory_store_compaction.py`

**Context:** Per spec 4.6, compaction and view-derivation are the Factory's write side. `HistoryManager` (Task 2) stays the pure compute engine; `MemoryStore` wraps it as the write-side API that the daemon and turn-head hook call. This keeps `HistoryManager` reusable and testable while giving callers a single `MemoryStore` entry point for memory writes. The wrappers hold a `HistoryManager` and delegate — no logic duplication.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_store_compaction.py
from Memory.store import MemoryStore
from History.HistoryManager import HistoryManager


def _state(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}", "on_stage": ["hero"], "location_id": "loc"}
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


def test_store_compact_delegates_to_history_manager():
    store = MemoryStore(history_manager=HistoryManager(compression_trigger_size=30, summary_horizon_turns=45))
    state = _state(5)
    blocks, new_last = store.compact(state)
    assert blocks
    assert new_last == 5
    # non-mutating (delegation preserves compact_snapshot's purity)
    assert state["memory"]["scene_memory"]["compressed_blocks"] == []


def test_store_derive_views_from_existing_blocks():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    store = MemoryStore(history_manager=mgr)
    state = _state(5)
    blocks, _ = store.compact(state)
    views = store.derive_views(state, blocks)
    assert set(views.keys()) == {
        "last_compressed_turn", "scene_memory", "playwright_memory",
        "director_memory", "scheduler_memory",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_store_compaction.py -v`
Expected: FAIL — `MemoryStore` has no `history_manager` param / no `compact`/`derive_views`.

- [ ] **Step 3: Extend `MemoryStore`**

In `Memory/store.py`, add an optional `history_manager` to the constructor and the two wrappers. `record_player_impression` (Step 1) stays unchanged and does not depend on `history_manager`.

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from GameplayTuning import RelationshipTuning

if TYPE_CHECKING:
    from GameState import GameState
    from History.GameMemory import MemoryState
    from History.HistoryManager import HistoryManager


class MemoryStore:
    """Write-side memory manager (spec 4.6). Pure functions: take state/memory fragments, return new ones.

    Read side stays in DefaultActorMemoryProvider. This class never mutates its inputs and holds no memory state.
    `history_manager` is the pure compaction/derivation engine this store delegates to.
    """

    def __init__(self, history_manager: "HistoryManager | None" = None) -> None:
        self._history_manager = history_manager

    # record_player_impression: unchanged from Step 1 (omitted here for brevity — keep as-is)

    def compact(self, state: "GameState") -> tuple[list, int]:
        """Compact uncompressed history into blocks WITHOUT mutating state. Delegates to HistoryManager."""
        assert self._history_manager is not None, "MemoryStore.compact requires a history_manager"
        return self._history_manager.compact_snapshot(state)

    def derive_views(self, state: "GameState", blocks: list) -> "MemoryState":
        """Derive Agent memory views from already-existing blocks (no compaction). Delegates to HistoryManager."""
        assert self._history_manager is not None, "MemoryStore.derive_views requires a history_manager"
        return self._history_manager.derive_views(state, blocks)
```

Note: keep the existing `record_player_impression` method body from Step 1 intact — only add `__init__`, `compact`, `derive_views`. The `record_player_impression` module-level instance in `ActorRuntime.py` (`_MEMORY_STORE = MemoryStore()`) still works because `history_manager` defaults to `None` and impression writing never touches it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_store_compaction.py tests/test_memory_store_player_impression.py -v`
Expected: PASS (both the new compaction tests and the Step 1 impression tests — confirms the constructor change didn't break the stateless usage).

- [ ] **Step 5: Commit**

```bash
git add Memory/store.py tests/test_memory_store_compaction.py
git commit -m "feat(memory): MemoryStore.compact/derive_views wrapping HistoryManager (spec 4.6)"
```

---

## Task 4: AsyncMemoryCompactor daemon

**Files:**
- Create: `History/AsyncMemoryCompactor.py`
- Test: `tests/test_async_memory_compactor.py`

**Context:** Mirror `Recall/service/async_indexer.py`: single daemon thread, non-blocking `enqueue`, `join()` blocks until drained, results land in a lock-guarded `pending_result` slot fetched via `take_pending()`. The compactor holds a `HistoryManager` and calls `compact_snapshot` on the enqueued snapshot. Failures log and leave `pending_result` empty (retry next turn).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_async_memory_compactor.py
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


def _snapshot(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"line {t}", "on_stage": ["hero"], "location_id": "loc"}
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


def _store(trigger=30):
    return MemoryStore(history_manager=HistoryManager(compression_trigger_size=trigger))


def test_enqueue_join_produces_pending_result():
    compactor = AsyncMemoryCompactor(memory_store=_store())
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        result = compactor.take_pending()
        assert result is not None
        blocks, new_last = result
        assert blocks and new_last == 5
        # taking again yields None (slot cleared)
        assert compactor.take_pending() is None
    finally:
        compactor.stop()


def test_failure_leaves_no_pending(monkeypatch):
    store = _store()

    def boom(_state):
        raise RuntimeError("compaction failed")

    monkeypatch.setattr(store, "compact", boom)
    compactor = AsyncMemoryCompactor(memory_store=store)
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        assert compactor.take_pending() is None  # failure → no pending, retry later
    finally:
        compactor.stop()


def test_snapshot_isolation_does_not_touch_source():
    compactor = AsyncMemoryCompactor(memory_store=_store())
    compactor.start()
    try:
        snap = _snapshot(5)
        compactor.enqueue(snap)
        compactor.join()
        compactor.take_pending()
        # compact is non-mutating; the enqueued dict is unchanged
        assert snap["memory"]["last_compressed_turn"] == 0
    finally:
        compactor.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_async_memory_compactor.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the daemon**

```python
# History/AsyncMemoryCompactor.py
from __future__ import annotations

import copy
import logging
import queue
import threading
from typing import Any, Optional

from GameState import GameState
from Memory.store import MemoryStore

_logger = logging.getLogger(__name__)

_PendingResult = tuple[list[Any], int]  # (all_blocks, new_last_compressed_turn)


class AsyncMemoryCompactor:
    """后台记忆压缩守护线程,仿 AsyncSceneIndexer。

    轮末非阻塞入队 state 快照;后台线程对快照(隔离拷贝)调 MemoryStore.compact
    (写侧 API,内部委托 HistoryManager),成功则把 (blocks, new_last) 放入 pending 槽,
    下一轮轮首 take_pending 取走合并。失败仅记日志,不写 pending,下轮可重试(压缩幂等)。
    """

    def __init__(self, *, memory_store: MemoryStore) -> None:
        self._store = memory_store
        self._queue: "queue.Queue[Optional[GameState]]" = queue.Queue()
        self._pending: Optional[_PendingResult] = None
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker = threading.Thread(target=self._run, name="memory-compactor", daemon=True)
        self._worker.start()

    def enqueue(self, state: GameState) -> None:
        # 深拷贝隔离:后台只读快照,绝不碰活 state。
        self._queue.put(copy.deepcopy(state))

    def join(self) -> None:
        self._queue.join()

    def take_pending(self) -> Optional[_PendingResult]:
        with self._lock:
            result = self._pending
            self._pending = None
            return result

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.join()
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._started = False

    def _run(self) -> None:
        while True:
            snapshot = self._queue.get()
            try:
                if snapshot is None:
                    return
                blocks, new_last = self._store.compact(snapshot)
                with self._lock:
                    self._pending = (blocks, new_last)
            except Exception:  # 失败不写 pending,记日志,下轮重试。
                _logger.exception("后台记忆压缩失败")
            finally:
                self._queue.task_done()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_async_memory_compactor.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add History/AsyncMemoryCompactor.py tests/test_async_memory_compactor.py
git commit -m "feat(memory): AsyncMemoryCompactor background daemon (enqueue/join/take_pending)"
```

---

## Task 5: Turn-head join + eviction helper

**Files:**
- Modify: `History/HistoryManager.py` (add `evict_compressed_history` static helper)
- Test: `tests/test_compaction_eviction.py`

**Context:** After joining the background result at turn head, the compressed originals must be removed from `state["history"]` — but ONLY `turn <= new_last_compressed_turn`, and only after success. Block-internal `raw_items` copies are untouched (they live inside the blocks).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compaction_eviction.py
from History.HistoryManager import HistoryManager


def test_evict_removes_only_compressed_turns():
    history = [{"turn": t, "content": f"l{t}"} for t in range(1, 11)]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=5)
    assert [item["turn"] for item in kept] == [6, 7, 8, 9, 10]


def test_evict_noop_when_cursor_zero():
    history = [{"turn": t} for t in range(1, 4)]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=0)
    assert [item["turn"] for item in kept] == [1, 2, 3]


def test_evict_keeps_block_internal_raw_items_untouched():
    # blocks carry their own raw_items copy; eviction only touches the history list
    history = [{"turn": 1, "content": "a"}, {"turn": 2, "content": "b"}]
    blocks = [{"turn_start": 1, "turn_end": 2, "raw_items": list(history)}]
    kept = HistoryManager.evict_compressed_history(history, new_last_compressed_turn=2)
    assert kept == []
    assert blocks[0]["raw_items"] == [{"turn": 1, "content": "a"}, {"turn": 2, "content": "b"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compaction_eviction.py -v`
Expected: FAIL — `evict_compressed_history` not defined.

- [ ] **Step 3: Implement the static helper**

Add to `HistoryManager`:

```python
    @staticmethod
    def evict_compressed_history(history: list, new_last_compressed_turn: int) -> list:
        """Drop history items with turn <= cursor. Block-internal raw_items unaffected."""
        if new_last_compressed_turn <= 0:
            return list(history)
        return [item for item in history if item["turn"] > new_last_compressed_turn]
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_compaction_eviction.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add History/HistoryManager.py tests/test_compaction_eviction.py
git commit -m "feat(memory): evict_compressed_history helper (post-success eviction)"
```

---

## Task 6: Wire the async pipeline into bootstrap hooks

**Files:**
- Modify: `session_bootstrap.py`
- Test: `tests/test_bootstrap_async_compaction.py`

**Context:** Fix the constants and rework `register_default_hooks`. The new flow, per spec unit 2 + architecture overview:
- **Turn head** (new hook on the beat's start point / prepended to the action): `take_pending()`; if a result exists, merge blocks into `state["memory"]`, advance `last_compressed_turn`, evict history, and re-derive views via `derive_views`.
- **`narration.after`**: derive views from existing blocks (fast), then if `decide_refresh(...).should_compress`, `enqueue(state)` to the compactor (non-blocking).

Because the existing hook system registers on `narration.after`, and there is no explicit "turn head" hook point, implement the join at the **start of `_refresh_history`** (it runs once per narration; the join consumes the *previous* turn's pending result before this turn's enqueue). This keeps a single hook and satisfies "next turn joins prior result".

- [ ] **Step 1: Fix the constants**

In `session_bootstrap.py` line 388:

```python
        history_manager=HistoryManager(compression_trigger_size=30, summary_horizon_turns=45),
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_bootstrap_async_compaction.py
from session_bootstrap import build_graph_dependencies


def test_history_manager_constants_fixed():
    deps = build_graph_dependencies(mode="mock", interactive=False)
    assert deps.history_manager.compression_trigger_size == 30
    assert deps.history_manager.summary_horizon_turns == 45


def test_compactor_attached_and_started():
    deps = build_graph_dependencies(mode="mock", interactive=False)
    assert getattr(deps, "memory_store", None) is not None
    assert getattr(deps, "memory_compactor", None) is not None
```

Adjust `mode="mock"` to the non-agent mode used by other bootstrap tests if different (grep `build_graph_dependencies(` in `tests/`).

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_bootstrap_async_compaction.py -v`
Expected: FAIL — trigger still 1 (before Step 1 lands) and no `memory_compactor` attribute.

- [ ] **Step 4: Construct + start the compactor and rework the hook**

In `session_bootstrap.py`, import at top:

```python
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.MemoryRefreshPolicy import decide_refresh
from Memory.store import MemoryStore
```

In `build_runtime_dependencies`, after `deps = GraphDependencies(...)` and before `register_default_hooks(deps)`, build the write-side `MemoryStore` (wrapping the history_manager) and start a compactor on it (store both on deps; add attributes to `GraphDependencies` if they lack slots — check `Graph/nodes.py`):

```python
    if deps.history_manager is not None:
        deps.memory_store = MemoryStore(history_manager=deps.history_manager)
        deps.memory_compactor = AsyncMemoryCompactor(memory_store=deps.memory_store)
        deps.memory_compactor.start()
```

Rework `_refresh_history` in `register_default_hooks` (439–442) — view derivation now goes through `deps.memory_store` (spec 4.6):

```python
    def _refresh_history(state):
        manager = deps.history_manager
        store = getattr(deps, "memory_store", None)
        compactor = getattr(deps, "memory_compactor", None)
        if manager is None or store is None:
            return state

        merged_state = state
        # Turn head: join the previous turn's background compaction, if any.
        if compactor is not None:
            pending = compactor.take_pending()
            if pending is not None:
                blocks, new_last = pending
                evicted_history = manager.evict_compressed_history(state["history"], new_last)
                merged_state = {
                    **state,
                    "history": evicted_history,
                    "memory": {
                        **state["memory"],
                        "scene_memory": {
                            **state["memory"]["scene_memory"],
                            "compressed_blocks": blocks,
                        },
                        "last_compressed_turn": new_last,
                    },
                }

        # Fast path: derive Agent views from EXISTING blocks (no compaction), via the store.
        existing_blocks = merged_state["memory"]["scene_memory"]["compressed_blocks"]
        merged_state = {**merged_state, "memory": store.derive_views(merged_state, existing_blocks)}

        # If policy says compact, enqueue snapshot to background (non-blocking).
        decision = decide_refresh(merged_state, trigger_size=manager.compression_trigger_size)
        if decision.should_compress and compactor is not None:
            compactor.enqueue(merged_state)

        return merged_state
```

Note: `derive_views` merges joined blocks into views; because compaction is deferred, the freshly-enqueued turn's blocks appear one turn later (next join) — matching the "next-turn join" design.

- [ ] **Step 5: Add `memory_store` + `memory_compactor` slots to GraphDependencies if needed**

Run: `grep -n "memory_compactor\|memory_store\|history_manager\|class GraphDependencies\|@dataclass" Graph/nodes.py | head`
If `GraphDependencies` is a dataclass without these fields, add `memory_store: Any = None` and `memory_compactor: Any = None` alongside `history_manager`. If it is a plain class allowing arbitrary attributes, no change needed.

- [ ] **Step 6: Run test + full suite**

Run: `python -m pytest tests/test_bootstrap_async_compaction.py -v && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add session_bootstrap.py Graph/nodes.py tests/test_bootstrap_async_compaction.py
git commit -m "feat(memory): async compaction pipeline — join at head, derive sync, enqueue background"
```

---

## Task 7: End-to-end — critical path no longer pays compaction cost

**Files:**
- Test: `tests/test_async_compaction_e2e.py`

**Context:** Verify (a) two consecutive turns: turn N enqueues, turn N+1 joins and merges + evicts; (b) the synchronous hook does not run compaction (assert `compact_snapshot` is not called during the action, only `derive_views`).

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_async_compaction_e2e.py
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


def _state(n, last_compressed=0, blocks=None):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1"},
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "runtime": {"turn_index": n, "scene_finished": False},
        "history": history,
        "memory": {"last_compressed_turn": last_compressed, "scene_memory": {"compressed_blocks": blocks or []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_enqueue_then_join_merges_and_reports_cursor():
    mgr = HistoryManager(compression_trigger_size=30, summary_horizon_turns=45)
    store = MemoryStore(history_manager=mgr)
    compactor = AsyncMemoryCompactor(memory_store=store)
    compactor.start()
    try:
        compactor.enqueue(_state(35))  # >= threshold worth of history
        compactor.join()
        blocks, new_last = compactor.take_pending()
        assert new_last > 0
        evicted = mgr.evict_compressed_history(_state(35)["history"], new_last)
        assert all(item["turn"] > new_last for item in evicted)
    finally:
        compactor.stop()
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_async_compaction_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_async_compaction_e2e.py
git commit -m "test(memory): async compaction e2e — enqueue, join, merge, evict"
```

---

## Self-Review Checklist (run before handoff)

1. **Spec coverage:** Unit 1 (MemoryRefreshPolicy: opening/<30/≥30/scene_finished) → Task 1. `compact_snapshot`/`derive_views` pure engine → Task 2. MemoryStore write-side wrappers (spec 4.6: compaction/derivation under Factory) → Task 3. AsyncMemoryCompactor (enqueue/join/pending/failure/snapshot isolation) → Task 4. Constant fix (1→30, horizon 45) → Task 6 Step 1. Evict-after-success (turn ≤ cursor) → Task 5 + Task 6 hook. Raw_items preserved → Task 5 Step 3 test. Join at turn head, no-timeout → Task 6 hook (`take_pending` + merge). Derive from existing blocks synchronously via store → Task 3 + Task 6.
2. **Placeholder scan:** `mode="mock"` flagged in Task 6 with a grep instruction to confirm the actual non-agent mode — deliberate, not a placeholder.
3. **Type consistency:** `compact_snapshot -> (list, int)` (Task 2) = `MemoryStore.compact -> (list, int)` (Task 3) = `_PendingResult = tuple[list, int]` and `take_pending` return (Task 4) = `blocks, new_last = pending` unpack in the hook (Task 6). `AsyncMemoryCompactor(memory_store=...)` (Task 4) matches the bootstrap construction (Task 6). `evict_compressed_history(history, new_last_compressed_turn)` signature identical across Task 5 def and Task 6 call.
4. **No mutation:** `compact_snapshot` documented + tested non-mutating (Task 2 Step 1); `MemoryStore.compact` delegates without mutation (Task 3 test); compactor deep-copies on enqueue (Task 4) — triple safety.
