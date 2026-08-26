# 世界设定编写模块设计

> 一个建在基础模块之上的**世界设定构建服务**：通过预设题材或多轮对话，产出一份
> 结构化的 `WorldSetting`（世界设定包），替代现在写死在开局流程里的修仙种子。它
> 既服务当前故事模式的开局搭建，也供后续「小说书写助手」复用。核心是把写死的
> 修仙题材与升级体系抽象为**题材无关**的数据契约 + 通用等级阶梯。

## 背景与目标

**现状：** 开局剧情架构被硬编码锁死在中文玄幻修仙题材，题材从三层渗入：

1. **默认开局种子（写死）**——`session_bootstrap.build_default_state`（:336）里
   `location_id="云峰入门台"`、`beat="初入仙门"`、`cultivation_goal="…修仙世界立足"`；
   玩家档案默认 `无名修士 / 杂灵根 / 练气一层 / 基础吐纳术`
   （`CharacterProfile.py` 的 `DEFAULT_SPIRITUAL_ROOT/REALM/MAIN_TECHNIQUE`）。
2. **LLM 提示词（写死题材名词）**——`PlayerWriterAgent.PLAYWRIGHT_SYSTEM_PROMPT`
   写 "open-world **xianxia**"、"fixed long-term objective is **cultivation and longevity**"；
   `PlayerWriterFormatter` 多处 `fixed_global_goal="修仙求长生"`；`NarratorAgent`
   系统提示写死 "Chinese **xianxia**"。
3. **玩法系统结构性绑定**——整个 `Cultivation/` 模块（境界阶梯 + 晋升数值）是写死的
   修仙升级；`CharacterProfileBase` 把 `spiritual_root/realm/main_technique` 直接做进
   schema，每个角色被迫带修仙属性。

现有唯一被参数化的只有 `narration_style_preset`（prose 风格：xianxia_default /
light_novel / epic），且它只控文风、不控世界观；连 fallback 旁白都故意忽略它
（`NarrationFallback.build_fallback_intro_text` 明写 "stays in a stable xianxia register"）。

**本次目标：** 新增一个题材无关的世界设定编写模块，产出唯一数据契约 `WorldSetting`，
让预设题材（玄幻/武侠/无限流…）与用户对话生成走同一 Schema，替代写死的开局种子。

**范围边界：**
- **只做「产出 `WorldSetting` + 注入开局」这条链路。** 上层的「小说书写助手」侧边栏
  UI、游戏全程介入编剧的交互，是后续独立模块，不在本次范围。
- **等级体系抽象到「通用阶梯」层面**：有序阶层 + 每层名 + 结构化晋升条件 + 一个轻量
  `AdvancementJudge` 判定框架。各题材具体的计数递增玩法（如无限流轮次+1）**留接口**，
  实现留给各题材玩法模块，本模块不实现。
- **修仙迁移为默认实例**：现有 `Cultivation/` 行为退化为「内置 xianxia `WorldSetting`」，
  开局无设定包时回退到它，保证现有行为逐字节等价。
- **RAG 检索复用故事模式已有的 `StoryTemplateService`** + `selected_template_id`
  引用路径，不另造检索。
- **角色表与势力/地理是增量演进的**：开局只定主角 + 1-2 关键配角 + 初始势力种子，
  其余随后续章节编剧丰富。本模块只产出种子。

## 探查已确认的关键事实

1. **开局注入点**（`session_bootstrap.py`）：`build_default_state`（:336）调
   `build_opening_state(...)`，后者接收显式 kwargs（`chapter_id / location_id / beat /
   cultivation_goal / current_player_realm / current_chapter_realm / next_chapter_realm /
   scene_notes / director_notes` 等）。这是设定包的天然映射目标。
2. **玩家档案构建**（`session_bootstrap.build_player_profile`:116）已接受
   `customization` 与 `profile_defaults` 覆盖参数——覆盖档案默认值的管道已存在，
   只是默认值是 xianxia。
3. **模板引用链路**（现有故事模式）：`WebGameSession` 存 `selected_template_id`，
   `_inject_template_plot_beats_unlocked` 调 `StoryTemplateService.suggest_plot_beats`
   把 `template_plot_beats` 注入 state。本模块的 `template_ref` 复用此路径。
4. **模板服务接口**（`StoryTemplate/StoryTemplateService.py`）：`list_templates` /
   `get_template_detail`（style_bible / characters / beats / skeleton）/
   `suggest_plot_beats` / `next_skeleton_nodes` / `search_style_passages`。RAG 双向检索
   全部复用这些接口。
5. **DirectorAgent 形态**（`Director/DirectorAgent.py` + `DirectorFormatter.py`）：
   系统提示 + formatter 构造结构化 JSON instruction + schema 约束产出。对话式设定
   Agent 借鉴此形态，但由用户多轮介入驱动。

## 数据契约：`WorldSetting`

设定包分两段，呼应「骨架锁定 vs 增量演进」。

### A. 锁定骨架（开局定死，全局稳定）
- `genre_tag` — 题材标签（`xianxia` / `wuxia` / `infinite_flow` / …）
- `tone` — 基调（黑暗 / 热血 / 古典…；升级现有 narration preset 的世界级基调）
- `core_drive` — 核心驱动 / 长期目标（替代写死的 `修仙求长生`）
- `core_conflict` — 核心冲突 / 张力源
- `power_system` — 世界规则 / 力量体系（约束角色能做什么）
- `progression` — 通用等级阶梯（见下）
- `protagonist` — 主角设定：定位 / 起始 tier / 动机 / 初始关系 / 秘密

### B. 增量种子（开局给起点，随章节丰富）
- `key_characters[]` — 1-2 个关键配角（同主角颗粒度）
- `factions_geography[]` — 初始主要地点 + 势力

### 元信息
- `title` / `summary`
- `source` — `preset`（题材工厂模板）/ `dialogue`（对话生成）/ `rag_import`
- `template_ref[]` — 若参考了 RAG 模板，记来源（`template_id` + 引用的片段），允许多个

### `ProgressionSystem`（通用等级阶梯）
- `system_name` — 体系名（"修为境界" / "江湖地位" / "轮回权限"）
- `current_tier_index` — 主角起始所在层
- `tiers[]` — **有序**阶层，每个 tier：
  - `name` — 层名（练气一层 / 三流高手 / 新人）
  - `advance_condition` — 结构化晋升条件 `AdvanceCondition`

### `AdvanceCondition`（结构化晋升条件）
- `type` — 四选一：
  - `event` — 事件门槛：`{ description, completion_marker }`，Director 确认该情节
    发生后放行（现有修仙「筑基丹淬体成功」属此类）
  - `threshold` — 阀值门槛：`{ counter_key, target_value }`，引擎维护计数器
    （轮次 / 评级 / 积分），达标放行（无限流「完成 N 轮」属此类）
  - `narrative` — 叙事自由晋升：无硬条件，Director 按叙事节奏自行判断
  - `composite` — 组合：`{ op: AND|OR, sub_conditions[] }`，递归嵌套上述三类

## 组件

### 1. `GenreFactory`（题材工厂）
存一组预置的完整 `WorldSetting` 模板（玄幻/武侠/无限流…），每个含完整骨架 + 通用
阶梯实例。
- `list_genres()` — 列题材
- `get_template(genre_tag)` — 取完整设定包
- 预设可**一键开局**（直接把模板交给开局流程），也可作为对话 Agent 的**起点**。
- 修仙迁移出来的实例即工厂里的 `xianxia` 模板。

### 2. `WorldBuilderAgent`（对话式设定 Agent）
形态借鉴 DirectorAgent（系统提示 + formatter + 结构化 JSON schema），但由用户多轮
对话驱动。
- **逐项引导**：按 `WorldSetting` Schema 顺序（题材→核心驱动→力量体系→等级阶梯→
  主角→关键配角→势力）逐一询问，每项给**候选选项 + 引导建议**，避免开放式空问。
- 每轮产出：**部分设定包 + 下一待确认项 + 候选选项**，前端渲染成选择/填空。
- **可行性校验**：产出前检查骨架必填项齐全、`progression.tiers` 非空且有序、每个
  `AdvanceCondition.type` 合法、`current_tier_index` 在界内。
- 完成后输出完整 `WorldSetting`。

### 3. RAG 双向检索（复用 `StoryTemplateService`）
- **被动路（Agent 发起）**：拿已知题材/关键词自动检索，命中则主动问用户
  "库里有《X》接近，要不要参考它的世界观/情节骨架？"
- **主动路（用户发起）**：用户随时可说"我想要像库里《某某》XX 那样的设定/桥段"，
  Agent 用这句当 query 调 `search_style_passages` / `suggest_plot_beats`，回片段给
  用户确认，确认后融进当前填的设定项。
- 两路共用同一检索服务；命中记入 `template_ref`；不命中如实告知并纯对话生成；
  服务故障静默降级为纯对话。

### 4. `AdvancementJudge`（晋升判定框架）
接收当前 tier 的 `AdvanceCondition` + 游戏状态，返回「是否可晋升」。
- `event` — 查历史 / plot_flags 里 `completion_marker` 是否达成
- `threshold` — 查 state 里 `counter_key` 计数器是否 ≥ `target_value`
- `narrative` — 交给 Director 按节奏判断
- `composite` — 递归判定子条件，按 `op` 归并
- 计数器（如"已完成轮次"）由各题材玩法钩子递增；本模块**只留接口**，不实现具体
  题材的递增逻辑。

### 5. `WorldSettingApplier`（注入开局）
把 `WorldSetting` 映射成 `build_opening_state(...)` 参数 + `character_profiles`：
- `core_drive` → 替代 `cultivation_goal`
- `progression.tiers[current_tier_index]` 及下一层 → 替代
  `current_player_realm / current_chapter_realm / next_chapter_realm`
- `protagonist` → 主角 profile
- `key_characters[]` → 额外 profiles（开局 1-2 个）
- `factions_geography[]` → 开场 `location_id` + `scene_notes` 种子
- `power_system / core_conflict / tone` → 注入 Playwright/Narrator 提示词上下文，
  替代硬编码 xianxia 字样
- `template_ref` → 复用现有 `selected_template_id` 注入路径，照常喂
  `template_plot_beats`

## 数据流

```
预设题材： GenreFactory.get_template(tag) ──┐
                                            ├─→ WorldSetting ─→ WorldSettingApplier ─→ build_opening_state + profiles ─→ 开局 state
自定义：   WorldBuilderAgent 多轮对话 ──────┘         │
              ↑↓ 双向 RAG（StoryTemplateService）     │
                                                      └─→ template_ref → selected_template_id → template_plot_beats

运行时晋升： AdvanceCondition + state ─→ AdvancementJudge ─→ 可否晋升 ─→ Director/Playwright 推进 tier
```

## 与现有引擎对接

- **`SessionConfig`** 新增 `world_setting` 字段。
- **`build_default_state`** 保留但改为：无设定包时回退到内置 `xianxia` `WorldSetting`
  （修仙成为默认实例，而非写死字面量）。
- **`Cultivation/`** 保留但降级为可选：有 `progression` 的题材启用晋升判定；无等级
  题材 `progression` 为空，`AdvancementJudge` 走 `narrative` 分支，引擎跳过晋升判定。
- **提示词去题材化**：`PLAYWRIGHT_SYSTEM_PROMPT` / `NarratorAgent` 系统提示 /
  `PlayerWriterFormatter` 的 `fixed_global_goal` 里的 xianxia 字样，改为从
  `WorldSetting` 的 `genre_tag / core_drive / power_system / tone` 注入。

## 错误处理

- 对话 Agent 产出的设定包**必过校验**：骨架必填项齐全、`progression.tiers` 非空且
  有序、每个 `AdvanceCondition.type` 合法、`current_tier_index` 在界内。校验失败 →
  回到对话补问，不进开局。
- RAG 服务不可用 / 检索异常 → 静默降级为纯对话生成（对标现有模板服务缺失时的静默
  跳过）。
- 无等级题材 `progression` 为空 → `AdvancementJudge` 直接走 `narrative`，不做晋升判定。

## 测试

- `WorldSetting` Schema 校验单测：合法 + 各类非法（骨架缺项 / tiers 空 / tiers 乱序 /
  非法 `AdvanceCondition.type` / `current_tier_index` 越界）。
- `AdvancementJudge` 四类条件判定单测：event / threshold / narrative / composite
  （含 AND/OR 归并）。
- **修仙迁移回归测试**：默认 `WorldSetting` 走一遍开局，产出 state 与现有
  `build_default_state` 等价。
- `WorldSettingApplier` 映射单测：给一份非修仙设定包（武侠），断言开局 state 无
  xianxia 硬编码字样、等级/驱动来自设定包。
- `WorldBuilderAgent` 用 fake LLM 走一轮「逐项引导→校验→产出完整包」集成测试。
- RAG 双向检索单测：被动命中主动问、用户主动点名检索、服务故障降级三条路径。

## 分期建议（供后续 plan 拆分）

1. **数据契约层**：`WorldSetting` / `ProgressionSystem` / `AdvanceCondition` Schema +
   校验 + `AdvancementJudge`。
2. **迁移层**：把现有修仙抽成内置 `xianxia` `WorldSetting` + `WorldSettingApplier` +
   开局注入 + 提示词去题材化（含回归测试）。
3. **题材工厂**：`GenreFactory` + 多个预设题材模板。
4. **对话 Agent**：`WorldBuilderAgent` + formatter + 逐项引导 + RAG 双向检索。

上层「小说书写助手」侧边栏与全程介入编剧，作为独立后续模块，另立 spec。
