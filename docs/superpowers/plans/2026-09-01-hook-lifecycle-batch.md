# Hook 生命周期统一与响应组批处理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make serial, parallel-group, flush, and wrap-up Beat paths obey the same 12-point Hook lifecycle while committing parallel actor results as one deterministic batch.

**Architecture:** Stage every actor result in `runtime.resolved_acts` and consume it from the first default `actor.after` Hook. A new `ActorGroupNode` uses the existing `HookableNode` lifecycle once per response group; normal actor nodes stage a one-element batch. Flush and wrap-up use their existing hookable wrappers rather than raw functions.

**Tech Stack:** Python 3.11+, TypedDict, unittest/pytest, LangGraph-compatible `GameState` nodes.

**Spec:** `docs/superpowers/specs/2026-09-01-hook-lifecycle-batch-design.md`

## Global Constraints

- Use Python 3.11 or newer: this repository imports `typing.NotRequired` directly.
- Do not add third-party runtime dependencies or a new DI/factory layer.
- Preserve the existing group-start snapshot, scheduler order, retry semantics, narration batching, and fail-fast exception propagation.
- Only the twelve Hook points in the spec are legal; unknown point registration raises `ValueError`.
- Default Hook registration is silently idempotent and must not clear custom hooks.
- The current checkout is dirty. Execute in an isolated worktree and commit only the files listed in each task.

---

## File Structure

| File | Change |
| --- | --- |
| `GameState.py` | Define `ActorFailure`; add initialized actor-batch runtime fields. |
| `Actor/ActorRuntime.py` | Add batch commit function that reuses `apply_resolved_act` and writes group failure events afterward. |
| `Graph/beat_group.py` | Replace direct commits with a staging function that preserves ordered actions and merged group flags. |
| `Graph/hooks.py` | Define and validate the 12 supported Hook point names. |
| `Graph/hookable_node.py` | Add successful-after-chain finalization hook. |
| `Graph/beat_nodes.py` | Stage serial actions, add `ActorGroupNode`, and clear staged batch only after successful actor after-hooks. |
| `Graph/dependencies.py` | Record whether default hooks were installed. |
| `Graph/dialogue_nodes.py` | Route group, forced flush, and wrap-up paths through hookable nodes. |
| `session_bootstrap.py` | Register batch commit default Hook once per dependency bundle. |
| `tests/test_hooks.py` | Cover accepted/unknown Hook points and preserve test-only valid point usage. |
| `tests/test_hookable_node.py` | Cover finalization only after a successful after-hook chain. |
| `tests/test_beat_group_parallel.py` | Cover group staging, ordered batch commit, and failure-event order. |
| `tests/test_beat_subgraph_hooks.py` | Cover idempotent default registration and the extended Hook taxonomy. |
| `tests/test_beat_resolution.py` | Cover full serial/group/flush/wrap lifecycle traces and failure short-circuiting. |

## Interfaces

```python
# GameState.py
class ActorFailure(TypedDict):
    actor_id: str
    error: str

# Actor/ActorRuntime.py
def apply_resolved_act_batch(
    state: GameState,
    relationship_tuning: RelationshipTuning | None = None,
    *,
    character_profiles: dict[str, CharacterProfile] | None = None,
) -> GameState: ...

# Graph/beat_group.py
def stage_group_results(
    state: GameState,
    *,
    successes: list[tuple[str, ResolvedAct]],
    failures: list[tuple[str, str]],
) -> GameState: ...

# Graph/hooks.py
HOOK_POINTS: frozenset[str]

# Graph/hookable_node.py
def finalize(self, state: GameState) -> GameState: ...
```

### Task 1: Lock the Hook taxonomy and finalize lifecycle

**Files:**
- Modify: `Graph/hooks.py:8-37`
- Modify: `Graph/hookable_node.py:9-44`
- Modify: `tests/test_hooks.py:21-79`
- Modify: `tests/test_hookable_node.py:22-77`

**Consumes:** Existing `HookRegistry` registration order and `HookableNode.as_step()` behavior.

**Produces:** `HOOK_POINTS`, `HookRegistry.register()` validation, and a `HookableNode.finalize()` extension invoked only after all after-hooks succeed.

- [ ] **Step 1: Write failing registry and finalization tests**

  Replace arbitrary points in `tests/test_hooks.py` with legal points, then add:

  ```python
  def test_register_rejects_unknown_hook_point(self):
      registry = HookRegistry()
      with self.assertRaisesRegex(ValueError, "unknown hook point"):
          registry.register("actor.afetr", lambda state: state)
  ```

  In `tests/test_hookable_node.py`, make `_EchoNode.name = "actor"`, add a `_FinalizingNode` that appends `"finalize"`, and assert:

  ```python
  self.assertEqual(result["trace"], ["before", "run", "after", "finalize"])
  ```

  Add a failing-after-hook test that asserts `finalize` was not called.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

  Run: `python -m pytest -q tests/test_hooks.py tests/test_hookable_node.py`

  Expected: failures for the missing Hook-point validation and missing `finalize` behavior; existing tests with arbitrary point names are updated before this command.

- [ ] **Step 3: Implement the minimum registry and lifecycle changes**

  In `Graph/hooks.py`, declare the exact point set and validate before append:

  ```python
  HOOK_POINTS = frozenset(
      f"{name}.{phase}"
      for name in (
          "director_lead_in", "actor", "narration",
          "cultivation_progress", "scene_end", "director_wrap_up",
      )
      for phase in ("before", "after")
  )

  def register(self, hook_point: str, fn: HookFn) -> None:
      if hook_point not in HOOK_POINTS:
          raise ValueError(f"unknown hook point: {hook_point}")
      self._hooks.setdefault(hook_point, []).append(fn)
  ```

  In `Graph/hookable_node.py`, add a concrete no-op finalizer and call it after the after-hook chain:

  ```python
  def finalize(self, state: GameState) -> GameState:
      return state

  def as_step(self) -> NodeStep:
      def _step(state: GameState) -> GameState:
          state = self._registry.emit(self.hook_point_before, state)
          state = self.run(state)
          state = self._registry.emit(self.hook_point_after, state)
          return self.finalize(state)
      return _step
  ```

- [ ] **Step 4: Run focused tests and verify success**

  Run: `python -m pytest -q tests/test_hooks.py tests/test_hookable_node.py`

  Expected: PASS.

- [ ] **Step 5: Commit the isolated-worktree task**

  ```bash
  git add Graph/hooks.py Graph/hookable_node.py tests/test_hooks.py tests/test_hookable_node.py
  git commit -m "feat: validate hook points and finalize nodes"
  ```

### Task 2: Stage and commit actor-result batches

**Files:**
- Modify: `GameState.py:108-179`
- Modify: `Actor/ActorRuntime.py:298-390`
- Modify: `Graph/beat_group.py:7,135-191`
- Modify: `tests/test_beat_group_parallel.py:18,213-241`

**Consumes:** `ResolvedAct`, `apply_resolved_act`, `merge_group_flags`, and the ordering returned by `run_actor_group`.

**Produces:** `ActorFailure`, initialized `resolved_acts` / `pending_actor_failures`, `stage_group_results()`, and `apply_resolved_act_batch()`.

- [ ] **Step 1: Write failing staging and batch-commit tests**

  Replace `apply_group_results` imports/usages with `stage_group_results` plus `apply_resolved_act_batch`. Add tests that assert:

  ```python
  staged = stage_group_results(state, successes=acts, failures=[("b", "timeout")])
  self.assertEqual([act["actor"] for act in staged["runtime"]["resolved_acts"]], ["a"])
  self.assertEqual(staged["runtime"]["pending_actor_failures"], [{"actor_id": "b", "error": "timeout"}])
  self.assertEqual(staged["history"], state["history"])

  committed = apply_resolved_act_batch(staged)
  self.assertEqual([item["actor"] for item in committed["history"]], ["a", None])
  self.assertEqual(committed["runtime"]["resolved_act"]["actor"], "a")
  ```

  Add a two-success test verifying history actor order remains `a`, then `b`, and add a group-flag test that verifies the staged final action receives the existing priority-based flags.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

  Run: `python -m pytest -q tests/test_beat_group_parallel.py`

  Expected: import failure for `stage_group_results` and `apply_resolved_act_batch`.

- [ ] **Step 3: Add runtime types and defaults**

  In `GameState.py`, define `ActorFailure` next to `ResolvedAct`, add these `RuntimeState` fields, and initialize both to empty lists in `create_runtime_state`:

  ```python
  resolved_acts: list[ResolvedAct]
  pending_actor_failures: list[ActorFailure]
  ```

- [ ] **Step 4: Implement domain batch commit**

  Add `apply_resolved_act_batch` below `apply_resolved_act`. It must loop through a snapshot of `state["runtime"]["resolved_acts"]`, set each item as `runtime.resolved_act`, and call the existing `apply_resolved_act` once per item. After all successful actions, append exactly one existing-format system history event when `pending_actor_failures` is nonempty:

  ```python
  failures = list(current["runtime"].get("pending_actor_failures", []))
  if failures:
      failed_ids = "、".join(item["actor_id"] for item in failures)
      next_turn = int(current["runtime"]["turn_index"]) + 1
      current = {
          **current,
          "history": [*current["history"], {"turn": next_turn, "actor": None,
              "mode": "event", "content": f"（系统）以下角色本轮生成失败，已跳过：{failed_ids}。",
              "spoken_text": "", "nonverbal_action": "", "message_kind": "system",
              "on_stage": list(current["scene"].get("on_stage", [])),
              "location_id": current["scene"].get("location_id", "")}],
          "runtime": {**current["runtime"], "turn_index": next_turn},
      }
  return current
  ```

  Do not clear either staging field here.

- [ ] **Step 5: Replace direct group commits with staging**

  Replace `apply_group_results` in `Graph/beat_group.py` with `stage_group_results`. Copy each success action, merge `merge_group_flags(successes)` into the final copied action exactly as the old function did, then return a state whose runtime contains:

  ```python
  "resolved_acts": ordered_acts,
  "pending_actor_failures": [
      {"actor_id": actor_id, "error": error}
      for actor_id, error in failures
  ],
  "resolved_act": ordered_acts[-1] if ordered_acts else None,
  ```

  This function must not modify history, characters, plot flags, turn index, or pending actor queues.

- [ ] **Step 6: Run focused tests and verify success**

  Run: `python -m pytest -q tests/test_beat_group_parallel.py`

  Expected: PASS, including same-snapshot, retry, group-flag, action-order, and failure-event tests.

- [ ] **Step 7: Commit the isolated-worktree task**

  ```bash
  git add GameState.py Actor/ActorRuntime.py Graph/beat_group.py tests/test_beat_group_parallel.py
  git commit -m "feat: stage and commit actor batches"
  ```

### Task 3: Route every Beat path through hookable nodes

**Files:**
- Modify: `Graph/beat_nodes.py:1-93`
- Modify: `Graph/dialogue_nodes.py:69-127`
- Modify: `session_bootstrap.py:486-509`
- Modify: `tests/test_beat_subgraph_hooks.py:159-203`
- Modify: `tests/test_beat_resolution.py:722-855`

**Consumes:** `stage_group_results`, `run_actor_group`, `HookableNode.finalize`, and existing node wrappers.

**Produces:** `ActorGroupNode`, staged serial actor output, hookable group/flush/wrap paths, and end-to-end lifecycle tests.

- [ ] **Step 1: Write failing lifecycle tests**

  In `tests/test_beat_resolution.py`, build a one-actor serial Beat and a two-actor response-group Beat using its existing fake agents. Register trace Hooks for all twelve allowed points, then assert each run records this exact lifecycle:

  ```python
  [
      "director_lead_in.before", "director_lead_in.after",
      "actor.before", "actor.after",
      "narration.before", "narration.after",
      "cultivation_progress.before", "cultivation_progress.after",
      "scene_end.before", "scene_end.after",
      "narration.before", "narration.after",  # forced flush
      "director_wrap_up.before", "director_wrap_up.after",
  ]
  ```

  The group assertion must verify `actor.before` and `actor.after` occur once each and that the two actors retain the same group-start history length. Add a custom `actor.after` trace Hook that asserts `len(state["runtime"]["resolved_acts"]) == 2` before finalization.

  Add a test registering an `actor.after` Hook that raises `RuntimeError("hook boom")`; assert `resolve_story_turn` raises and no narration/cultivation/scene-end/flush/wrap Hook trace appears afterward.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

  Run: `python -m pytest -q tests/test_beat_subgraph_hooks.py tests/test_beat_resolution.py`

  Expected: lifecycle trace failures because group, flush, and wrap still call raw functions; the group batch assertion also fails.

- [ ] **Step 3: Implement `ActorNode` staging and `ActorGroupNode`**

  In `Graph/beat_nodes.py`, make `ActorNode.run` call the existing `actor_node`, then stage its produced `resolved_act` as a one-element `resolved_acts` list when present. Override `finalize` in both actor classes to clear staging only after the complete after-hook chain:

  ```python
  def finalize(self, state: GameState) -> GameState:
      return {
          **state,
          "runtime": {
              **state["runtime"],
              "resolved_acts": [],
              "pending_actor_failures": [],
          },
      }
  ```

  Add `ActorGroupNode(HookableNode)` with constructor arguments `(deps, hook_registry, group, resolve_agent)`. Its `run` calls `run_actor_group`, then `stage_group_results`; `resolve_agent` has signature `Callable[[str, GameState], ActorAgent | None]` so `beat_nodes.py` does not import the private resolver from `dialogue_nodes.py`.

- [ ] **Step 4: Replace raw group and closing calls**

  In `beat_resolution_node`, lazily import `ActorGroupNode` and `DirectorWrapUpNode` with the existing wrappers. Implement `_group_step` only with `.as_step()` calls:

  ```python
  lead_in = DirectorLeadInNode(deps, registry).as_step()
  actor_group = ActorGroupNode(
      deps, registry, group,
      resolve_agent=lambda actor_id, group_state: _resolve_agent_for_actor(deps, actor_id, group_state),
  ).as_step()
  narration = NarrationNode(deps, registry).as_step()
  cultivation = CultivationProgressNode(deps, registry).as_step()
  scene_end = SceneEndNode(deps, registry).as_step()
  return scene_end(cultivation(narration(actor_group(lead_in(current)))))
  ```

  Build `flush_step` and `wrap_step` once from `NarrationNode(deps, registry, force_flush=True).as_step()` and `DirectorWrapUpNode(deps, registry).as_step()`. Remove imports that become unused after raw calls disappear.

- [ ] **Step 5: Wire the batch reducer into the existing default actor Hook**

  This is a causal prerequisite for the new group path: it stages all group actions, so the existing single-act default Hook would otherwise commit only the final actor. In `session_bootstrap.py`, import `apply_resolved_act_batch` and replace the existing `_history_commit` body with:

  ```python
  return apply_resolved_act_batch(
      state,
      deps.gameplay_tuning.relationship,
      character_profiles=deps.character_profiles,
  )
  ```

  Do not add the idempotence guard here; Task 4 owns that registration-lifecycle change.

- [ ] **Step 6: Run focused tests and verify success**

  Run: `python -m pytest -q tests/test_beat_subgraph_hooks.py tests/test_beat_resolution.py`

  Expected: PASS; serial and group traces include the forced-flush narration and wrap-up hooks, group actor hooks occur once, and an after-hook exception short-circuits the Beat.

- [ ] **Step 7: Commit the isolated-worktree task**

  ```bash
  git add Graph/beat_nodes.py Graph/dialogue_nodes.py session_bootstrap.py tests/test_beat_subgraph_hooks.py tests/test_beat_resolution.py
  git commit -m "feat: unify beat hook lifecycles"
  ```

### Task 4: Make default hooks batch-aware and idempotent

**Files:**
- Modify: `Graph/dependencies.py:25-66`
- Modify: `session_bootstrap.py:486-509`
- Modify: `tests/test_beat_subgraph_hooks.py:92-156`

**Consumes:** `GraphDependencies` and the valid `actor.after` / `narration.after` Hook points.

**Produces:** One-time default registration and regression coverage for repeated setup; Task 3 has already made the default actor commit batch-aware.

- [ ] **Step 1: Write failing idempotence and batch-default tests**

  Add a test that calls `register_default_hooks(deps)` twice and asserts:

  ```python
  self.assertTrue(deps.default_hooks_registered)
  self.assertEqual(len(deps.hook_registry._hooks["actor.after"]), 2)
  self.assertEqual(len(deps.hook_registry._hooks["narration.after"]), 1)
  ```

  Register a custom legal `scene_end.after` Hook before both calls and assert it remains registered. Keep the existing batch-commit coverage as a regression assertion; Task 3 supplies that wiring before this task begins.

- [ ] **Step 2: Run the focused test and verify the expected failure**

  Run: `python -m pytest -q tests/test_beat_subgraph_hooks.py`

  Expected: repeated registration creates four actor hooks and two narration hooks.

- [ ] **Step 3: Implement idempotent defaults**

  Add `default_hooks_registered: bool = False` to `GraphDependencies`. In `register_default_hooks`, guard before defining or registering closures:

  ```python
  if deps.default_hooks_registered:
      return
  ```

  Keep the batch-aware `_history_commit` added in Task 3. Leave `_contextual_progression` second and `_refresh_history` at `narration.after`. Set `deps.default_hooks_registered = True` only after all three registrations succeed.

- [ ] **Step 4: Run focused tests and verify success**

  Run: `python -m pytest -q tests/test_beat_subgraph_hooks.py`

  Expected: PASS; repeated setup is a no-op, custom hooks remain, and actor batch commit precedes contextual progression.

- [ ] **Step 5: Commit the isolated-worktree task**

  ```bash
  git add Graph/dependencies.py session_bootstrap.py tests/test_beat_subgraph_hooks.py
  git commit -m "fix: register default batch hooks once"
  ```

### Task 5: Run regressions and verify the written contract

**Files:**
- Modify: `docs/superpowers/specs/2026-09-01-hook-lifecycle-batch-design.md` only if implementation required an approved wording correction.
- Test: `tests/test_hooks.py`
- Test: `tests/test_hookable_node.py`
- Test: `tests/test_beat_group_parallel.py`
- Test: `tests/test_beat_subgraph_hooks.py`
- Test: `tests/test_beat_resolution.py`
- Test: `tests/test_beat_loop_streaming.py`
- Test: `tests/test_contextual_scene_handoffs.py`
- Test: `tests/test_narrator_intro_flow.py`

**Consumes:** All prior completed tasks.

**Produces:** Fresh verification evidence that the lifecycle contract and prior Beat behavior both hold.

- [ ] **Step 1: Run the focused lifecycle suite**

  Run: `python -m pytest -q tests/test_hooks.py tests/test_hookable_node.py tests/test_beat_group_parallel.py tests/test_beat_subgraph_hooks.py tests/test_beat_resolution.py`

  Expected: PASS with no skipped or xfailed lifecycle tests.

- [ ] **Step 2: Run dependent regression tests**

  Run: `python -m pytest -q tests/test_beat_loop_streaming.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_prepare_chapter_turn_parallel.py`

  Expected: PASS; no duplicate stream events, no lost scene handoff, and no narration regression.

- [ ] **Step 3: Run the full suite**

  Run: `python -m pytest -q`

  Expected: PASS.

- [ ] **Step 4: Inspect the final change scope**

  Run: `git diff --check HEAD~4..HEAD && git diff --stat HEAD~4..HEAD`

  Expected: no whitespace errors; only the planned graph, actor-runtime, state, bootstrap, test, spec, and plan files appear.

- [ ] **Step 5: Commit any approved spec wording correction only when needed**

  ```bash
  git add docs/superpowers/specs/2026-09-01-hook-lifecycle-batch-design.md
  git commit -m "docs: align hook lifecycle spec"
  ```
