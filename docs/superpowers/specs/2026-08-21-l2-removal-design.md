# 全局移除 L2 角色分层 — 设计文档

**日期**：2026-08-21
**状态**：已确认，待转 implementation plan

## 目标

从 easy_game 全代码库彻底移除 L2 角色分层，收敛为 **L1 + actor** 两层模型。验收标准：源码（非测试、非注释）中不再出现 `L2` / `l2_profile`。

## 背景

当前存在三层角色模型：
- **L1**：主角/核心角色，玩家绑定（player_bound_instance），有结构化 `l1_profile`，容量上限 6。
- **L2**：重要配角，同为玩家绑定，有独立结构化 `l2_profile`，容量上限 15，且是**创建角色时的默认层**。
- **actor**：功能型 NPC，共享模板（shared_template），无结构化 profile，容量不限。

探查结论（关键事实）：
- L2 的独有运行时 agent（`L2ActorAgent` / `SupportingSceneIntentPolicy` / `build_l2_actor_instruction` / `ComponentFactory.build_l2_actor_agent`）**是死代码**——`Graph/dialogue_nodes._resolve_agent_for_actor` 只分支 `agent_type=="L1"` vs 其他，L2 角色实际由普通 `ActorAgent` 扮演。
- `DirectorFormatter` 已是两层（只识别 L1/actor），但 `DirectorRuntime._prioritize_active_actors` 仍是三层。
- Plan 4 曾在 `store_snapshot._resolve_story_layer` 把 L2 临时折叠为 actor；本次纠正为折叠为 L1。
- L2 是单向依赖到类型核心（`CharacterProfile.AgentType` / `_resolve_*`）的中间层。

## 已确认的核心决策

1. **L2 并入 L1**：所有原 L2 角色成为 L1，保留玩家绑定和结构化 profile。
2. **max_L1 = 21**：玩家绑定角色总量不变（原 6+15），取消 L1/L2 子预算区分。
3. **删除 `l2_profile`**：只用 `l1_profile`。
4. **不保留旧存档迁移逻辑**：当前无 L2 存档，直接用 L1 替代，代码中不写任何为遗留 L2 数据保留的兼容分支。
5. **删除所有 L2 死代码**。

## 架构与执行策略

单分支（chained off main），按依赖顺序自底向上重构：**类型核心 → 容量/roster → 创建流程 → 调度 → 持久化 → 死代码删除 → 测试/验收**。每步跑测试，全绿后 `--no-ff` 合并到 main。

---

## 第 1 节：类型核心（`CharacterProfile.py`）

重构地基，所有其他文件依赖它。

- `AgentType`（L20）：`Literal["actor", "L2", "L1"]` → `Literal["actor", "L1"]`
- `StoryLayer`（L21）：`Literal["player", "actor", "L2", "L1"]` → `Literal["player", "actor", "L1"]`
- 删除 `L2AgentProfile` TypedDict（L27-33）
- 删除 `CharacterProfile.l2_profile` 字段（L78），保留 `l1_profile`
- `_resolve_agent_type`（L148-158）：删除 `l2_profile` present→L2 分支；**`profile_source=="actor_create_agent"` 默认 `"L2"` → `"L1"`**
- `_resolve_story_layer`（L161-178）：`agent_type in {"L1","L2"}` → `agent_type == "L1"`
- `_resolve_storage_mode`（L181-182）：L2 消失后只有 L1/player→player_bound，actor→shared_template
- 删除 `normalize_l2_agent_profile`（L224-263）
- `ensure_character_profile`（L393-406）：删除 l2_profile 填充逻辑。**不需要**为旧数据丢弃 l2_profile 写迁移分支（字段与类型均已删除，无 L2 存档）
- `promote_character_profile_to_l1`（L435-464）：L2 消失后此函数语义退化为"确保 L1"；评估简化或保留为 no-op 兼容。若无调用方依赖其"提升"语义，倾向简化/删除

## 第 2 节：容量 / roster 汇总

`StoryStateUtils.py`、`Actor/ActorCreateSchema.py`、`CharacterRosterTools.py`、`ToolSkillRegistry.py`。

**StoryStateUtils.py：**
- 删除 `MAX_L2_CHARACTERS = 15`；`MAX_L1_CHARACTERS` 6 → **21**（L50-51）
- `VALID_CHARACTER_ROSTER_FILTERS`（L52）：`("L1","L2","ActorAgent","all")` → `("L1","ActorAgent","all")`
- `normalize_roster_layer_filter`/`matches_roster_layer`（L55-68）：去掉 l2→L2 归一化
- `build_character_roster_summary`（L77-104）：删除 `total_L2`/`max_L2`/`remaining_L2`；`total_player_bound = total_l1`
- `build_character_roster_decision_hints`（L107-132）：迭代 `("L1","ActorAgent")`
- `serialize_story_cast_member`（L188-208）：删除 `l2_profile` 序列化

**ActorCreateSchema.py：**
- 删除 `MAX_L2_AGENTS = 15`；`MAX_L1_AGENTS` 6 → 21（L23-25）；`MAX_STORY_CHARACTERS=21` 保留
- 删除 `L2_PROFILE_SCHEMA`（L63-98）
- agent_type enum（L169-172）：`["actor","L2","L1"]` → `["actor","L1"]`；删除 `l2_profile` 属性（L174）

**ToolSkillRegistry.py：**
- `layer_filter` enum（L279）：去掉 "L2"；summary keys 迭代（L384）去掉 `total_L2`

**CharacterRosterTools.py：** 随 summary/filter 变化联动调整。

## 第 3 节：创建流程（`Actor/ActorCreate*`）

**ActorCreateHeuristics.py：**
- `_resolve_story_agent_type`（L303-362）：三路→两路。背景提及保底 **L1**（原"至少 L2"，L354）；**默认 fallback（L362）`"L2"` → `"L1"`**；"replaceable"→actor 保留；核心/长期→L1 保留
- `_count_story_layers`（L365-381）：只数 L1
- `_resolve_effective_roster_counts`（L384-416）：删除 total_L2 合并逻辑
- `_respect_agent_layer_limits`（L419-456）：降级阶梯 **L1→actor**（原 L1→L2→actor），用新 MAX_L1_AGENTS=21
- `_respect_player_bound_capacity`（L459-495）：计数只用 existing_l1 + new_l1

**ActorCreateAgent.py：**
- 删除 `normalize_l2_agent_profile`/`MAX_L2_AGENTS` 导入（L27,47-48）
- 删除 `existing_l2_count`/`new_l2_count` 跟踪（L132,386,390-391,570-573）
- prompt payload（L154,176-186）：删除 `L2_rule`/`max_l2_agents`/`existing_l2_agents`
- 指令文案（L240）："If agent_type is L2, include l2_profile…" 删除
- contextual-actor 路径（L266,338-339）：去掉 L2 选项
- story_layer 设定（L502-557）：只处理 L1；删除 l2_profile 填充（L546-554）
- 移除 `MAX_L2_AGENTS` 导出（L672）

**ActorCreatePrompt.py（LLM 文案）：**
- L19,20,23,32-37,39：所有 L1/L2 措辞改为只讲 L1/actor 两层。L34"用 L2 承担软性支撑"整条删除；L36"不确定长期分量→选 L2"改为两层措辞；L39 l2_profile 条款删除

## 第 4 节：调度（Director）+ 运行时 agent 选择

`Director/DirectorRuntime.py`、`Director/DirectorAgent.py`、`Actor/ActorAgent.py`、`Actor/ActorFormatter.py`。（`DirectorFormatter.py` 已两层，无需改。）

**DirectorRuntime.py：**
- `_resolve_actor_tier`（L254-264）：返回 "L1"/"actor"
- `_prioritize_active_actors`（L288-309）：分组 `{"actor","L1"}`；排序两层——focus/L1 pressure→`("L1","actor")`，else→`("actor","L1")`

**DirectorAgent.py（prompt 文案）：**
- L35-37："L1 major / L2 support-heavy" → 只描述 L1 与 actor 两层职能
- L49："L1/L2 full" → "L1"

**ActorAgent.py（system prompt）：**
- rule 10（L30-34）："If agent_type is L2, prioritize l2_profile…" **整条删除**
- rule 12（L36）：L1 用 l1_profile，保留

**ActorFormatter.py：**
- 删除 `build_l2_actor_instruction`（L237-249，见第 6 节）
- `agent_contract`/player_memory（L69-85）：已只认 L1，无需改

## 第 5 节：持久化

`Persistence/Models.py`、`store_sync.py`、`Store.py`、`store_snapshot.py`。**无需任何旧存档迁移分支。**

**Models.py：**
- `agent_layer` 列 default（L149）：`"L2"` → `"L1"`（新写入缺省）

**store_sync.py：**
- `template_kind` 校验集（L64-66）：`{"actor","L2","L1"}` → `{"actor","L1"}`
- `seed_starter_story_characters`（L105）：模板筛选 `IN ("L1","L2")` → `IN ("L1")`
- upsert 缺省（L171,177）：`agent_layer` 缺失 default `"L2"` → `"L1"`

**Store.py（roster 读路径）：**
- `query_character_roster`（L397-400）：`clean_text(row.agent_layer, "L1")`（普通缺省，非迁移）；分类只 L1/actor；计数只 total_l1
- `agent_type` 输出（L409）：只 L1
- `normalize_loaded_state`（Plan 4 引入）：**不加** L2→L1 / 丢弃 l2_profile 的迁移分支

**store_snapshot.py：**
- `_resolve_story_layer`（Plan 4 曾折叠 L2→actor）：**改为 L2→L1**，与本次决策一致；保留 player/actor/L1 直通。此后 `build_story_character_records`（filter `!="L1"`）会把原 L2 角色纳入 story_character 表
- 注：这会改变 Plan 4 行为（原 L2 存 actor_interaction 表 → 现存 story_character 表）。对应测试（上一轮已迁 L1）与新方向一致

## 第 6 节：死代码删除

运行时从未被调度，删除零行为影响。

- 删除 `Actor/L2ActorAgent.py` 整个文件
- 删除 `SupportingSceneIntentPolicy.py` 整个文件
- `Actor/ActorFormatter.py`：删除 `build_l2_actor_instruction`（L237-249）
- `ComponentFactory.py`：删除 `build_l2_actor_agent`（L57-64）及 TYPE_CHECKING 导入（L13）
- `Actor/__init__.py`：删除 `L2ActorAgent` import/export（L5,L12）

## 第 7 节：测试 + 验收

**改动测试**（去除 L2 断言/fixture）：
- `test_character_roster_tools.py`：mock payload 的 `total_L2` 断言（L202/224/276）删除；roster summary 断言随两层调整
- `test_agent_profile_layers.py`、`test_beat_resolution.py`、`test_character_memory_two_tier.py`、`test_director_formatter_tiers.py`、`test_director_formatter_two_tier.py`、`test_player_command_tools.py`、`test_scheduler_policy.py`、`test_store_snapshot_story_layer.py`、`test_story_authoring_subgraph.py`：逐个把 L2 fixture/断言迁为 L1 或删除（视测试意图）

**删除测试**：专测 L2 独有行为的测试（L2ActorAgent、SupportingSceneIntentPolicy、build_l2_actor_instruction）随死代码删除。

**最终验收：**
- 全套 pytest 绿
- `grep -ri 'L2\|l2_profile' --include='*.py'` 在源码（非 tests、非注释）返回空
- 合并前对 main 跑 `detect_changes` 复核影响面

## 数据流

- **创建**：`ActorCreateAgent` → `_resolve_story_agent_type` 返回 L1/actor → `_resolve_agent_type` 默认 L1（actor_create_agent 源）→ profile 只带 `l1_profile`
- **运行**：`dialogue_nodes._resolve_agent_for_actor` L1→l1_actor_agent，其他→actor_agent（不变，L2 分支本就不存在）
- **调度**：`DirectorRuntime._prioritize_active_actors` 两层排序
- **持久化**：save 经 `store_snapshot._resolve_story_layer`（L1/actor/player 直通）；load 经 `Store.query_character_roster`（L1/actor）

## 风险与边界

- `promote_character_profile_to_l1` 的去留需在实现时确认调用方（若被非 L2 场景调用，保留为"确保 L1"语义）。
- `agent_type` 被复用为运行时调度键 + 持久化层键 + 玩家 auto-mode 标志（web_session 把玩家临时设 "L1"）——枚举收窄不影响此路径（玩家用 L1，本就保留）。
- 测试迁移需逐个判断意图：是"测层级行为"（迁 L1）还是"测 L2 独有物"（删除）。
