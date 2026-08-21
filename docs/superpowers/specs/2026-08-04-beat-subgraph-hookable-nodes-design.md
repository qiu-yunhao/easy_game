# beat_execution_subgraph 节点 Hook 化改造设计

> **日期**：2026-08-04
> **状态**：设计已通过用户确认，待生成实施计划
> **背景**：当前 `beat_execution_subgraph` 是 8 步硬编码序列，其中 4 步（`history_commit / contextual_progression / narration / refresh_history`）实质是"无控制流决策"的副作用节点。为便于后续扩展（记忆检索、Reflection Agent、叙述风格注入、Milestone 章节等），将主节点结构统一化：**每个主节点自带对称的 before/after hook 位点，副作用降级为默认注册的 hook**。

---

## 一、动机

### 现状问题

1. `beat_execution_subgraph`（`Graph/beat_subgraph.py`）用位置参数硬编码 8 个 step，扩展点全靠改签名
2. 4 个节点（`history_commit / contextual_progression / narration / refresh_history`）没有控制流决策，本质是"actor / narration 的后置副作用"，硬做成节点导致：
   - 无法通过配置切换是否启用
   - 未来"记忆检索"需要在 actor 之前预处理，主流程没有挂位
3. 节点之间的先后依赖靠数组顺序保证，不显式

### 目标

- **对称化**：每个主节点带 `before` / `after` 两个 hook 位点
- **注册式扩展**：新增行为只需 `hook_registry.register(...)`，主流程零改动
- **规范化**：所有主节点继承同一抽象基类，行为一致、易测试
- **零副作用降级**：把 4 个无决策节点降级为默认注册的 hook

---

## 二、Hook 位点契约

### 定义"没有副作用"（严格版）

**允许改 state，但不改变"下一个节点是否要跑"** —— 即 hook 只做"写入类"或"读取后处理类"的工作，不做分支决策。

### 五个主节点 × 对称 before/after = 10 个位点

| 主节点 | `<name>.before` 位点 | `<name>.after` 位点 |
|---|---|---|
| `director_lead_in` | `director_lead_in.before` | `director_lead_in.after` |
| `actor` | `actor.before` | `actor.after` |
| `narration` | `narration.before` | `narration.after` |
| `cultivation_progress` | `cultivation_progress.before` | `cultivation_progress.after` |
| `scene_end` | `scene_end.before` | `scene_end.after` |

Beat loop 外部（`run_beat_loop.wrap_step`）另有一个：

| 主节点 | before | after |
|---|---|---|
| `director_wrap_up` | `director_wrap_up.before` | `director_wrap_up.after` |

### 保留为节点的判定标准

**含控制流决策的节点保留为显式节点**，不降级为 hook：

- `narration_subgraph_node` —— 内部 `select_narration_batch` 决定"是否叙述、批多大、是否强制清空"，是名词性锚点
- `cultivation_progress_node` —— 写 `plot_flags` 影响后续 `chapter_transition`，且 mutate `deps.character_profiles`
- `scene_end_node` —— 改 `state.runtime.scene_finished`，直接决定 `beat_loop` 是否 break
- `director_lead_in_node` / `director_wrap_up_node` —— 内部有条件判断（只在特定 actor 切换时追加）

---

## 三、四个默认 hook 的落位

| 原节点 | 新挂载点 | 说明 |
|---|---|---|
| `history_commit` | `actor.after` | actor 产出 `resolved_act` 后立即写入 history/关系/记忆 |
| `contextual_progression` | `actor.after` | 紧随 history_commit，推进场景 handoff（注册顺序在其后） |
| `refresh_history` | `narration.after` | 叙述完成后刷 history 摘要（保持当前"叙述读上一 beat 快照"语义） |
| ~~`narration`~~ | 保留为节点 | `narration_subgraph_node` 就是位点的锚，不降级 |

**注册顺序敏感项**：`actor.after` 位点上 `history_commit` 必须在 `contextual_progression` 之前注册（因为 contextual_progression 读的是已写入的 state）。

---

## 四、组件设计

### 4.1 `Graph/hooks.py` —— HookRegistry

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
        """清空某位点(测试用)或全部。"""
        if hook_point is None:
            self._hooks.clear()
        else:
            self._hooks.pop(hook_point, None)

    def emit(self, hook_point: str, state: GameState) -> GameState:
        """按注册顺序跑所有 hook。位点无 hook 时零开销。"""
        hooks = self._hooks.get(hook_point)
        if not hooks:
            return state
        for hook in hooks:
            state = hook(state)
        return state

    def registered_points(self) -> list[str]:
        return sorted(self._hooks.keys())
```

**关键设计**：
- Hook 签名与 `NodeStep` 完全一致（`state → state`），可互换
- `emit` 提前返回，空位点零开销
- `clear` 方法支持测试隔离

### 4.2 `Graph/hookable_node.py` —— 抽象基类

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from GameState import GameState
from Graph.hooks import HookRegistry, NodeStep


class HookableNode(ABC):
    """
    所有主节点的抽象基类。

    每个子类:
      1. 声明 name(用作 hook 位点前缀)
      2. 实现 run(state) —— 节点核心逻辑

    基类自动组装 "before → run → after" 三段式为一个 NodeStep。
    """

    def __init__(self, hook_registry: HookRegistry) -> None:
        self._registry = hook_registry

    @property
    @abstractmethod
    def name(self) -> str:
        """节点名。同时是 hook 位点前缀。"""

    @property
    def hook_point_before(self) -> str:
        return f"{self.name}.before"

    @property
    def hook_point_after(self) -> str:
        return f"{self.name}.after"

    @abstractmethod
    def run(self, state: GameState) -> GameState:
        """节点核心逻辑。子类实现,不负责触发 hook。"""

    def as_step(self) -> NodeStep:
        """组装成 NodeStep: before hook → run → after hook。"""
        def _step(state: GameState) -> GameState:
            state = self._registry.emit(self.hook_point_before, state)
            state = self.run(state)
            state = self._registry.emit(self.hook_point_after, state)
            return state
        return _step
```

**关键设计**：
- `name` 属性同时充当 hook 位点前缀 —— 单一真理源，杜绝位点名不一致
- `as_step()` 返回闭包，兼容现有 `compile_graph_with_nodes` 契约
- 子类只写 `run`，不必知道 hook 存在

### 4.3 `Graph/beat_nodes.py` —— 6 个 HookableNode 子类

```python
from Graph.hookable_node import HookableNode
from Graph.hooks import HookRegistry
# 复用现有函数(不删)
from Graph.nodes import (
    director_lead_in_node, actor_node,
    cultivation_progress_node, scene_end_node,
    director_wrap_up_node,
)
from Graph.narration_nodes import narration_subgraph_node


class DirectorLeadInNode(HookableNode):
    name = "director_lead_in"
    def __init__(self, deps, hook_registry: HookRegistry):
        super().__init__(hook_registry)
        self._deps = deps
    def run(self, state):
        return director_lead_in_node(state, self._deps)


class ActorNode(HookableNode):
    name = "actor"
    def __init__(self, deps, hook_registry: HookRegistry):
        super().__init__(hook_registry)
        self._deps = deps
    def run(self, state):
        return actor_node(state, self._deps)


class NarrationNode(HookableNode):
    name = "narration"
    def __init__(self, deps, hook_registry: HookRegistry, *, force_flush: bool = False):
        super().__init__(hook_registry)
        self._deps = deps
        self._force_flush = force_flush
    def run(self, state):
        return narration_subgraph_node(state, self._deps, force_flush=self._force_flush)


class CultivationProgressNode(HookableNode):
    name = "cultivation_progress"
    def __init__(self, deps, hook_registry: HookRegistry):
        super().__init__(hook_registry)
        self._deps = deps
    def run(self, state):
        return cultivation_progress_node(state, self._deps)


class SceneEndNode(HookableNode):
    name = "scene_end"
    def __init__(self, deps, hook_registry: HookRegistry):
        super().__init__(hook_registry)
        self._deps = deps
    def run(self, state):
        return scene_end_node(state, self._deps)


class DirectorWrapUpNode(HookableNode):
    name = "director_wrap_up"
    def __init__(self, deps, hook_registry: HookRegistry):
        super().__init__(hook_registry)
        self._deps = deps
    def run(self, state):
        return director_wrap_up_node(state, self._deps)
```

### 4.4 `Graph/beat_subgraph.py` —— 重构后

```python
from Graph.hookable_node import HookableNode

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
            (director_lead_in.name,       director_lead_in.as_step()),
            (actor.name,                  actor.as_step()),
            (narration.name,              narration.as_step()),
            (cultivation_progress.name,   cultivation_progress.as_step()),
            (scene_end.name,              scene_end.as_step()),
        ],
        fallback_to_runner=True,
    )
```

主流程从"8 个 step" → **"5 个 HookableNode + 内嵌 10 个 emit 位点"**。

### 4.5 `GraphDependencies` 增补

```python
@dataclass(slots=True)
class GraphDependencies:
    ...  # 现有字段
    hook_registry: HookRegistry = field(default_factory=HookRegistry)
```

### 4.6 `session_bootstrap.py` —— 默认 hook 注册

```python
def build_default_hook_registry(deps: GraphDependencies) -> HookRegistry:
    reg = HookRegistry()

    # actor.after: history_commit(注册顺序 1) → contextual_progression(注册顺序 2)
    reg.register("actor.after", lambda s: apply_resolved_act(
        s, deps.gameplay_tuning.relationship, character_profiles=deps.character_profiles
    ))
    reg.register("actor.after", lambda s: apply_contextual_scene_progression(
        s, deps.character_profiles
    ))

    # narration.after: refresh_history
    def _refresh_history_hook(s: GameState) -> GameState:
        if deps.history_manager is None or not deps.history_manager.should_refresh(s):
            return s
        return {**s, "memory": deps.history_manager.build_memory(s)}
    reg.register("narration.after", _refresh_history_hook)

    return reg
```

Composition root(`session_bootstrap.py` / `demo_run.py` / `web_session.py`)在构造 `GraphDependencies` 后,调用 `deps.hook_registry = build_default_hook_registry(deps)`——用返回的 registry 替换 dataclass 默认构造的空 registry。

**替代方案**(如需保留 `GraphDependencies` 构造后就已就绪):把 `build_default_hook_registry(deps)` 改为 `register_default_hooks(deps.hook_registry, deps)`,直接在默认空 registry 上追加注册,不替换实例。实施阶段任选其一,不影响外部契约。

---

## 五、数据流

### Beat 执行一步的完整链路

```
── emit("director_lead_in.before") ──          [空位]
director_lead_in.run()                          决定是否追加导演开场白
── emit("director_lead_in.after") ──           [空位]

── emit("actor.before") ──                     [未来: 记忆检索]
actor.run()                                     产出 resolved_act
── emit("actor.after") ──                      history_commit → contextual_progression
                                                (顺序敏感: contextual_progression 读已写入的 state)

── emit("narration.before") ──                 [未来: 叙述风格注入]
narration.run()                                 batch → 生成 → polish → 追加
── emit("narration.after") ──                  refresh_history(条件性刷新 memory 摘要)

── emit("cultivation_progress.before") ──      [空位]
cultivation_progress.run()                      检测修炼信号/突破,写 plot_flags
── emit("cultivation_progress.after") ──       [空位]

── emit("scene_end.before") ──                 [空位]
scene_end.run()                                 evaluate → 改 scene_finished
── emit("scene_end.after") ──                  [空位]
```

Beat loop 外(`run_beat_loop.wrap_step`)：

```
── emit("director_wrap_up.before") ──          [空位]
director_wrap_up.run()                          决定是否追加导演收场白
── emit("director_wrap_up.after") ──           [未来: Reflection Agent 触发]
```

### Hook 位点的分层用途

| 层次 | 位点示例 | 典型用途 |
|---|---|---|
| **写入类**（actor.after / director_lead_in.after / scene_end.after） | actor.after | 状态落地(记忆/关系/handoff) |
| **读取预处理类**（actor.before / narration.before） | actor.before | 预热上下文(检索记忆/命中 hook) |
| **收尾类**（narration.after / director_wrap_up.after） | narration.after | 呈现后整理(摘要刷新/衰减/反思) |

---

## 六、扩展路径示例

### 场景 1：加入 tag/向量记忆检索

```python
# 在 composition root 追加一行
reg.register("actor.before", lambda s: retrieve_memories_hook(s, memory_pool))
```

主流程不动，`actor.before` 位点空 → 有，`actor.run()` 拼 prompt 时读到 `state.runtime.hot_memories`。

### 场景 2：加入 Reflection Agent

```python
# 每 N 个 beat 触发一次复盘
reg.register("director_wrap_up.after", lambda s: reflection_trigger_hook(s, threshold=10))
```

### 场景 3：Milestone 章节机制

Milestone 属于 `chapter_transition_node` 前置决策，不在 beat_execution_subgraph 范围内 —— 若要接入,应扩展 `TRANSITION_NODES` 里的节点也接入 HookableNode 契约(未来的独立改造)。

---

## 七、非目标（本次不做）

1. **不动 `narration_subgraph_node` 内部**（batch 逻辑保留）
2. **不动 `cultivation_progress_node` 内部**（修为决策保留）
3. **不动 `story_authoring_subgraph` / `chapter_preparation_subgraph` / `transition_subgraph`** —— 只改 `beat_execution_subgraph` + `wrap_step`
4. **不引入装饰器式全局注册** —— 保持显式 composition root
5. **不删除现有的函数式节点实现**（`history_commit_node` 等）—— 保留供测试直接调用，只是不再作为默认 step

---

## 八、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 每 beat 多 10 次 dict lookup | 微秒级,LLM 延迟主导下不可察觉 | `emit` 空位点提前 return |
| Hook 注册顺序敏感 | 例: `actor.after` 上 commit 必须先于 progression | 顺序在 composition root 显式代码,可读;写测试验证顺序 |
| 现有测试直接调 `history_commit_node(state, deps)` | 测试不受影响(函数保留) | 建议追加"通过 registry 注册后 emit 一次"的集成测试 |
| `beat_execution_subgraph` 签名从 kwargs step → HookableNode | 调用点全部要改 | 一次性改完:`builder.py` + 相关测试(<10 处) |
| 现存代码在 `GraphDependencies` 上无 `hook_registry` 字段(改造前) | 改造中新增字段会破坏其它构造点 | 新字段用 `field(default_factory=HookRegistry)`,原有构造代码不传该参数也能工作 |

---

## 九、测试策略

### 单元测试

1. **`test_hook_registry.py`**
   - `register` 追加到同一位点
   - `emit` 按注册顺序调用
   - 空位点零开销(mock hook 不被调用)
   - `clear` 隔离测试

2. **`test_hookable_node.py`**
   - `as_step()` 组装出的函数按 before → run → after 顺序调用
   - `run` 抛异常时 after hook 不执行(异常传播)
   - 子类 `name` 决定位点前缀

### 集成测试

1. **`test_beat_subgraph_hooks.py`**
   - 构造 default registry,跑一 beat,断言 `history_commit` / `contextual_progression` / `refresh_history` 都跑了
   - 清空 `actor.after`,跑一 beat,断言 history 未变化(证明降级正确)
   - 在 `actor.before` 注册一个 mock,验证被调用且拿到 pre-actor state

2. **`test_regression_beat_flow.py`**
   - 用现有 fixture 跑完整 beat,比对改造前后 state 逐字段一致

---

## 十、实施顺序建议

1. 新建 `Graph/hooks.py`(HookRegistry + 单测)
2. 新建 `Graph/hookable_node.py`(抽象基类 + 单测)
3. 新建 `Graph/beat_nodes.py`(6 个子类)
4. 在 `GraphDependencies` 加 `hook_registry` 字段
5. 重构 `build_beat_execution_subgraph` 签名(接收 HookableNode)
6. 改 `beat_resolution_node` 的构造代码,把 lambda 替成 HookableNode 实例
7. 在 `session_bootstrap.py` 加 `build_default_hook_registry`,composition root 调用
8. 同步改 `demo_run.py` / `web_session.py`(如有独立组装路径)
9. 跑回归测试,补集成测试
10. 删除或标记 deprecated 的旧 step 参数(可保留一段过渡期)

---

## 十一、Glossary

- **HookableNode**：主节点抽象基类,自带 before/after 两个位点
- **HookRegistry**：按位点名存 hook 列表的注册中心
- **NodeStep**：`Callable[[GameState], GameState]`,主流程一步的最小契约
- **Hook 位点(hook point)**：形如 `<node_name>.before` / `<node_name>.after` 的字符串键
- **降级 hook**：将原本的独立节点(无控制流决策)改为默认注册在某位点的 hook
