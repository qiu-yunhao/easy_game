# 对话引擎解耦设计

**日期**: 2026-08-13
**范围**: 对话引擎(actor → narration 产出玩家可见文字的完整链路,含 beat loop / 调度 / 导演 / 场景结束),**不含**开局与章节生成(story planning / chapter expansion)。

## 背景与动机

`easy_game`(Stagebound)是编剧-导演-演员-旁白多智能体互动叙事引擎。当前对话流的核心耦合痛点:

1. **God Object**:`GameState` 被 61+ 文件引用,每个 agent 收到整个 `state` + 整个 `character_profiles`,没有窄接口。
2. **双数据源**:`character_profiles` 游离在 `GameState` 之外、挂在 `deps` 上,被多处就地 mutate(如 `cultivation_progress_node` 的 `deps.character_profiles[player_actor] = {...}`,nodes.py:295)。
3. **枢纽文件**:`Graph/nodes.py`(565 行)混了依赖定义、剧情编排、修炼领域逻辑(硬编码中文文案 104-176)、对话流四类职责;存在 `nodes ↔ beat_nodes` 循环依赖(靠 nodes.py:401 懒加载绕开)。
4. **会话控制逻辑错位**:`_advance_until_player_turn`、`_prime_opening_player_turn`、工具意图路由塞在 `web_session.py`(744 行),CLI(`demo_run.py`)得重复实现。

## 目标

- 引入 `CharacterRepository` 作为角色档案的单一写入口。
- 用每角色专属只读 DTO 替代到处传整个 `GameState`。
- 拆分 `nodes.py`,破除循环依赖。
- 把修炼领域逻辑抽成独立插件,对话引擎不再感知修炼细节。
- 提取 mode-agnostic `ConversationController`,Web/CLI 共用。

## 核心架构变化

### ① CharacterRepository — 单一写入口

用 `CharacterRepository` 类包住裸 dict:
- **读**:`get(actor_id) -> CharacterProfile`(只读拷贝)、`all()`。
- **写**:仅具名方法 `update_realm(actor_id, realm)`、`apply_deltas(...)` 等,禁止外部 `[]=` 就地改。
- **兼容**:`deps.character_profiles` 保留为代理属性(委托到 repo),让 61 个引用点分阶段迁移,不必一次全改。

### ② 每角色专属只读 DTO — 去 God Object

对话路径四个入口改为收窄接口(均为 frozen dataclass,由 `Graph/context_builders.py` 从 GameState 构造):

| 入口 | 现收 | 改收 |
|------|------|------|
| `ActorAgent.perform_turn` | state + profiles | `TurnContext`(当前 actor 视角:自己 profile、on_stage 对手、相关 history 切片、scene) |
| `SemanticParserAgent.parse_action` | state + profiles | `PlayerTurnContext` |
| `NarratorAgent.narrate_action_batch` | state | `NarrationBatch`(待旁白 acts + 风格 preset) |
| `SchedulerPolicy.decide_next_turn` | state | `SchedulerView`(runtime queue + scene) |

Agent 内部不再触碰 GameState 结构。

### ③ 拆 nodes.py + 破循环依赖

- `Graph/dependencies.py` — `GraphDependencies` 定义(从 nodes.py 移出)。
- `Graph/dialogue_nodes.py` — `actor_node`、`beat_resolution_node`、`_resolve_agent_for_actor`、`_polish_nonverbal_action`。
- `Graph/story_planning_nodes.py` — `story_*_node`、`_prepare_story_planning_node`。
- `Cultivation/` 领域插件 — `cultivation_progress_node`、marker、突破文案,经 beat loop hook 接入。

`GraphDependencies` 独立后,`nodes ↔ beat_nodes` 循环消失,可删 nodes.py:401 懒加载。

### ④ ConversationController — mode-agnostic 会话控制器

把 `_advance_until_player_turn`、`_prime_opening_player_turn`、`_maybe_handle_player_intent_plan_unlocked` 抽到 `Graph/ConversationController.py`。`WebGameSession` 变薄(只管 HTTP/序列化/存档),`demo_run.py` 复用同一 controller。

## 分阶段计划(每阶段 = 独立可合入 + 153 测试全绿 + 中文 commit + code review)

- **阶段 0**:确认 153 测试全绿;若对话流缺端到端快照,补一个作为安全网。
- **阶段 1**:引入 `CharacterRepository`;`deps.character_profiles` 变代理属性;就地 mutate 改具名写方法。(风险最低,先做)
- **阶段 2**:拆 `nodes.py` → `dependencies.py` / `dialogue_nodes.py` / `story_planning_nodes.py`,破循环依赖。纯搬移。
- **阶段 3**:抽 `Cultivation/` 领域插件,改 hook 接入,对话引擎去掉修炼 import。
- **阶段 4**:引入 DTO + `context_builders.py`,四个 agent 入口换签名。
- **阶段 5**:抽 `ConversationController`,`WebGameSession` 变薄,CLI 复用。

## 测试策略

每阶段结束跑 `python -m pytest`(153 个)必须全绿才进下一阶段。高风险符号改动(`GraphDependencies`、`apply_resolved_act`、四个 agent 入口)前跑 GitNexus `impact` 分析并报告 blast radius。

## 非目标(YAGNI)

- 不动 story planning / chapter expansion 的编排逻辑(仅从 nodes.py 搬移,不改行为)。
- 不接入尚未 wired 的 `Recall` 模块。
- 不改玩家可见输出(行为等价重构)。
- 不重写 `BaseAgent` transport(agent 与传输分离留待后续)。
