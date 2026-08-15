# 阶段5:提取 ConversationController — 设计方案

> 日期:2026-08-15
> 状态:待 review(仅设计,不含实现)
> 关联:对话引擎解耦重构的最后一个阶段(阶段 1-4 已完成);
> 承接总设计 `2026-08-13-dialogue-engine-decoupling-design.md` 第 54-56/65 行(④ ConversationController)。

---

## 1. 背景与目标

### 1.1 起点
对话引擎解耦重构分 5 个阶段,阶段 1-4 已完成(CharacterRepository 单一写入口 /
拆 nodes.py 破循环依赖 / 修炼领域插件化 / 每角色专属 DTO)。会话推进控制逻辑
(何时把控制权交给玩家、何时自动推进 NPC 回合、开场如何落到玩家)当前全部内联在
`web_session.py` 的 `WebGameSession` 类里,与 HTTP/锁/序列化/存档强耦合,无法被别的入口复用。

### 1.2 目标
把这套 **mode-agnostic 的会话推进控制**抽成独立的 `Graph/conversation_controller.py`,
`WebGameSession` 变薄(只管 Web 特有职责),并为**将来的"自动写小说"入口**(全自动、
无玩家参与、一路推进到场景结束)预留复用接口。本轮只接 Web,不改 CLI(`demo_run.py`)。

### 1.3 范围边界(已澄清)
- **只抽 Web 侧**:`demo_run.py` 的批量 for-round 循环本轮不动;controller 设计成
  无状态 + 停止条件注入,天然为将来自动入口预留复用能力,但本轮不写自动入口。
- **停止条件作参数注入**:controller 不关心"是谁在等",只关心"推进到满足停止条件
  就交回控制权"。Web 传"到玩家回合就停",自动模式传"永不停(靠 scene_finished 自然终止)"。
- **工具路由留在 Web 层**:`_maybe_handle_player_intent_plan_unlocked` /
  `_append_tool_message_unlocked` 深度依赖 Web-only 的 `player_command_tools`(绑存档 store/
  HTTP context),自动模式根本不走它。这两个方法**留在 `WebGameSession`**,但内部推进
  改调 `controller.advance(...)`(不再自己写循环)。

---

## 2. 现状盘点(已核对源码)

### 2.1 承载推进控制的三个私有方法(`web_session.py`,阶段5 提取源)
- `:598-640` `_prime_opening_player_turn(state) -> state`:开场把首回合交给玩家。
  **纯 state→state,零 I/O**。逻辑上假定一个 `player_actor`;若为空(自动模式)则
  `next_act=None`,自然退化。
- `:642-644` `_ensure_prepared_turn()`:若已初始化且未结束且 `next_act is None`,
  调 `prepare_chapter_turn` 补一个回合。读写 `self.state`。
- `:646-677` `_advance_until_player_turn(max_hops=24, on_event=None) -> str`:
  核心推进循环。while 里 `_ensure_prepared_turn` → 检查 `scene_finished`/`next_act` →
  `is_player_turn` 则返回 handoff reason(带 `npc_acted` 判定)→ 否则 `resolve_story_turn`
  推进。超 `max_hops` 抛 `RuntimeError`。读写 `self.state`、`self.deps`。

### 2.2 调用点
- `_initialize` 尾部(`:595-596`):`prime` + `advance`。
- `apply_player_action`(`:368-383`):`advance` → 工具路由 → push_action →
  `resolve_story_turn` → `advance`。锁 + 序列化包裹。
- `apply_player_action_streaming`(`:385-421`):同构,多 `on_event`/`_emit` 透传。
- `_maybe_handle_player_intent_plan_unlocked`(`:461-463`):非工具步骤内联
  `push_action + resolve_story_turn + _advance_until_player_turn`。

### 2.3 关键事实(降低风险)
- **无测试直接引用这三个私有方法**(已 grep 确认)。现有 `web_session` 相关测试
  (`test_session_bootstrap.py`、`test_contextual_scene_handoffs.py`、
  `test_persistence_save_load.py` 等 6 个文件)全部经 `WebGameSession` / `apply_player_action`
  **间接**覆盖推进逻辑。故收窄零测试阻力,行为等价即自动通过。
- CLI(`demo_run.py:238-244`)是完全不同的批量 `for round: plan_story_round` 语义,
  本轮不碰,不强行统一。

---

## 3. 设计

### 3.1 核心抽象:停止条件谓词
```python
# StopCondition:给定当前 state,判断是否该停下把控制权交出去。
StopCondition = Callable[[GameState], bool]

def stop_at_player_turn(state: GameState) -> bool:   # Web 用
    return is_player_turn(state)

def never_stop(state: GameState) -> bool:            # 自动写小说用(只靠 scene_finished 自然终止)
    return False
```

### 3.2 ConversationController(无状态薄类)
持有 `deps` 只读引用,**不持有 state**(state 每次传入、返回新的),使 Web 与自动入口
各自管自己的 state 生命周期。

```python
class ConversationController:
    def __init__(self, deps: GraphDependencies) -> None:
        self._deps = deps

    def prime_opening_turn(self, state: GameState) -> GameState:
        # 原 _prime_opening_player_turn 逐行搬入,签名改为纯 state->state(去掉 self.state)。
        ...

    def advance(
        self,
        state: GameState,
        *,
        stop_when: StopCondition,
        max_hops: int = 24,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[GameState, str]:
        # 原 _advance_until_player_turn 循环体,但:
        # - 不读 self.state,改用传入的 state 局部变量,循环末尾更新它,最后返回。
        # - "是否停下" 从写死的 is_player_turn(...) 改为 stop_when(state)。
        # - _ensure_prepared_turn 内联为循环里的私有步骤(用局部 state)。
        # - 返回 (new_state, handoff_reason)。
        ...
```

唯一一份推进循环:Web 传 `stop_at_player_turn`,自动入口传 `never_stop`。

### 3.3 WebGameSession 收窄
保留 Web 特有职责:HTTP 入口、`self._lock`、`serialize_state`、存档 store、
**工具路由**(两个方法留原地)。新增持有 controller:
```python
# __init__ / _reload_dependencies 里(deps 就绪后):
self._controller = ConversationController(self.deps)
```

`apply_player_action` 收窄(streaming 版同构,多 `_emit` 透传给两处 advance 的 on_event):
```python
def apply_player_action(self, raw_input: str) -> dict[str, Any]:
    with self._lock:
        if not self.story_initialized:
            raise RuntimeError("请先初始化场景，再提交玩家动作。")
        if self.state["runtime"].get("scene_finished", False):
            raise RuntimeError("当前场景已经结束，请重置后继续。")
        self.state, _ = self._controller.advance(self.state, stop_when=stop_at_player_turn)
        if not is_player_turn(self.state):
            raise RuntimeError("当前还没有轮到玩家行动。")
        tool_response = self._maybe_handle_player_intent_plan_unlocked(raw_input)
        if tool_response is not None:
            return tool_response
        self._player_interface.push_action(raw_input)
        self.state = resolve_story_turn(self.state, self.deps)
        self.state, self.last_handoff_reason = self._controller.advance(
            self.state, stop_when=stop_at_player_turn)
        return self.serialize_state()
```

`_initialize` 尾部:
```python
    self.state = self._controller.prime_opening_turn(self.state)
    self.state, self.last_handoff_reason = self._controller.advance(
        self.state, stop_when=stop_at_player_turn)
```

`_maybe_handle_player_intent_plan_unlocked` 内非工具步骤(`:461-463`)改为:
```python
        self._player_interface.push_action(action_text)
        self.state = resolve_story_turn(self.state, self.deps)
        self.state, self.last_handoff_reason = self._controller.advance(
            self.state, stop_when=stop_at_player_turn)
```
(工具路由整体仍留在 WebGameSession,只是推进委托给 controller。)

### 3.4 将来的自动写小说入口(本轮不写,仅验证接口够用)
```python
controller = ConversationController(deps)
state = controller.prime_opening_turn(state)   # 无 player_actor → next_act=None
state, _ = controller.advance(state, stop_when=never_stop, max_hops=<足够大>)
```

### 3.5 数据流
```
[Web] apply_player_action
  → controller.advance(state, stop_when=stop_at_player_turn)   # 推进到玩家回合
  → 工具路由(留 Web)/ push_action → resolve_story_turn
  → controller.advance(state, stop_when=stop_at_player_turn)   # 推进到下个玩家回合

[自动/将来] controller.advance(state, stop_when=never_stop)    # 一路推进到 scene_finished
```

---

## 4. 错误处理(沿用现有语义,不新增)
- `advance` 超 `max_hops`(默认 24)仍未到停止点 → `raise RuntimeError("自动推进超过安全跳数，仍未到达稳定交接点。")`。原逻辑照搬。
- **`never_stop` 模式下 `max_hops` 成为硬上限**:若场景 NPC 回合数可能超 24,自动入口须传更大 `max_hops`。此点写入 controller docstring;本轮不为自动入口调参(它还没写)。
- `scene_finished` / `next_act is None` 是**正常终止**,返回 handoff reason 字符串,不抛错——这是 `never_stop` 模式的自然出口。
- `story_initialized` 校验、`scene_finished` 预检查留在 `apply_player_action`(Web 层入口校验,不属推进逻辑)。

---

## 5. 测试策略
新增 `tests/test_conversation_controller.py`(fake deps/agents + 轻量 state,不碰 LLM):
1. **prime_opening_turn**:含 player_actor 的 state → 断言 `next_act["actor"] == player_actor`;无 player_actor(自动模式)→ 断言 `next_act is None`。
2. **advance + stop_at_player_turn**:构造"NPC 回合 → 玩家回合"序列(fake `resolve_story_turn` 推进),断言停在玩家回合、返回正确 handoff reason。
3. **advance + never_stop**:构造一串 NPC 回合直到 `scene_finished=True`,断言一路推进到底、不在中途玩家回合停(验证自动模式接口真能跑通到场景结束)。
4. **advance max_hops**:构造永不终止的 state,断言超跳数抛 `RuntimeError`。
5. **on_event 透传**:断言 streaming 回调被 `advance` 正确转交给 `resolve_story_turn`。

**回归**:守住现有 172 全绿。`web_session` 相关测试收窄后行为等价,应无改动即通过(已确认无测试引用被删私有方法)。

---

## 6. 文件结构
- **新建** `Graph/conversation_controller.py`:`StopCondition` 类型别名 + `stop_at_player_turn` / `never_stop` 两个谓词 + `ConversationController` 类。
- **修改** `web_session.py`:删 `_advance_until_player_turn` / `_prime_opening_player_turn` / `_ensure_prepared_turn` 三个方法(约 80 行);构造 `self._controller`;`_initialize` / `apply_player_action` / `apply_player_action_streaming` / `_maybe_handle_player_intent_plan_unlocked` 改为委托调用。
- **新建** `tests/test_conversation_controller.py`。

---

## 7. 风险与权衡
- **无状态 controller**:state 传入传出而非持有,是为让自动入口与 Web 各管各的 state 生命周期;代价是调用方每次要接住返回的新 state(Web 现有代码本就在重赋 `self.state`,零额外负担)。
- **工具路由留 Web**:避免把 Web-only 的 `player_command_tools` 依赖拖进 mode-agnostic 的 controller;代价是工具路由方法仍在 `web_session.py`,但其推进部分已委托 controller,不再重复循环逻辑。
- **max_hops 硬上限**:`never_stop` 靠 `scene_finished` 终止,但 `max_hops` 仍是安全阀。本轮不为尚未存在的自动入口调参,仅在 docstring 标注。
- **行为等价**:Web 侧停止点仍是 `stop_at_player_turn`,循环体逐行搬迁,`npc_acted` 判定/handoff reason 文案不变,故现有 172 测试应保持全绿。

---

## 8. 不在本轮
- 自动写小说入口的**实现**(本轮只预留 `advance(stop_when=never_stop)` 接口并测试其可跑通)。
- CLI(`demo_run.py`)复用 controller(其批量 for-round 语义与交接语义不同,需单独一轮)。
- 工具路由 mode-agnostic 化(需先抽象 `player_command_tools` 的存档/HTTP 依赖)。
