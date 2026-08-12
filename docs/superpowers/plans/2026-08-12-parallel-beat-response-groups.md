# 分片并行角色响应 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一 beat 内"独立开口、彼此不接话"的角色并发生成，把 N 段串行 LLM 调用压缩成"分组数 × 每组最慢角色"，降低整轮延迟。

**Architecture:** Director 新增 `response_groups` 语义分组（组间串行、组内并行）。`run_beat_loop` 由"逐个 actor"改为"逐组"：组内用 `ThreadPoolExecutor` 并发 `perform_turn`（各带 3 次重试），拿到全部结果后按 Director 原优先级顺序确定性 apply（apply 是纯内存操作，天然串行化状态变更）。冲突按固定规则合并；单角色失败部分成功 + 上报。后端-only，前端保持一次性返回。

**Tech Stack:** Python 3, TypedDict 状态模型, `concurrent.futures.ThreadPoolExecutor`, unittest（现有测试用 openai import shim）。

---

## 参考：关键代码坐标

- 串行循环：`Graph/beat_subgraph.py` `run_beat_loop`（当前逐个取 actor）
- Director schema：`Director/DirectorSchema.py` `DIRECTOR_RESPONSE_SCHEMA`
- Director brief 类型：`Director/DirectorBrief.py` `DirectorBrief` / `empty_director_brief`
- 归一化：`Director/DirectorRuntime.py` `normalize_director_brief`（line ~312）、`apply_director_brief`（line ~397，落 `pending_beat_actors`）
- runtime 状态：`GameState.py` `RuntimeState`（line 122）/ `create_runtime_state`（line 158）
- actor 上下文：`Actor/ActorFormatter.py:71` `recent_history = state["history"][-8:]`（并行依赖根因）
- 单次 apply：`Actor/ActorRuntime.py:602` `apply_resolved_act`（读 `state["runtime"]["resolved_act"]`）
- 组内单 actor 执行：`Graph/nodes.py` `actor_node`（line ~424，按 agent_type 选 agent）+ `resolve_npc_turn_state`（`Graph/actor_paths.py:65`）
- 测试模式：`tests/test_beat_resolution.py`（`FakeDirector` / `FakeActor` + openai shim）

## File Structure

| 文件 | 责任 | 改动类型 |
|------|------|----------|
| `Director/DirectorSchema.py` | LLM 输出契约增加 `response_groups` | Modify |
| `Director/DirectorBrief.py` | `DirectorBrief` 增字段 + empty 默认 | Modify |
| `Director/DirectorRuntime.py` | `response_groups` 归一化、一致性降级、interrupt 拆组 | Modify |
| `Director/DirectorAgent.py` | system prompt 增加分组规则 | Modify |
| `GameState.py` | runtime 增 `pending_response_groups` | Modify |
| `Graph/nodes.py` | `apply_director_brief` 落分组；新增组执行/回收/合并 helper | Modify |
| `Graph/beat_group.py` | 组内并行执行 + 重试队列 + 冲突合并（新模块，隔离复杂度） | Create |
| `Graph/beat_subgraph.py` | `run_beat_loop` 改为按组消费 | Modify |
| `tests/test_beat_group_parallel.py` | 分组/并行/回收/合并/重试测试 | Create |
| `tests/test_director_response_groups.py` | Director 归一化与降级测试 | Create |

---

## Task 1: DirectorBrief 增加 response_groups 字段

**Files:**
- Modify: `Director/DirectorBrief.py`
- Test: `tests/test_director_response_groups.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_director_response_groups.py`:

```python
from __future__ import annotations

import unittest

from Director.DirectorBrief import empty_director_brief


class EmptyDirectorBriefTest(unittest.TestCase):
    def test_empty_brief_has_response_groups(self):
        brief = empty_director_brief()
        self.assertIn("response_groups", brief)
        self.assertEqual(brief["response_groups"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_director_response_groups.py::EmptyDirectorBriefTest -v`
Expected: FAIL — `KeyError: 'response_groups'` or assertion error.

- [ ] **Step 3: Add the field**

In `Director/DirectorBrief.py`, add to the `DirectorBrief` TypedDict (after `who_should_respond: list[str]`):

```python
    who_should_respond: list[str]
    response_groups: list[list[str]]
```

And in `empty_director_brief()` return dict (after `"who_should_respond": [],`):

```python
        "who_should_respond": [],
        "response_groups": [],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_director_response_groups.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Director/DirectorBrief.py tests/test_director_response_groups.py
git commit -m "feat(director): add response_groups field to DirectorBrief"
```

---

## Task 2: DirectorSchema 增加 response_groups

**Files:**
- Modify: `Director/DirectorSchema.py`

- [ ] **Step 1: Add schema property**

In `Director/DirectorSchema.py`, add to `properties` (after the `who_should_respond` block, before `lead_in_text`):

```python
                "who_should_respond": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "response_groups": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
```

Add `"response_groups"` to the `required` list (after `"who_should_respond"`):

```python
                "who_should_respond",
                "response_groups",
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/test_director_conflict_triptych.py tests/test_director_formatter_tiers.py -v`
Expected: PASS (schema change is additive; normalization handles absence).

- [ ] **Step 3: Commit**

```bash
git add Director/DirectorSchema.py
git commit -m "feat(director): add response_groups to director response schema"
```

---

## Task 3: normalize_director_brief 归一化 response_groups（含降级）

分组归一化规则：过滤 `future_on_stage` 外的 id、去重；展平后若与 `who_should_respond` 不一致（或字段缺失/为空）→ 降级为全串行（每人一组）。

**Files:**
- Modify: `Director/DirectorRuntime.py`
- Test: `tests/test_director_response_groups.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_director_response_groups.py`:

```python
from Director.DirectorRuntime import normalize_director_brief


class NormalizeResponseGroupsTest(unittest.TestCase):
    def _base_brief(self, **overrides):
        brief = {
            "beat": "b",
            "beat_goal": "g",
            "focus_character": None,
            "tension_target": 0.3,
            "allow_interrupt": False,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a"], ["b", "c"]],
            "lead_in_text": "",
            "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        brief.update(overrides)
        return brief

    def test_valid_groups_are_kept(self):
        result = normalize_director_brief(
            self._base_brief(),
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b", "c"]])

    def test_missing_groups_degrade_to_serial(self):
        brief = self._base_brief()
        del brief["response_groups"]
        result = normalize_director_brief(
            brief,
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b"], ["c"]])

    def test_inconsistent_groups_degrade_to_serial(self):
        # groups flatten to {a,b} but who_should_respond is {a,b,c}
        result = normalize_director_brief(
            self._base_brief(response_groups=[["a", "b"]]),
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b"], ["c"]])

    def test_offstage_ids_filtered_then_consistency_checked(self):
        # 'z' not on stage -> dropped from who_should_respond; groups must match survivors
        result = normalize_director_brief(
            self._base_brief(
                who_should_respond=["a", "b", "z"],
                response_groups=[["a"], ["b"], ["z"]],
            ),
            current_on_stage=["a", "b"],
            allowed_actor_ids=["a", "b"],
        )
        self.assertEqual(result["who_should_respond"], ["a", "b"])
        self.assertEqual(result["response_groups"], [["a"], ["b"]])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_director_response_groups.py::NormalizeResponseGroupsTest -v`
Expected: FAIL — `response_groups` not present in normalized output.

- [ ] **Step 3: Implement normalization helper + wire into normalize_director_brief**

In `Director/DirectorRuntime.py`, add this helper before `normalize_director_brief`:

```python
def _normalize_response_groups(
    raw_groups: Any,
    who_should_respond: list[str],
) -> list[list[str]]:
    allowed = set(who_should_respond)
    serial = [[cid] for cid in who_should_respond]
    if not isinstance(raw_groups, list):
        return serial

    groups: list[list[str]] = []
    seen: set[str] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            return serial
        group: list[str] = []
        for item in raw_group:
            cid = str(item).strip()
            if not cid or cid not in allowed or cid in seen:
                continue
            seen.add(cid)
            group.append(cid)
        if group:
            groups.append(group)

    if seen != allowed:
        return serial
    return groups
```

Then in `normalize_director_brief`, after the block that sets `normalized["who_should_respond"]` (the `if not normalized["who_should_respond"]:` fallback), add:

```python
    normalized["response_groups"] = _normalize_response_groups(
        brief.get("response_groups"),
        normalized["who_should_respond"],
    )
```

Note: `empty_director_brief()` already seeds `response_groups: []`, and the early `if not brief: return normalized` path returns it as `[]`, which is correct (no actors → no groups).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_director_response_groups.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run director regression tests**

Run: `python -m pytest tests/test_director_conflict_triptych.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Director/DirectorRuntime.py tests/test_director_response_groups.py
git commit -m "feat(director): normalize response_groups with serial-degrade fallback"
```

---

## Task 4: interrupt 角色拆成独立后续串行组

规则（spec §5.2）：并行组内不支持打断。若 `allow_interrupt` 为真且某角色被标为 interrupt，把它单独成组。本实现采用简化确定性规则：**当 `allow_interrupt` 为真时，`who_should_respond` 中的 focus_character 单独成首组**（interrupt 通常由 focus 发起），其余按 Director 分组。若无法判定，保持 Director 分组。

> 说明：Director schema 未单列 interrupt actor 字段。采用"allow_interrupt 时 focus 单独成组"这一确定性近似，避免引入新字段。

**Files:**
- Modify: `Director/DirectorRuntime.py`
- Test: `tests/test_director_response_groups.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_director_response_groups.py`:

```python
class InterruptSplitsGroupsTest(unittest.TestCase):
    def test_allow_interrupt_splits_focus_into_own_group(self):
        brief = {
            "beat": "b", "beat_goal": "g",
            "focus_character": "a",
            "tension_target": 0.3,
            "allow_interrupt": True,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a", "b"], ["c"]],
            "lead_in_text": "", "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        result = normalize_director_brief(
            brief, current_on_stage=["a", "b", "c"], allowed_actor_ids=["a", "b", "c"],
        )
        # 'a' (focus) pulled out of the parallel group into its own leading group
        self.assertEqual(result["response_groups"][0], ["a"])
        # flatten still equals who_should_respond set
        flat = [cid for grp in result["response_groups"] for cid in grp]
        self.assertEqual(sorted(flat), ["a", "b", "c"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_director_response_groups.py::InterruptSplitsGroupsTest -v`
Expected: FAIL — focus still grouped with `b`.

- [ ] **Step 3: Implement interrupt split**

In `Director/DirectorRuntime.py`, add helper before `normalize_director_brief`:

```python
def _split_interrupt_actor(
    groups: list[list[str]],
    *,
    focus_character: str | None,
    allow_interrupt: bool,
) -> list[list[str]]:
    if not allow_interrupt or not focus_character:
        return groups
    focus = str(focus_character).strip()
    if not focus:
        return groups
    remaining: list[list[str]] = []
    found = False
    for group in groups:
        stripped = [cid for cid in group if cid != focus]
        if focus in group:
            found = True
        if stripped:
            remaining.append(stripped)
    if not found:
        return groups
    return [[focus], *remaining]
```

Then in `normalize_director_brief`, replace the `normalized["response_groups"] = ...` line from Task 3 with:

```python
    normalized["response_groups"] = _split_interrupt_actor(
        _normalize_response_groups(
            brief.get("response_groups"),
            normalized["who_should_respond"],
        ),
        focus_character=normalized["focus_character"],
        allow_interrupt=normalized["allow_interrupt"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_director_response_groups.py -v`
Expected: PASS (all tests including InterruptSplitsGroupsTest)

- [ ] **Step 5: Commit**

```bash
git add Director/DirectorRuntime.py tests/test_director_response_groups.py
git commit -m "feat(director): split interrupt focus actor into its own leading group"
```

---

## Task 5: runtime 增加 pending_response_groups + apply_director_brief 落地

**Files:**
- Modify: `GameState.py`
- Modify: `Director/DirectorRuntime.py` (`apply_director_brief`)
- Test: `tests/test_director_response_groups.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_director_response_groups.py`:

```python
from Director.DirectorRuntime import apply_director_brief
from GameState import create_initial_game_state


class ApplyBriefGroupsTest(unittest.TestCase):
    def test_apply_populates_pending_response_groups(self):
        state = create_initial_game_state(on_stage=["a", "b", "c"])
        state["characters"] = {cid: {} for cid in ["a", "b", "c"]}
        state["scene"]["on_stage"] = ["a", "b", "c"]
        brief = {
            "beat": "b", "beat_goal": "g",
            "focus_character": None, "tension_target": 0.2,
            "allow_interrupt": False,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a"], ["b", "c"]],
            "lead_in_text": "", "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        result = apply_director_brief(state, brief, character_profiles={})
        self.assertEqual(
            result["runtime"]["pending_response_groups"],
            [["a"], ["b", "c"]],
        )
```

> Verify `create_initial_game_state` signature by reading `GameState.py`; the test in `tests/test_beat_resolution.py` imports it. If it needs different args, mirror that test's construction.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_director_response_groups.py::ApplyBriefGroupsTest -v`
Expected: FAIL — `KeyError: 'pending_response_groups'`.

- [ ] **Step 3: Add runtime field**

In `GameState.py` `RuntimeState` TypedDict, after `pending_beat_actors: list[str]`:

```python
    pending_beat_actors: list[str]
    pending_response_groups: list[list[str]]
```

In `create_runtime_state()` return dict, after `"pending_beat_actors": [],`:

```python
        "pending_beat_actors": [],
        "pending_response_groups": [],
```

- [ ] **Step 4: Populate in apply_director_brief**

In `Director/DirectorRuntime.py` `apply_director_brief`, the return `runtime` dict currently sets `pending_beat_actors`. The `response_groups` must be intersected with `prioritized_active_on_stage` (same filter as `pending_beat_actors`) and stripped of empties. Before the `return`, add:

```python
    pending_response_groups = [
        filtered
        for filtered in (
            [cid for cid in group if cid in prioritized_active_on_stage]
            for group in normalized["response_groups"]
        )
        if filtered
    ]
    if not pending_response_groups and pending_beat_actors:
        pending_response_groups = [[cid] for cid in pending_beat_actors]
```

Then add to the returned `runtime` dict (after `"pending_beat_actors": pending_beat_actors,`):

```python
            "pending_beat_actors": pending_beat_actors,
            "pending_response_groups": pending_response_groups,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_director_response_groups.py -v`
Expected: PASS

- [ ] **Step 6: Run broad regression**

Run: `python -m pytest tests/test_beat_resolution.py -v`
Expected: PASS (new field is additive; loop not yet changed)

- [ ] **Step 7: Commit**

```bash
git add GameState.py Director/DirectorRuntime.py tests/test_director_response_groups.py
git commit -m "feat(runtime): thread pending_response_groups from director brief into runtime"
```

---

## Task 6: 冲突合并纯函数 merge_group_resolved_acts

组内多角色 resolved_act 的确定性合并规则（spec §5）。输入：按 Director 优先级排序的 `(actor_id, resolved_act)` 列表。输出：合并元数据（终场标志、plot_flags）——注意 relationship/emotion/history 不在此合并（它们由后续逐个 `apply_resolved_act` 天然叠加）。此函数只裁决**跨角色的全局标志**。

**Files:**
- Create: `Graph/beat_group.py`
- Test: `tests/test_beat_group_parallel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_beat_group_parallel.py`:

```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.beat_group import merge_group_flags


class MergeGroupFlagsTest(unittest.TestCase):
    def test_end_scene_only_from_highest_priority(self):
        # order = priority: a first, b second
        ordered = [
            ("a", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {}}),
            ("b", {"should_end_scene": True, "should_end_chapter": True, "triggered_plot_flags": {}}),
        ]
        flags = merge_group_flags(ordered)
        # b is lower priority -> ignored
        self.assertFalse(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])

    def test_end_scene_from_highest_priority_wins(self):
        ordered = [
            ("a", {"should_end_scene": True, "should_end_chapter": False, "triggered_plot_flags": {}}),
            ("b", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {}}),
        ]
        flags = merge_group_flags(ordered)
        self.assertTrue(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])

    def test_plot_flags_first_non_empty_by_priority(self):
        ordered = [
            ("a", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {"secret": "revealed_by_a"}}),
            ("b", {"should_end_scene": False, "should_end_chapter": False, "triggered_plot_flags": {"secret": "revealed_by_b", "other": "x"}}),
        ]
        flags = merge_group_flags(ordered)
        self.assertEqual(flags["triggered_plot_flags"]["secret"], "revealed_by_a")
        self.assertEqual(flags["triggered_plot_flags"]["other"], "x")

    def test_empty_group(self):
        flags = merge_group_flags([])
        self.assertFalse(flags["should_end_scene"])
        self.assertFalse(flags["should_end_chapter"])
        self.assertEqual(flags["triggered_plot_flags"], {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_beat_group_parallel.py::MergeGroupFlagsTest -v`
Expected: FAIL — `ModuleNotFoundError: Graph.beat_group`.

- [ ] **Step 3: Implement merge_group_flags**

Create `Graph/beat_group.py`:

```python
from __future__ import annotations

from typing import Any


def merge_group_flags(
    ordered_acts: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Deterministically merge cross-actor global flags for a parallel group.

    ordered_acts is sorted by director priority (highest first).
    - should_end_scene/chapter: only the highest-priority actor's value counts.
    - triggered_plot_flags: first non-empty value per key, scanning by priority.
    """
    should_end_scene = False
    should_end_chapter = False
    if ordered_acts:
        _, top_act = ordered_acts[0]
        should_end_scene = bool(top_act.get("should_end_scene", False))
        should_end_chapter = bool(top_act.get("should_end_chapter", False))

    triggered_plot_flags: dict[str, str] = {}
    for _actor_id, act in ordered_acts:
        for key, value in (act.get("triggered_plot_flags") or {}).items():
            if key not in triggered_plot_flags and str(value).strip():
                triggered_plot_flags[key] = str(value)

    return {
        "should_end_scene": should_end_scene,
        "should_end_chapter": should_end_chapter,
        "triggered_plot_flags": triggered_plot_flags,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_beat_group_parallel.py::MergeGroupFlagsTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Graph/beat_group.py tests/test_beat_group_parallel.py
git commit -m "feat(beat): merge_group_flags for deterministic cross-actor flag merge"
```

---

## Task 7: 组内并行执行 + 重试队列 run_actor_group

对一个组并发 `perform_turn`，每个 actor 各带 3 次重试；返回 `(successes: list[(actor_id, resolved_act)], failures: list[(actor_id, error_str)])`，其中 successes 按传入的优先级顺序排列。generation 用 `group_start_state`（组内所有 actor 读同一份 history，互不预读）。

**Files:**
- Modify: `Graph/beat_group.py`
- Test: `tests/test_beat_group_parallel.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_beat_group_parallel.py`:

```python
from Graph.beat_group import run_actor_group


class FakeActorAgent:
    def __init__(self, fail_times=0, label="ok"):
        self.calls = 0
        self.fail_times = fail_times
        self.label = label

    def perform_turn(self, state, character_profiles):
        del character_profiles
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("boom")
        actor = state["runtime"]["next_act"]["actor"]
        return {"actor": actor, "content": f"{self.label}:{actor}", "history_len": len(state["history"])}


def _make_state(history_len=3):
    return {
        "runtime": {"next_act": None},
        "history": [{"turn": i} for i in range(history_len)],
        "characters": {},
    }


class RunActorGroupTest(unittest.TestCase):
    def test_all_actors_see_same_start_history(self):
        agents = {aid: FakeActorAgent() for aid in ["a", "b", "c"]}
        state = _make_state(history_len=5)
        successes, failures = run_actor_group(
            state,
            group=["a", "b", "c"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={},
            max_retries=3,
        )
        self.assertEqual(failures, [])
        # every actor read the same 5-length history (no intra-group pre-reading)
        for _aid, act in successes:
            self.assertEqual(act["history_len"], 5)

    def test_success_order_matches_group_order(self):
        agents = {aid: FakeActorAgent() for aid in ["a", "b", "c"]}
        state = _make_state()
        successes, _failures = run_actor_group(
            state, group=["a", "b", "c"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        self.assertEqual([aid for aid, _ in successes], ["a", "b", "c"])

    def test_retry_then_succeed(self):
        agents = {"a": FakeActorAgent(fail_times=2)}  # fails twice, ok on 3rd
        state = _make_state()
        successes, failures = run_actor_group(
            state, group=["a"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        self.assertEqual(len(successes), 1)
        self.assertEqual(failures, [])
        self.assertEqual(agents["a"].calls, 3)

    def test_exhausted_retries_reported_as_failure(self):
        agents = {"a": FakeActorAgent(fail_times=99), "b": FakeActorAgent()}
        state = _make_state()
        successes, failures = run_actor_group(
            state, group=["a", "b"],
            resolve_agent=lambda aid: agents[aid],
            character_profiles={}, max_retries=3,
        )
        # partial success: b succeeds, a fails after 4 attempts (1 + 3 retries)
        self.assertEqual([aid for aid, _ in successes], ["b"])
        self.assertEqual([aid for aid, _ in failures], ["a"])
        self.assertEqual(agents["a"].calls, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_beat_group_parallel.py::RunActorGroupTest -v`
Expected: FAIL — `run_actor_group` not defined.

- [ ] **Step 3: Implement run_actor_group**

Append to `Graph/beat_group.py`:

```python
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


def _perform_with_retry(
    group_start_state: dict[str, Any],
    actor_id: str,
    resolve_agent: Callable[[str], Any],
    character_profiles: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    # Each actor reads the group-start history (no intra-group pre-reading).
    actor_state = {
        **group_start_state,
        "runtime": {
            **group_start_state["runtime"],
            "next_act": {**(group_start_state["runtime"].get("next_act") or {}), "actor": actor_id},
        },
    }
    last_error: Exception | None = None
    for _attempt in range(max_retries + 1):
        try:
            agent = resolve_agent(actor_id)
            return agent.perform_turn(state=actor_state, character_profiles=character_profiles)
        except Exception as exc:  # noqa: BLE001 - retry any generation failure
            last_error = exc
    raise last_error if last_error is not None else RuntimeError("unknown actor failure")


def run_actor_group(
    group_start_state: dict[str, Any],
    *,
    group: list[str],
    resolve_agent: Callable[[str], Any],
    character_profiles: dict[str, Any],
    max_retries: int = 3,
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str]]]:
    if not group:
        return [], []

    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(group)) as executor:
        future_map = {
            executor.submit(
                _perform_with_retry,
                group_start_state,
                actor_id,
                resolve_agent,
                character_profiles,
                max_retries,
            ): actor_id
            for actor_id in group
        }
        for future, actor_id in future_map.items():
            try:
                results[actor_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                errors[actor_id] = str(exc)

    successes = [(aid, results[aid]) for aid in group if aid in results]
    failures = [(aid, errors[aid]) for aid in group if aid in errors]
    return successes, failures
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_beat_group_parallel.py::RunActorGroupTest -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add Graph/beat_group.py tests/test_beat_group_parallel.py
git commit -m "feat(beat): run_actor_group parallel generation with per-actor retry queue"
```

---

## Task 8: 组回收 apply_group_results（串行 apply + 标志合并 + 失败上报）

拿到组内 successes/failures 后：按优先级顺序逐个把 resolved_act 塞进 `runtime.resolved_act` 并调用 `apply_resolved_act`（relationship/emotion/history 天然叠加）；用 `merge_group_flags` 裁决终场/plot_flag 并覆盖到最终 state；把 failures 作为 system 消息追加到 history。

**Files:**
- Modify: `Graph/beat_group.py`
- Test: `tests/test_beat_group_parallel.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_beat_group_parallel.py`:

```python
from Graph.beat_group import apply_group_results
from GameState import create_initial_game_state
from ResolvedActUtils import build_resolved_act_payload


class ApplyGroupResultsTest(unittest.TestCase):
    def _state(self):
        state = create_initial_game_state(on_stage=["a", "b"])
        state["characters"] = {"a": {}, "b": {}}
        state["scene"]["on_stage"] = ["a", "b"]
        return state

    def test_both_acts_committed_to_history_in_order(self):
        state = self._state()
        acts = [
            ("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A-line", spoken_text="A-line")),
            ("b", build_resolved_act_payload(actor="b", mode="speak", target=None, content="B-line", spoken_text="B-line")),
        ]
        result = apply_group_results(state, successes=acts, failures=[])
        actors_in_history = [h["actor"] for h in result["history"] if h.get("actor") in ("a", "b")]
        self.assertEqual(actors_in_history, ["a", "b"])

    def test_end_scene_from_lower_priority_ignored(self):
        state = self._state()
        acts = [
            ("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A", spoken_text="A", should_end_scene=False)),
            ("b", build_resolved_act_payload(actor="b", mode="speak", target=None, content="B", spoken_text="B", should_end_scene=True)),
        ]
        result = apply_group_results(state, successes=acts, failures=[])
        self.assertFalse(result["runtime"]["resolved_act"]["should_end_scene"])

    def test_failures_appended_as_system_message(self):
        state = self._state()
        acts = [("a", build_resolved_act_payload(actor="a", mode="speak", target=None, content="A", spoken_text="A"))]
        result = apply_group_results(state, successes=acts, failures=[("b", "timeout")])
        system_msgs = [h for h in result["history"] if h.get("message_kind") == "system"]
        self.assertTrue(any("b" in str(h.get("content", "")) for h in system_msgs))
```

> Confirm `build_resolved_act_payload` accepts `should_end_scene` kwarg (it appears in `ResolvedAct` TypedDict). If the payload builder doesn't take it directly, set it on the returned dict before passing.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_beat_group_parallel.py::ApplyGroupResultsTest -v`
Expected: FAIL — `apply_group_results` not defined.

- [ ] **Step 3: Implement apply_group_results**

Append to `Graph/beat_group.py`:

```python
from Actor.ActorRuntime import apply_resolved_act


def apply_group_results(
    state: dict[str, Any],
    *,
    successes: list[tuple[str, dict[str, Any]]],
    failures: list[tuple[str, str]],
    relationship_tuning: Any = None,
    character_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = state
    for _actor_id, resolved_act in successes:
        current = {
            **current,
            "runtime": {**current["runtime"], "resolved_act": resolved_act},
        }
        current = apply_resolved_act(
            current,
            relationship_tuning,
            character_profiles=character_profiles,
        )

    flags = merge_group_flags(successes)
    resolved_after = dict(current["runtime"].get("resolved_act") or {})
    if resolved_after:
        resolved_after["should_end_scene"] = flags["should_end_scene"]
        resolved_after["should_end_chapter"] = flags["should_end_chapter"]
        merged_plot_flags = dict(resolved_after.get("triggered_plot_flags") or {})
        merged_plot_flags.update(flags["triggered_plot_flags"])
        resolved_after["triggered_plot_flags"] = merged_plot_flags
        current = {
            **current,
            "runtime": {**current["runtime"], "resolved_act": resolved_after},
        }

    if failures:
        failed_ids = "、".join(actor_id for actor_id, _err in failures)
        next_turn = int(current["runtime"].get("turn_index", 0) or 0) + 1
        current = {
            **current,
            "history": [
                *current["history"],
                {
                    "turn": next_turn,
                    "actor": None,
                    "mode": "event",
                    "content": f"（系统）以下角色本轮生成失败，已跳过：{failed_ids}。",
                    "spoken_text": "",
                    "nonverbal_action": "",
                    "message_kind": "system",
                },
            ],
            "runtime": {**current["runtime"], "turn_index": next_turn},
        }

    return current
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_beat_group_parallel.py::ApplyGroupResultsTest -v`
Expected: PASS

- [ ] **Step 5: Run full beat_group test file**

Run: `python -m pytest tests/test_beat_group_parallel.py -v`
Expected: PASS (all classes)

- [ ] **Step 6: Commit**

```bash
git add Graph/beat_group.py tests/test_beat_group_parallel.py
git commit -m "feat(beat): apply_group_results with serial apply, flag merge, failure reporting"
```

---

## Task 9: run_beat_loop 改为按组消费

把 `run_beat_loop` 从"逐个 actor"改为"逐组"。当组大小为 1 时走原有单 actor 路径（保持行为等价）；组大小 > 1 时走并行组路径。narration/scene_end 在每组结算后触发。

**Files:**
- Modify: `Graph/beat_subgraph.py`
- Modify: `Graph/nodes.py` (`beat_resolution_node` 传入 resolve_agent + 组执行 hook)
- Test: `tests/test_beat_resolution.py` (add parallel-group case)

- [ ] **Step 1: Write the failing integration test**

Append a new test class to `tests/test_beat_resolution.py` (reuse existing `FakeDirector`, `FakeActor`, and the state/deps construction already present in that file — mirror the setup used by the existing tests there):

```python
class ParallelGroupBeatTest(unittest.TestCase):
    def test_group_of_two_both_speak_in_one_beat(self):
        # Build state/deps exactly like the existing tests in this file do,
        # with on_stage = ["npc_a", "npc_b"] (no player turn), then set:
        #   director brief who_should_respond = ["npc_a", "npc_b"]
        #   response_groups = [["npc_a", "npc_b"]]
        # Use FakeActor for both. After resolve_story_turn, assert BOTH
        # npc_a and npc_b have committed history entries in the same beat.
        ...
```

> Fill this in concretely by copying the state/deps builder from the nearest existing test in `tests/test_beat_resolution.py` (e.g. the tier/scheduler test). Set `state["runtime"]["pending_response_groups"] = [["npc_a", "npc_b"]]` and `pending_beat_actors = ["npc_a", "npc_b"]` before invoking the beat. Assert `[h["actor"] for h in result["history"] if h["actor"] in ("npc_a","npc_b")] == ["npc_a", "npc_b"]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_beat_resolution.py::ParallelGroupBeatTest -v`
Expected: FAIL — only one actor committed (loop still serial, consumes one at a time).

- [ ] **Step 3: Add group-aware consumption to run_beat_loop**

In `Graph/beat_subgraph.py`, add a helper and a group-execution parameter. Modify `run_beat_loop` signature to accept an optional `group_step`:

```python
def _next_group(state: GameState) -> list[str]:
    groups = state["runtime"].get("pending_response_groups", [])
    for group in groups:
        active = [
            cid for cid in group
            if cid in state["runtime"].get("eligible_actors", [])
        ]
        if active:
            return active
    return []
```

In the `while` loop, before the single-actor `scheduler_step`/`execution_subgraph` path, insert:

```python
        group = _next_group(current)
        if group_step is not None and len(group) > 1:
            current = group_step(current, group)
            # remove consumed group from pending_response_groups & pending_beat_actors
            consumed = set(group)
            current = {
                **current,
                "runtime": {
                    **current["runtime"],
                    "pending_response_groups": [
                        [cid for cid in grp if cid not in consumed]
                        for grp in current["runtime"].get("pending_response_groups", [])
                    ],
                    "pending_beat_actors": [
                        cid for cid in current["runtime"].get("pending_beat_actors", [])
                        if cid not in consumed
                    ],
                    "next_act": None,
                },
            }
            # drop now-empty groups
            current["runtime"]["pending_response_groups"] = [
                grp for grp in current["runtime"]["pending_response_groups"] if grp
            ]
            resolved_turns += 1
            if current["runtime"].get("scene_finished") or current["runtime"].get("chapter_finished"):
                break
            continue
```

Add `group_step: Callable | None = None` to the signature (import `Callable` from typing if not present).

- [ ] **Step 4: Wire group_step in beat_resolution_node**

In `Graph/nodes.py` `beat_resolution_node`, build a `group_step` closure and pass it to `run_beat_loop`. Add after the `execution_subgraph` is resolved:

```python
    from Graph.beat_group import run_actor_group, apply_group_results
    from Graph.narration_nodes import narration_subgraph_node as _narrate

    def _group_step(current: GameState, group: list[str]) -> GameState:
        successes, failures = run_actor_group(
            current,
            group=group,
            resolve_agent=lambda actor_id: _resolve_agent_for_actor(current, deps, actor_id),
            character_profiles=deps.character_profiles,
            max_retries=3,
        )
        applied = apply_group_results(
            current,
            successes=successes,
            failures=failures,
            relationship_tuning=deps.gameplay_tuning.relationship,
            character_profiles=deps.character_profiles,
        )
        applied = cultivation_progress_node(applied, deps)
        applied = _narrate(applied, deps)
        return scene_end_node(applied, deps)
```

Extract the agent-selection logic from `actor_node` (the `agent_type` → L1/L2/actor `_resolve_component` block, lines ~432-456) into a module-level helper `_resolve_agent_for_actor(state, deps, actor_id)` and call it from both `actor_node` and `_group_step`. Then pass `group_step=_group_step` into the `run_beat_loop(...)` call.

- [ ] **Step 5: Run integration test to verify it passes**

Run: `python -m pytest tests/test_beat_resolution.py::ParallelGroupBeatTest -v`
Expected: PASS — both actors committed in one beat.

- [ ] **Step 6: Run full beat regression**

Run: `python -m pytest tests/test_beat_resolution.py tests/test_beat_subgraph_hooks.py -v`
Expected: PASS (size-1 groups preserve original serial behavior)

- [ ] **Step 7: Commit**

```bash
git add Graph/beat_subgraph.py Graph/nodes.py tests/test_beat_resolution.py
git commit -m "feat(beat): consume response groups, parallelizing multi-actor beats"
```

---

## Task 10: 全量回归 + 端到端

**Files:**
- (No new files; validation task)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest`
Expected: All previously-passing tests (was 82 passed) still pass, plus the new tests. If any fail, fix inline before proceeding.

- [ ] **Step 2: Verify heuristic degrade path**

Run: `python demo_run.py --mode heuristic --rounds 3`
Expected: Runs to completion without error (heuristic mode → serial per-actor groups, no ThreadPool regressions).

- [ ] **Step 3: Sanity-check no serial-behavior regression**

Confirm: a beat where Director returns `response_groups` with all size-1 groups produces identical history ordering to pre-change behavior (covered by existing `test_beat_resolution.py` tests passing).

- [ ] **Step 4: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test(beat): full regression for parallel response groups"
```

---

## Self-Review Notes

- **Spec coverage:** §3 分组 → Tasks 1-5; §4 组内并行 → Task 7; §5 冲突合并 → Tasks 6, 8; §6 重试/部分成功 → Tasks 7, 8; §7 模块清单 → all tasks; §8 测试 → Tasks 3,5,6,7,8,9,10.
- **Interrupt handling (§5.2):** Task 4 uses the "allow_interrupt → focus solo group" deterministic approximation (documented, since schema has no explicit interrupt-actor field).
- **relationship/emotion/history merge (§5.2 叠加/原序回收):** handled implicitly by Task 8 calling `apply_resolved_act` per actor in priority order — the existing `_merge_additive_mapping` already accumulates. No separate merge function needed (avoids duplicating ActorRuntime logic).
- **Front-end unchanged:** `web_session` untouched; failures surface via the system history message added in Task 8, which `_serialize_history_entry` already renders (`message_kind == "system"`).
