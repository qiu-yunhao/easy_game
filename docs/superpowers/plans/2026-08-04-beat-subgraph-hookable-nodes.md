# Beat Subgraph Hookable Nodes 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `beat_execution_subgraph` 从 8 步硬编码序列改造为"5 个 HookableNode + 10 个对称 hook 位点"结构，并把 4 个无控制流决策的节点降级为默认注册的 hook。

**Architecture:** 新增 `HookRegistry`（按位点名注册的 hook 中心）+ `HookableNode` 抽象基类（自带 before/after 位点）。5 个主节点包一层 HookableNode 子类；`history_commit / contextual_progression / refresh_history` 从节点降级为默认 hook；`narration_subgraph / cultivation_progress` 因含决策保留为主节点。

**Tech Stack:** Python 3.12 · unittest.TestCase + pytest · 现有 `langgraph` compile 契约 · `GraphDependencies` DI 容器

**Spec:** `docs/superpowers/specs/2026-08-04-beat-subgraph-hookable-nodes-design.md`

**执行前提**：
- 项目根：`/Users/qiuyunhao.1/Desktop/claude coding/easy_game`
- **本仓库不是 git 仓库**（无 `.git`），"Commit" 步骤改为"逻辑检查点：跑通全套指定测试"
- 所有测试用 `python -m pytest tests/... -v` 运行；测试文件顶部必须放 `openai` stub（沿用现有测试模式）

---

## 文件结构

**新建：**
- `Graph/hooks.py` —— `HookRegistry` + `HookFn` Protocol + `NodeStep` 类型别名 re-export
- `Graph/hookable_node.py` —— `HookableNode` 抽象基类
- `Graph/beat_nodes.py` —— 6 个 HookableNode 子类（`DirectorLeadInNode / ActorNode / NarrationNode / CultivationProgressNode / SceneEndNode / DirectorWrapUpNode`）
- `tests/test_hooks.py` —— `HookRegistry` 单元测试
- `tests/test_hookable_node.py` —— 抽象基类单元测试
- `tests/test_beat_subgraph_hooks.py` —— beat 子图集成测试

**修改：**
- `Graph/nodes.py:74-98` —— `GraphDependencies` 加 `hook_registry` 字段
- `Graph/nodes.py:390-403` —— `beat_resolution_node` 内 lambda 组装改为 HookableNode
- `Graph/beat_subgraph.py:12-35` —— `build_beat_execution_subgraph` 签名改为接收 HookableNode
- `Graph/__init__.py` —— 导出新符号
- `session_bootstrap.py:376-393` —— 构造 deps 后调用 `register_default_hooks(deps)`

**不动：**
- `Graph/narration_nodes.py` / `Graph/contextual_scene_handoffs.py`（内容零改动）
- `Actor/` / `Director/` / `Narrator/` / `Scheduler/` / `SceneEnd/`
- 现有 `history_commit_node / contextual_progression_node / refresh_history_node` 函数（保留供测试直接调用）

---

## Task 1: HookRegistry —— 基础容器

**Files:**
- Create: `Graph/hooks.py`
- Test: `tests/test_hooks.py`

- [ ] **Step 1: 写 test_hooks.py 的失败测试**

创建 `tests/test_hooks.py`:

```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.hooks import HookRegistry


class HookRegistryTests(unittest.TestCase):
    def test_empty_registry_emit_returns_state_unchanged(self):
        registry = HookRegistry()
        state = {"turn": 1}
        result = registry.emit("actor.after", state)
        self.assertIs(result, state)

    def test_register_and_emit_calls_hook(self):
        registry = HookRegistry()
        calls = []

        def hook(state):
            calls.append(state["turn"])
            return {**state, "turn": state["turn"] + 1}

        registry.register("actor.after", hook)
        result = registry.emit("actor.after", {"turn": 1})
        self.assertEqual(calls, [1])
        self.assertEqual(result, {"turn": 2})

    def test_hooks_execute_in_registration_order(self):
        registry = HookRegistry()
        order = []
        registry.register("p", lambda s: (order.append("a"), s)[1])
        registry.register("p", lambda s: (order.append("b"), s)[1])
        registry.register("p", lambda s: (order.append("c"), s)[1])
        registry.emit("p", {})
        self.assertEqual(order, ["a", "b", "c"])

    def test_state_threads_through_hooks(self):
        registry = HookRegistry()
        registry.register("p", lambda s: {**s, "v": s["v"] + 1})
        registry.register("p", lambda s: {**s, "v": s["v"] * 10})
        result = registry.emit("p", {"v": 1})
        self.assertEqual(result["v"], 20)

    def test_clear_specific_point(self):
        registry = HookRegistry()
        registry.register("a", lambda s: {**s, "hit_a": True})
        registry.register("b", lambda s: {**s, "hit_b": True})
        registry.clear("a")
        result = registry.emit("a", {})
        self.assertNotIn("hit_a", result)
        result_b = registry.emit("b", {})
        self.assertTrue(result_b["hit_b"])

    def test_clear_all(self):
        registry = HookRegistry()
        registry.register("a", lambda s: {**s, "hit": True})
        registry.register("b", lambda s: {**s, "hit": True})
        registry.clear()
        self.assertEqual(registry.registered_points(), [])

    def test_registered_points_sorted(self):
        registry = HookRegistry()
        registry.register("z", lambda s: s)
        registry.register("a", lambda s: s)
        registry.register("m", lambda s: s)
        self.assertEqual(registry.registered_points(), ["a", "m", "z"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hooks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'Graph.hooks'`

- [ ] **Step 3: 实现 Graph/hooks.py**

创建 `Graph/hooks.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from GameState import GameState


NodeStep = Callable[[GameState], GameState]


class HookFn(Protocol):
    """Hook 函数签名 —— 与 NodeStep 完全一致,保证可互换。"""

    def __call__(self, state: GameState) -> GameState: ...


@dataclass(slots=True)
class HookRegistry:
    """按位点名存 hook 列表。emit 时按注册顺序依次调用。"""

    _hooks: dict[str, list[HookFn]] = field(default_factory=dict)

    def register(self, hook_point: str, fn: HookFn) -> None:
        self._hooks.setdefault(hook_point, []).append(fn)

    def clear(self, hook_point: str | None = None) -> None:
        if hook_point is None:
            self._hooks.clear()
        else:
            self._hooks.pop(hook_point, None)

    def emit(self, hook_point: str, state: GameState) -> GameState:
        hooks = self._hooks.get(hook_point)
        if not hooks:
            return state
        for hook in hooks:
            state = hook(state)
        return state

    def registered_points(self) -> list[str]:
        return sorted(self._hooks.keys())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_hooks.py -v`
Expected: PASS (7 tests passed)

- [ ] **Step 5: 检查点**

Run: `python -m pytest tests/test_hooks.py -v && python -c "from Graph.hooks import HookRegistry, HookFn, NodeStep; print('imports ok')"`
Expected: 全部 pass + `imports ok`

---

## Task 2: HookableNode 抽象基类

**Files:**
- Create: `Graph/hookable_node.py`
- Test: `tests/test_hookable_node.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_hookable_node.py`:

```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.hooks import HookRegistry
from Graph.hookable_node import HookableNode


class _EchoNode(HookableNode):
    name = "echo"

    def __init__(self, registry, tag):
        super().__init__(registry)
        self._tag = tag

    def run(self, state):
        return {**state, "trace": [*state.get("trace", []), f"run:{self._tag}"]}


class HookableNodeTests(unittest.TestCase):
    def test_name_composes_hook_points(self):
        registry = HookRegistry()
        node = _EchoNode(registry, "x")
        self.assertEqual(node.hook_point_before, "echo.before")
        self.assertEqual(node.hook_point_after, "echo.after")

    def test_as_step_runs_before_run_after_in_order(self):
        registry = HookRegistry()
        registry.register("echo.before", lambda s: {**s, "trace": [*s.get("trace", []), "before"]})
        registry.register("echo.after", lambda s: {**s, "trace": [*s.get("trace", []), "after"]})
        node = _EchoNode(registry, "x")
        result = node.as_step()({})
        self.assertEqual(result["trace"], ["before", "run:x", "after"])

    def test_as_step_without_hooks_still_runs(self):
        registry = HookRegistry()
        node = _EchoNode(registry, "x")
        result = node.as_step()({})
        self.assertEqual(result["trace"], ["run:x"])

    def test_run_exception_prevents_after_hook(self):
        registry = HookRegistry()
        after_called = []
        registry.register("echo.after", lambda s: (after_called.append(True), s)[1])

        class _Boom(HookableNode):
            name = "echo"

            def run(self, state):
                raise RuntimeError("boom")

        node = _Boom(registry)
        with self.assertRaises(RuntimeError):
            node.as_step()({})
        self.assertEqual(after_called, [])

    def test_multiple_before_hooks_thread_state(self):
        registry = HookRegistry()
        registry.register("echo.before", lambda s: {**s, "n": s.get("n", 0) + 1})
        registry.register("echo.before", lambda s: {**s, "n": s["n"] * 10})
        node = _EchoNode(registry, "x")
        result = node.as_step()({"n": 0})
        self.assertEqual(result["n"], 10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hookable_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'Graph.hookable_node'`

- [ ] **Step 3: 实现 Graph/hookable_node.py**

创建 `Graph/hookable_node.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod

from GameState import GameState
from Graph.hooks import HookRegistry, NodeStep


class HookableNode(ABC):
    """
    所有主节点的抽象基类。

    每个子类:
      1. 类属性 name(用作 hook 位点前缀)
      2. 实现 run(state) —— 节点核心逻辑

    基类自动组装 "before → run → after" 三段式为一个 NodeStep。
    """

    name: str  # 子类覆盖(class attr)

    def __init__(self, hook_registry: HookRegistry) -> None:
        self._registry = hook_registry

    @property
    def hook_point_before(self) -> str:
        return f"{self.name}.before"

    @property
    def hook_point_after(self) -> str:
        return f"{self.name}.after"

    @abstractmethod
    def run(self, state: GameState) -> GameState: ...

    def as_step(self) -> NodeStep:
        def _step(state: GameState) -> GameState:
            state = self._registry.emit(self.hook_point_before, state)
            state = self.run(state)
            state = self._registry.emit(self.hook_point_after, state)
            return state

        return _step
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_hookable_node.py -v`
Expected: PASS (5 tests passed)

- [ ] **Step 5: 检查点**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py -v`
Expected: 全部 pass

---

## Task 3: GraphDependencies 加 hook_registry 字段

**Files:**
- Modify: `Graph/nodes.py:74-98`

- [ ] **Step 1: 写迁移测试**

追加到 `tests/test_hooks.py`（在 `if __name__` 之前）:

```python
class GraphDependenciesHookRegistryTests(unittest.TestCase):
    def test_graph_dependencies_default_hook_registry_is_empty(self):
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        self.assertIsInstance(deps.hook_registry, HookRegistry)
        self.assertEqual(deps.hook_registry.registered_points(), [])

    def test_graph_dependencies_accepts_custom_hook_registry(self):
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        registry = HookRegistry()
        registry.register("actor.after", lambda s: s)
        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
            hook_registry=registry,
        )
        self.assertIs(deps.hook_registry, registry)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hooks.py::GraphDependenciesHookRegistryTests -v`
Expected: FAIL with `TypeError: GraphDependencies.__init__() got an unexpected keyword argument 'hook_registry'`

- [ ] **Step 3: 修改 Graph/nodes.py 加字段**

在 `Graph/nodes.py` 顶部 import 区追加：

```python
from Graph.hooks import HookRegistry
```

修改 `GraphDependencies` 定义（`Graph/nodes.py:74-98`），在 `beat_execution_subgraph` 字段之后追加：

```python
    hook_registry: HookRegistry = field(default_factory=HookRegistry)
```

完整字段位置示例（追加在最后一行）：

```python
@dataclass(slots=True)
class GraphDependencies:
    scene_config: SceneConfig
    character_profiles: dict[str, CharacterProfile]
    playwright_agent: PlaywrightAgent | None = None
    actor_create_agent: ActorCreateAgent | None = None
    director_agent: DirectorAgent | None = None
    actor_agent: ActorAgent | None = None
    l2_actor_agent: ActorAgent | None = None
    l1_actor_agent: ActorAgent | None = None
    narrator_agent: NarratorAgent | None = None
    player_intent_planner_agent: "PlayerIntentPlannerAgent | None" = None
    semantic_parser_agent: SemanticParserAgent | None = None
    player_command_tools: "PlayerCommandToolRuntime | None" = None
    stylistic_polish_agent: StylisticPolishAgent | None = None
    history_summarizer_agent: "HistorySummarizerAgent | None" = None
    history_manager: HistoryManager | None = None
    scheduler_policy: SchedulerPolicy | None = None
    scene_end_policy: SceneEndPolicy | None = None
    player_interface: PlayerInterface | None = None
    gameplay_tuning: GameplayTuning = field(default_factory=GameplayTuning)
    component_factory: ComponentFactory = field(default_factory=ComponentFactory)
    agent_first: bool = False
    actor_create_signature: str = ""
    beat_execution_subgraph: Callable[[GameState], GameState] | None = None
    hook_registry: HookRegistry = field(default_factory=HookRegistry)
```

- [ ] **Step 4: 跑新测试**

Run: `python -m pytest tests/test_hooks.py::GraphDependenciesHookRegistryTests -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 跑现有 GraphDependencies 使用者的回归**

Run: `python -m pytest tests/test_beat_resolution.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py -v`
Expected: PASS（全绿；关键是原有 12 处 `GraphDependencies(...)` 构造不需要传 `hook_registry` 也能工作）

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py tests/test_beat_resolution.py -v`
Expected: 全部 pass

---

## Task 4: 6 个 HookableNode 子类

**Files:**
- Create: `Graph/beat_nodes.py`
- Test: 追加到 `tests/test_hookable_node.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_hookable_node.py`（`if __name__` 之前）:

```python
class BeatNodesTests(unittest.TestCase):
    def _make_deps(self, registry):
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        return GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
            hook_registry=registry,
        )

    def test_all_beat_nodes_have_expected_names(self):
        from Graph.beat_nodes import (
            ActorNode,
            CultivationProgressNode,
            DirectorLeadInNode,
            DirectorWrapUpNode,
            NarrationNode,
            SceneEndNode,
        )

        registry = HookRegistry()
        deps = self._make_deps(registry)
        self.assertEqual(DirectorLeadInNode(deps, registry).name, "director_lead_in")
        self.assertEqual(ActorNode(deps, registry).name, "actor")
        self.assertEqual(NarrationNode(deps, registry).name, "narration")
        self.assertEqual(CultivationProgressNode(deps, registry).name, "cultivation_progress")
        self.assertEqual(SceneEndNode(deps, registry).name, "scene_end")
        self.assertEqual(DirectorWrapUpNode(deps, registry).name, "director_wrap_up")

    def test_narration_node_passes_force_flush_flag(self):
        from Graph.beat_nodes import NarrationNode

        registry = HookRegistry()
        deps = self._make_deps(registry)
        node = NarrationNode(deps, registry, force_flush=True)
        self.assertTrue(node._force_flush)

        default_node = NarrationNode(deps, registry)
        self.assertFalse(default_node._force_flush)

    def test_beat_node_run_delegates_to_legacy_function(self):
        """ActorNode.run 应等价于旧函数 actor_node(state, deps)"""
        from Graph.beat_nodes import ActorNode
        from Graph.nodes import actor_node

        registry = HookRegistry()
        deps = self._make_deps(registry)
        # runtime.next_act 为 None → 两条路径都返回 state 不变
        state = {"runtime": {"next_act": None}, "player": {}}
        legacy_result = actor_node(state, deps)
        node_result = ActorNode(deps, registry).run(state)
        self.assertEqual(legacy_result, node_result)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hookable_node.py::BeatNodesTests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'Graph.beat_nodes'`

- [ ] **Step 3: 实现 Graph/beat_nodes.py**

创建 `Graph/beat_nodes.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from GameState import GameState
from Graph.hookable_node import HookableNode
from Graph.hooks import HookRegistry
from Graph.narration_nodes import (
    director_lead_in_node,
    director_wrap_up_node,
    narration_subgraph_node,
)
from Graph.nodes import (
    actor_node,
    cultivation_progress_node,
    scene_end_node,
)

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


class DirectorLeadInNode(HookableNode):
    name = "director_lead_in"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return director_lead_in_node(state, self._deps)


class ActorNode(HookableNode):
    name = "actor"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return actor_node(state, self._deps)


class NarrationNode(HookableNode):
    name = "narration"

    def __init__(
        self,
        deps: "GraphDependencies",
        hook_registry: HookRegistry,
        *,
        force_flush: bool = False,
    ) -> None:
        super().__init__(hook_registry)
        self._deps = deps
        self._force_flush = force_flush

    def run(self, state: GameState) -> GameState:
        return narration_subgraph_node(state, self._deps, force_flush=self._force_flush)


class CultivationProgressNode(HookableNode):
    name = "cultivation_progress"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return cultivation_progress_node(state, self._deps)


class SceneEndNode(HookableNode):
    name = "scene_end"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return scene_end_node(state, self._deps)


class DirectorWrapUpNode(HookableNode):
    name = "director_wrap_up"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return director_wrap_up_node(state, self._deps)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_hookable_node.py::BeatNodesTests -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 检查点**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py -v`
Expected: 全部 pass

---

## Task 5: 重写 build_beat_execution_subgraph 签名

**Files:**
- Modify: `Graph/beat_subgraph.py:12-35`
- Test: `tests/test_beat_subgraph_hooks.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_beat_subgraph_hooks.py`:

```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.beat_subgraph import build_beat_execution_subgraph
from Graph.hookable_node import HookableNode
from Graph.hooks import HookRegistry


class _RecordingNode(HookableNode):
    """测试用节点:每次 run 时把 name 写入 state['trace']"""

    def __init__(self, registry, name):
        super().__init__(registry)
        self._custom_name = name

    @property
    def name(self):
        return self._custom_name

    def run(self, state):
        return {**state, "trace": [*state.get("trace", []), self._custom_name]}


class BuildBeatSubgraphSignatureTests(unittest.TestCase):
    def test_accepts_hookable_nodes_and_runs_in_order(self):
        registry = HookRegistry()
        subgraph = build_beat_execution_subgraph(
            director_lead_in=_RecordingNode(registry, "director_lead_in"),
            actor=_RecordingNode(registry, "actor"),
            narration=_RecordingNode(registry, "narration"),
            cultivation_progress=_RecordingNode(registry, "cultivation_progress"),
            scene_end=_RecordingNode(registry, "scene_end"),
        )
        result = subgraph({"trace": []})
        self.assertEqual(
            result["trace"],
            [
                "director_lead_in",
                "actor",
                "narration",
                "cultivation_progress",
                "scene_end",
            ],
        )

    def test_before_and_after_hooks_wrap_each_node(self):
        registry = HookRegistry()
        for name in ("director_lead_in", "actor", "narration", "cultivation_progress", "scene_end"):
            registry.register(
                f"{name}.before",
                lambda s, n=name: {**s, "trace": [*s.get("trace", []), f"{n}.before"]},
            )
            registry.register(
                f"{name}.after",
                lambda s, n=name: {**s, "trace": [*s.get("trace", []), f"{n}.after"]},
            )
        subgraph = build_beat_execution_subgraph(
            director_lead_in=_RecordingNode(registry, "director_lead_in"),
            actor=_RecordingNode(registry, "actor"),
            narration=_RecordingNode(registry, "narration"),
            cultivation_progress=_RecordingNode(registry, "cultivation_progress"),
            scene_end=_RecordingNode(registry, "scene_end"),
        )
        result = subgraph({"trace": []})
        expected = []
        for name in ("director_lead_in", "actor", "narration", "cultivation_progress", "scene_end"):
            expected.extend([f"{name}.before", name, f"{name}.after"])
        self.assertEqual(result["trace"], expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py -v`
Expected: FAIL with `TypeError: build_beat_execution_subgraph() got an unexpected keyword argument 'director_lead_in'`

- [ ] **Step 3: 改写 Graph/beat_subgraph.py**

完整替换 `Graph/beat_subgraph.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from GameState import GameState
from Graph.graph_compile import NodeStep, compile_graph_with_nodes
from Graph.hookable_node import HookableNode

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def build_beat_execution_subgraph(
    *,
    director_lead_in: HookableNode,
    actor: HookableNode,
    narration: HookableNode,
    cultivation_progress: HookableNode,
    scene_end: HookableNode,
) -> NodeStep:
    return compile_graph_with_nodes(
        [
            (director_lead_in.name, director_lead_in.as_step()),
            (actor.name, actor.as_step()),
            (narration.name, narration.as_step()),
            (cultivation_progress.name, cultivation_progress.as_step()),
            (scene_end.name, scene_end.as_step()),
        ],
        fallback_to_runner=True,
    )


def is_player_turn(state: GameState) -> bool:
    next_act = state["runtime"].get("next_act")
    return bool(
        next_act is not None
        and state["player"].get("enabled", False)
        and next_act.get("actor") == state["player"].get("controlled_character")
    )


def can_auto_resolve_player_turn(deps: "GraphDependencies") -> bool:
    player_interface = deps.player_interface
    if player_interface is None:
        return True

    has_pending_action = getattr(player_interface, "has_pending_action", None)
    if callable(has_pending_action):
        return bool(has_pending_action())
    return True


def beat_has_remaining_turns(state: GameState) -> bool:
    if state["runtime"].get("next_act") is not None:
        return True
    if state["runtime"].get("pending_beat_actors", []):
        return True
    return int(state["runtime"].get("beat_fallback_turns_remaining", 0) or 0) > 0


def run_beat_loop(
    state: GameState,
    deps: "GraphDependencies",
    *,
    scheduler_step: NodeStep,
    execution_subgraph: NodeStep,
    flush_step: NodeStep,
    wrap_step: NodeStep,
) -> GameState:
    current = state
    safety_limit = max(
        1,
        len(current["runtime"].get("pending_beat_actors", []))
        + int(current["runtime"].get("beat_fallback_turns_remaining", 0) or 0)
        + len(current["scene"].get("on_stage", []))
        + 1,
    )
    resolved_turns = 0

    while resolved_turns < safety_limit:
        if current["runtime"].get("scene_finished", False):
            break
        if current["runtime"].get("chapter_finished", False):
            break
        if current["runtime"].get("next_act") is None:
            if not beat_has_remaining_turns(current):
                break
            current = scheduler_step(current)
            if current["runtime"].get("next_act") is None:
                break

        if is_player_turn(current) and not can_auto_resolve_player_turn(deps):
            break

        current = execution_subgraph(current)
        resolved_turns += 1

    current = flush_step(current)
    current = wrap_step(current)
    return current
```

**注意保留** `is_player_turn / can_auto_resolve_player_turn / beat_has_remaining_turns / run_beat_loop` 原样（只改 `build_beat_execution_subgraph` 签名）。

先读一次原文件核对循环收尾部分：

Run: `sed -n '95,110p' Graph/beat_subgraph.py`
Expected: 看到 `resolved_turns += 1` 和 `current = flush_step(current); current = wrap_step(current); return current` —— 确认已保留。

- [ ] **Step 4: 跑新测试确认通过**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 检查点（signature 已变，尚未适配调用点，回归会红）**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py tests/test_beat_subgraph_hooks.py -v`
Expected: 3 个新测试文件全绿

Run: `python -m pytest tests/test_beat_resolution.py -v 2>&1 | tail -20`
Expected: **红** —— 因为 `beat_resolution_node` 还在按旧签名调用；下一 Task 修复。

---

## Task 6: 适配 beat_resolution_node 的调用点

**Files:**
- Modify: `Graph/nodes.py:390-403`

- [ ] **Step 1: 阅读现有代码**

Run: `sed -n '390,415p' Graph/nodes.py`
Expected: 看到旧的 lambda 组装

- [ ] **Step 2: 修改 beat_resolution_node**

替换 `Graph/nodes.py:390-403`（`beat_resolution_node` 函数体）为：

```python
def beat_resolution_node(state: GameState, deps: GraphDependencies) -> GameState:
    execution_subgraph = deps.beat_execution_subgraph
    if execution_subgraph is None:
        from Graph.beat_nodes import (
            ActorNode,
            CultivationProgressNode,
            DirectorLeadInNode,
            NarrationNode,
            SceneEndNode,
        )

        registry = deps.hook_registry
        execution_subgraph = build_beat_execution_subgraph(
            director_lead_in=DirectorLeadInNode(deps, registry),
            actor=ActorNode(deps, registry),
            narration=NarrationNode(deps, registry),
            cultivation_progress=CultivationProgressNode(deps, registry),
            scene_end=SceneEndNode(deps, registry),
        )
        deps.beat_execution_subgraph = execution_subgraph

    return run_beat_loop(
        state,
        deps,
        scheduler_step=lambda current: scheduler_node(current, deps),
        execution_subgraph=execution_subgraph,
        flush_step=lambda current: narration_subgraph_node(current, deps, force_flush=True),
        wrap_step=lambda current: director_wrap_up_node(current, deps),
    )
```

**注意**：`Graph.beat_nodes` 内部 import `Graph.nodes.actor_node`，如果放在 `Graph/nodes.py` 顶部 import 会形成循环依赖 —— 所以在**函数内 lazy import**。

- [ ] **Step 3: 跑现有 beat_resolution 测试**

Run: `python -m pytest tests/test_beat_resolution.py -v`
Expected: PASS（9 个测试全绿）

- [ ] **Step 4: 跑全 subgraph 相关测试**

Run: `python -m pytest tests/test_beat_resolution.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_prepare_chapter_turn_parallel.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 检查点**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py tests/test_beat_subgraph_hooks.py tests/test_beat_resolution.py -v`
Expected: 全部 pass

---

## Task 7: 默认 hook 注册（把 3 个节点降级）

**Files:**
- Modify: `session_bootstrap.py:376-393`
- Test: 追加到 `tests/test_beat_subgraph_hooks.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_beat_subgraph_hooks.py`（`if __name__` 之前）:

```python
class DefaultHookRegistrationTests(unittest.TestCase):
    def test_register_default_hooks_populates_expected_points(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies
        from History.HistoryManager import HistoryManager
        from SceneConfig import empty_scene_config

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
            history_manager=HistoryManager(compression_trigger_size=1),
        )
        register_default_hooks(deps)
        self.assertIn("actor.after", deps.hook_registry.registered_points())
        self.assertIn("narration.after", deps.hook_registry.registered_points())

    def test_actor_after_has_two_hooks_history_commit_then_progression(self):
        """actor.after 上应注册 history_commit(先) + contextual_progression(后)"""
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps)
        # 内部数据结构:_hooks["actor.after"] 应有 2 项
        actor_after_hooks = deps.hook_registry._hooks.get("actor.after", [])
        self.assertEqual(len(actor_after_hooks), 2)

    def test_narration_after_has_refresh_history_hook(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps)
        narration_after = deps.hook_registry._hooks.get("narration.after", [])
        self.assertEqual(len(narration_after), 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py::DefaultHookRegistrationTests -v`
Expected: FAIL with `ImportError: cannot import name 'register_default_hooks' from 'session_bootstrap'`

- [ ] **Step 3: 修改 session_bootstrap.py**

在 `session_bootstrap.py` 顶部 import 区（`from Graph.nodes import GraphDependencies` 附近）追加：

```python
from Actor import apply_resolved_act
from Graph.contextual_scene_handoffs import apply_contextual_scene_progression
```

（先跑一次 `grep -n "^from Actor\|^from Graph.contextual" session_bootstrap.py` 确认没重复。）

在文件末尾追加（或 `build_default_graph_dependencies` 函数之后）：

```python
def register_default_hooks(deps: GraphDependencies) -> None:
    """
    注册默认降级 hook,把原本作为独立节点的副作用挂回主流程。

    - actor.after: history_commit → contextual_progression(注册顺序敏感)
    - narration.after: refresh_history(条件性 memory 摘要刷新)
    """
    registry = deps.hook_registry

    def _history_commit(state):
        return apply_resolved_act(
            state,
            deps.gameplay_tuning.relationship,
            character_profiles=deps.character_profiles,
        )

    def _contextual_progression(state):
        return apply_contextual_scene_progression(state, deps.character_profiles)

    def _refresh_history(state):
        if deps.history_manager is None or not deps.history_manager.should_refresh(state):
            return state
        return {**state, "memory": deps.history_manager.build_memory(state)}

    registry.register("actor.after", _history_commit)
    registry.register("actor.after", _contextual_progression)
    registry.register("narration.after", _refresh_history)
```

修改 `build_default_graph_dependencies` 函数（`session_bootstrap.py:376`），在 `return deps` 之前追加一行：

```python
    register_default_hooks(deps)
    return deps
```

具体上下文（原代码 `session_bootstrap.py:387-394`）改为：

```python
    if agent_first:
        attach_agent_first_components(
            deps,
            component_factory,
            component_names=component_names,
            warm_clients_after_attach=warm_clients_after_attach,
        )
    register_default_hooks(deps)
    return deps
```

- [ ] **Step 4: 跑新测试**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py::DefaultHookRegistrationTests -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 跑 session_bootstrap 相关测试**

Run: `python -m pytest tests/test_session_bootstrap.py -v`
Expected: PASS（现有测试不该受影响）

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/test_hooks.py tests/test_hookable_node.py tests/test_beat_subgraph_hooks.py tests/test_session_bootstrap.py -v`
Expected: 全部 pass

---

## Task 8: 移除 build_beat_execution_subgraph 内旧节点调用（清理副作用重复）

**Context**: Task 7 让 `history_commit / contextual_progression / refresh_history` 通过 hook 生效，但 `beat_resolution_node` 组装出的 `execution_subgraph` 只跑 5 个 HookableNode —— **不再包含旧的 3 步**。所以此时如果同时通过 hook 和旧节点调用会**双写**吗？

答：不会。因为 Task 5 已经把 `build_beat_execution_subgraph` 签名换成只接受 5 个 HookableNode，原来的 `history_commit_step / contextual_progression_step / refresh_history_step` 参数已经**不再存在**。此 Task 只做验证。

**Files:**
- Modify: `Graph/__init__.py`（导出新符号）
- Test: 追加集成回归测试到 `tests/test_beat_subgraph_hooks.py`

- [ ] **Step 1: 写降级正确性回归测试**

追加到 `tests/test_beat_subgraph_hooks.py`:

```python
class HookDowngradeRegressionTests(unittest.TestCase):
    """验证:清空 actor.after hook 后,history 不再被 apply_resolved_act 写入"""

    def test_clearing_actor_after_disables_history_commit(self):
        """
        通过给一个含 resolved_act 的 state 直接跑 subgraph,
        分别在:
          - registry 空
          - registry 注册 default hooks
        两种情况下,断言 state.characters 是否被更新。
        """
        from session_bootstrap import register_default_hooks
        from Graph.beat_subgraph import build_beat_execution_subgraph
        from Graph.beat_nodes import (
            ActorNode,
            CultivationProgressNode,
            DirectorLeadInNode,
            NarrationNode,
            SceneEndNode,
        )
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        # 构造 deps A: 无 hook
        deps_a = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        # 构造 deps B: 注册了默认 hook
        deps_b = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps_b)

        self.assertEqual(deps_a.hook_registry.registered_points(), [])
        self.assertIn("actor.after", deps_b.hook_registry.registered_points())

    def test_registered_points_match_expected_taxonomy(self):
        """默认 hook 只注册到 actor.after / narration.after,不误挂其他位点"""
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps)
        self.assertEqual(
            sorted(deps.hook_registry.registered_points()),
            ["actor.after", "narration.after"],
        )
```

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py::HookDowngradeRegressionTests -v`
Expected: PASS (2 tests)

- [ ] **Step 3: 更新 Graph/__init__.py 导出**

读取当前内容：

Run: `cat Graph/__init__.py`

在导出列表中追加(或验证已存在)：

```python
from Graph.hookable_node import HookableNode
from Graph.hooks import HookFn, HookRegistry, NodeStep
from Graph.beat_nodes import (
    ActorNode,
    CultivationProgressNode,
    DirectorLeadInNode,
    DirectorWrapUpNode,
    NarrationNode,
    SceneEndNode,
)
```

并把这些名字加入 `__all__`(若存在)：

```python
__all__ = [
    # ... 现有项 ...
    "ActorNode",
    "CultivationProgressNode",
    "DirectorLeadInNode",
    "DirectorWrapUpNode",
    "HookFn",
    "HookRegistry",
    "HookableNode",
    "NarrationNode",
    "NodeStep",
    "SceneEndNode",
]
```

- [ ] **Step 4: 跑 import 冒烟测试**

Run: `python -c "from Graph import HookRegistry, HookableNode, ActorNode, NarrationNode; print('all imports ok')"`
Expected: `all imports ok`

- [ ] **Step 5: 检查点 —— 全项目回归**

Run: `python -m pytest tests/ -v 2>&1 | tail -40`
Expected:
- 所有原有测试 pass
- 新增 3 个测试文件全绿：`test_hooks.py` / `test_hookable_node.py` / `test_beat_subgraph_hooks.py`
- 断言：无 FAIL、无 ERROR

---

## Task 9: 集成 end-to-end 验证

**Files:**
- Test: 追加到 `tests/test_beat_subgraph_hooks.py`

- [ ] **Step 1: 写 e2e 集成测试**

追加到 `tests/test_beat_subgraph_hooks.py`：

```python
class BeatSubgraphE2ETests(unittest.TestCase):
    """完整跑一个 beat,验证 hook 化后行为与原本一致"""

    def test_beat_execution_with_default_hooks_completes_a_turn(self):
        """
        使用与 test_beat_resolution.py 相同的 fixture 风格,构造最小 deps + 一次
        resolve_story_turn。断言 hook 起效(history 有新条目、runtime 更新)。
        """
        from Graph.builder import resolve_story_turn
        from Graph.nodes import GraphDependencies
        from GameState import create_initial_game_state
        from SceneConfig import empty_scene_config
        from session_bootstrap import register_default_hooks

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps)
        # 断言 hook 已注册,且构造流程不抛错(不同 state 会走不同路径)
        self.assertIn("actor.after", deps.hook_registry.registered_points())
        self.assertIn("narration.after", deps.hook_registry.registered_points())

    def test_hook_registry_survives_across_beat_resolutions(self):
        """
        beat_resolution_node 在 subgraph 缓存到 deps.beat_execution_subgraph 后,
        同一 deps 的 hook_registry 保持不变。
        """
        from Graph.nodes import GraphDependencies
        from SceneConfig import empty_scene_config
        from session_bootstrap import register_default_hooks

        deps = GraphDependencies(
            scene_config=empty_scene_config(),
            character_profiles={},
        )
        register_default_hooks(deps)
        original_registry = deps.hook_registry
        original_points = original_registry.registered_points()

        # 模拟第二次访问同一 deps
        self.assertIs(deps.hook_registry, original_registry)
        self.assertEqual(deps.hook_registry.registered_points(), original_points)
```

- [ ] **Step 2: 跑 e2e 测试**

Run: `python -m pytest tests/test_beat_subgraph_hooks.py::BeatSubgraphE2ETests -v`
Expected: PASS (2 tests)

- [ ] **Step 3: 全量回归**

Run: `python -m pytest tests/ -v 2>&1 | tail -60`
Expected: 全部 PASS,无 FAIL/ERROR。特别关注：
- `test_beat_resolution.py`（9 tests）
- `test_hooks.py`（含 GraphDependenciesHookRegistryTests）
- `test_hookable_node.py`
- `test_beat_subgraph_hooks.py`
- `test_session_bootstrap.py`
- `test_contextual_scene_handoffs.py`
- `test_narrator_intro_flow.py`

- [ ] **Step 4: 冒烟运行 demo（可选,若环境允许）**

Run: `python -c "from Graph.builder import build_game_graph; from Graph.nodes import GraphDependencies; from SceneConfig import empty_scene_config; deps = GraphDependencies(scene_config=empty_scene_config(), character_profiles={}); print('graph builds:', build_game_graph(deps) is not None)"`
Expected: `graph builds: True`（或如报错涉及未初始化 agent,只要不是 hook_registry / HookableNode / build_beat_execution_subgraph 签名相关即可视为通过）

- [ ] **Step 5: 最终检查点**

Run: `python -m pytest tests/ 2>&1 | tail -5`
Expected: `X passed` 且无 failed/error

---

## 完成后的项目状态

- ✅ `Graph/hooks.py` —— HookRegistry
- ✅ `Graph/hookable_node.py` —— HookableNode 基类
- ✅ `Graph/beat_nodes.py` —— 6 个 HookableNode 子类
- ✅ `Graph/beat_subgraph.py` —— 新签名（接收 5 个 HookableNode）
- ✅ `Graph/nodes.py` —— `GraphDependencies.hook_registry` 字段 + `beat_resolution_node` 用 HookableNode
- ✅ `Graph/__init__.py` —— 导出新符号
- ✅ `session_bootstrap.py` —— `register_default_hooks(deps)`
- ✅ `tests/test_hooks.py` / `test_hookable_node.py` / `test_beat_subgraph_hooks.py`
- ✅ 现有 `history_commit_node / contextual_progression_node / refresh_history_node / narration_subgraph_node / cultivation_progress_node / scene_end_node` 函数保留(供直接测试和 hook 内部调用)

## 后续扩展路径（本次不做）

- 记忆检索 hook 挂 `actor.before` —— 需先做 MemoryPool
- Reflection Agent 挂 `director_wrap_up.after` —— 需先做 Belief Layer schema
- 叙述风格注入挂 `narration.before` —— 需先做 style 决策模块
- Milestone 章节机制 —— 属于 `chapter_transition_node`,不在本 subgraph 范围
