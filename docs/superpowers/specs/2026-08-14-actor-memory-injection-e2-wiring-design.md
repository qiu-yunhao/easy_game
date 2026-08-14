# 记忆工厂读侧接入 Actor(E2)— 设计方案

> 日期:2026-08-14
> 状态:待 review(仅设计,不含实现)
> 关联:阶段4 记忆注入工厂的接入落地(决策 E 的读侧一步);承接
> `2026-08-14-actor-memory-injection-design.md`

---

## 1. 背景与目标

### 1.1 起点
阶段4 已建好只读记忆工厂 `Memory/DefaultActorMemoryProvider`,它的
`build(actor_id, state) -> ActorMemoryContext` 能从 GameState 抽出某角色的三层记忆
(短期在场过滤 / 长期复用 / 检索占位),组装成 frozen DTO。但**尚未接入任何 agent 路径**
(决策 E 当时推迟)。当前 Actor 回合仍直接从 state 翻字段,短期对话读的是
`state["history"][-8:]`——**无在场过滤**,角色能"记得"自己不在场时发生的对话。

### 1.2 目标
把 Actor 回合的**短期对话**与**人设**改由工厂产出的 `ActorMemoryContext` 注入,
兑现设计初衷"不在场则无短期记忆"。整链路呈:导演规划场景 → 演员自由发挥,
而演员的记忆由工厂统一供给。

### 1.3 范围边界(本轮只做读侧)
- **接**:短期对话(`recent_history`)改用 `ctx.short_term`(在场过滤);人设改用 `ctx.persona`。
- **不接**:长期三层 / player_memory / 角色自身短期记忆列表(`recent_short_term_memory`)
  的**读取逻辑保持原样**;记忆的**写入**(`ActorRuntime._apply_memory_updates`)本轮不动,
  留待"写侧那轮"把写入与压缩收进工厂做成读写门面。
- **形态**:方案 B 强制注入,语义单一,不留双源分支(本任务本身是重构)。

---

## 2. 现状盘点(已核对源码)

### 2.1 记忆读取现状
`Actor/ActorFormatter.py` 的 `_build_actor_payload`(24-73 行,三个 agent 共用)是唯一读点:
- `:30` `actor_profile = character_profiles.get(actor_id, {})` —— profile 来自参数,兜底空 dict。
- `:36-38` `ensure_character_memory_state(actor_runtime["memory"], actor_profile=actor_profile)`
  —— 归一 + **长期为空时从 profile 播种**(播种依赖 actor_profile)。
- `:52/54-57` profile 派生字段(整块 profile、agent_type、l2/l1_profile、layer_assignment)。
- `:60-64/68/72` 长期三层 / player_memory / 角色短期记忆列表(全来自 actor_memory)。
- `:71` `recent_history = state["history"][-8:]` —— **无在场过滤,本轮唯一要切换语义的行**。

### 2.2 关键事实
- **`character_profiles` 参数只服务当前 actor**:整条链路(三个 agent perform_turn +
  formatter + L2 的 supporting_scene_intent_policy.decide)都只取 `character_profiles.get(actor_id)`,
  从不取别的角色 profile。故 `ctx.persona`(单供当前 actor 一个 persona)可完全替代该参数。
- **两个短期字段是两回事**:`recent_history`(:71,全局原始对话)对应 `ctx.short_term`;
  `recent_short_term_memory`(:72,角色自身短期记忆列表,写侧产物)属长期/写侧范畴,本轮不动。
- **persona 等价替换**:`ctx.persona` 就是工厂从 `character_profiles` 取的同一个 `CharacterProfile`,
  字段完全一致。故 :36 的播种、:60-72 的长期读取在 profile 来源换成 ctx 后行为等价。
  前提是工厂兜底为合法空壳(见 3.1)。

### 2.3 perform_turn 与调用点
- 三个 agent(`Actor/ActorAgent.py:49`、`L1ActorAgent.py:35`、`L2ActorAgent.py:44`)
  签名一致:`perform_turn(self, state, character_profiles) -> ResolvedAct`。
- 调用点两处:`Graph/actor_paths.py:73`(NPC 串行 `resolve_npc_turn_state`)、
  `Graph/beat_group.py:76`(NPC 并行组)。玩家回合走 `parse_action`,不涉及。
- `GraphDependencies`(`Graph/dependencies.py:30`)已有 `character_profiles`,**无** `actor_memory_provider`;
  唯一生产构造点 `session_bootstrap.py:378` `build_runtime_dependencies`。

---

## 3. 设计

### 3.1 工厂兜底修正
`Memory/default_provider.py:28`:persona 未命中 `{}`(靠 type:ignore)→ `ensure_character_profile(None)`。
产出带全部必填键的合法 `CharacterProfile` 空壳,保住下游 `.get("memory_profile")` /
播种 / agent_contract 字段访问。移除 `# type: ignore[assignment]`。

### 3.2 formatter 收窄
`_build_actor_payload` 签名:删 `character_profiles: dict[str, CharacterProfile]`,
加必填 `memory_ctx: ActorMemoryContext`。函数体:
- `actor_id` 改用 `memory_ctx.actor_id`(不再从 `next_act` 取,保证与工厂 build 的 actor 一致)。
- 所有 `actor_profile` 引用(:30/32-38/52/54-57)统一指向 `memory_ctx.persona`。
- `:71` `recent_history` 改为 `list(memory_ctx.short_term)`(**唯一语义切换**)。
- `:36` 的 `ensure_character_memory_state`、`:60-72` 长期/player/短期记忆列表:**逻辑不动**,
  仅 profile 来源变 ctx(等价)。`actor_runtime` 仍从 `state["characters"]` 取。

### 3.3 三个 agent 收窄
`perform_turn` 签名 `(state, character_profiles)` → `(state, memory_ctx: ActorMemoryContext)`,
透传给 `_build_actor_payload`。`L2ActorAgent` 的
`supporting_scene_intent_policy.decide(actor_profile=...)` 改用 `memory_ctx.persona`。

### 3.4 调用方接线
- `Graph/actor_paths.py`(NPC 串行):
  `ctx = deps.actor_memory_provider.build(actor_id, state)` → `perform_turn(state, memory_ctx=ctx)`。
- `Graph/beat_group.py`(并行组):对每个 actor 先 `build(actor_id, actor_state)` 再 `perform_turn`。

### 3.5 依赖注入
- `Graph/dependencies.py`:`GraphDependencies` 加
  `actor_memory_provider: "ActorMemoryProvider | None" = None`(TYPE_CHECKING 引类型,避免环)。
- `session_bootstrap.py:378` `build_runtime_dependencies`:默认构建
  `DefaultActorMemoryProvider(character_profiles=<repo>, recent_rounds=3, granularity="on_stage")`。
- 调用方从 `deps.actor_memory_provider` 取(为 None 时视为配置错误,不做静默降级——本轮强制注入)。

### 3.6 数据流
```
actor_node / beat_group
  → ctx = deps.actor_memory_provider.build(actor_id, state)   # persona 合法兜底 + 在场过滤短期
  → agent.perform_turn(state, memory_ctx=ctx)
  → _build_actor_payload(state, memory_ctx=ctx)
      recent_history = ctx.short_term        # 在场过滤(新语义)
      actor_profile  = ctx.persona           # 等价替换,播种/字段照旧
      长期三层 / player_memory / recent_short_term_memory  # 本轮不动
```

---

## 4. 测试策略
- **formatter 单测**:传入构造好的 `ActorMemoryContext`,断言 payload 的 `recent_history` ==
  `ctx.short_term`、`actor_profile` == `ctx.persona`;长期字段仍按 actor_memory 读取。
- **三个 agent perform_turn 单测**:签名改造后,现有测试改为造 ctx 传入,断言仍产出合法 ResolvedAct。
- **工厂兜底单测**:未命中角色时 `ctx.persona` 是 `ensure_character_profile(None)` 的合法空壳
  (含必填键),而非空 dict。
- **集成测试(新增)**:构造"角色下场期间有对话"的 history,断言该角色回合的
  `recent_history` 不含其不在场期间的条目(在场过滤真正生效)。
- **回归**:守住现有 169 全绿。

---

## 5. 风险与权衡
- **强制注入的代价**:formatter + 三个 agent 的现有测试调用点都要改造为造 ctx 传入。
  这是方案 B 相对"可选参数过渡"多出的工作量,但因本任务是重构,这些测试本应随签名演进,
  换来无双源分支的单一语义。
- **persona 等价性**:长期播种依赖 profile,`ctx.persona` 与原参数 profile 同源同字段,
  行为等价;唯一前提是兜底改为合法空壳(3.1)。
- **beat_group 并行组**:每个 actor 各自 build(基于其 actor_state),与串行路径一致。
- **provider 为 None**:本轮强制注入,不做静默降级;bootstrap 默认构建保证生产链路恒有 provider,
  测试路径显式传入。

---

## 6. 不在本轮(留待写侧那轮)
- 记忆**写入**(`ActorRuntime._apply_memory_updates`:短期/长期/pinned/player 写入与就地压缩)
  搬迁进工厂,做成读写门面。
- 长期三层 / `recent_short_term_memory`(:72)的读取改走 ctx(需先把播种 `ensure_character_memory_state`
  纳入工厂 build)。
- 检索层(第三层)填实(决策 C:query 用什么)。
- 推广到 Director / Narrator / Scheduler(E3)。
