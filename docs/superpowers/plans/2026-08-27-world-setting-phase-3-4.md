# 世界设定编写模块 · 阶段 3–4 实现计划

> **状态：** 待执行。承接 `2026-08-26-world-setting-phase-1-2.md`，但修正其中“已接入开局”的不完整之处。

**目标：** 让内置题材真正能创建非修仙开局，并提供无 UI 依赖的多轮世界设定 API。用户可选预设或在对话中确认一份 `WorldSetting`，再显式应用它开始游戏；参考小说只在用户确认后写入设定并复用既有模板注入链路。

**不做：** 小说书写助手侧栏、设计器页面、全程介入的编剧、具体题材的计数器递增钩子、持久化未完成的设定对话。前端随后只需调用本计划新增 API，不另设 BFF。

## 先决结论（设计审查后固定）

1. **阶段 1–2 只实现了数据对象，尚未完成运行时注入。** `WebGameSession` / `SessionConfig` 没有 `world_setting`，重建流程固定调用 `build_default_state()`；因此必须先补运行时链路，再写 `GenreFactory`。
2. **不得把 `WorldSetting` 直接塞进每个 agent。** 唯一运行时真源放在 `state["plot"]["world_setting"]`；新增一个纯函数将其裁剪为 prompt 所需的 `world_context`。这样存档、场景流转和各 agent 都读同一个版本。
3. **现有 `realm_*` 字段暂不改名。** 它们是对外状态、章节大纲和存档的兼容字段；阶段 3 把它们的值解释为“通用 tier 名”，而不做高风险全仓库 rename。新增注释和 helper，之后若重构再迁移名称。
4. **v1 仅支持有序等级体系。** 现有 validator、applier、章节规划和 transition 都要求 `tiers` 非空；原 spec 中“无等级题材 progression 为空”的要求与现状冲突。此计划的三个预设均有 tiers。无等级题材须在后续独立变更中先定义 `progression: None` 的 schema、章节推进语义和 UI 文案，不能以空数组偷偷放行。
5. **模板引用可有多个，但运行中只选一个。** 现有引擎仅有一个 `selected_template_id`。应用世界设定时选 `template_ref[0]` 作为运行时模板；其余引用保留在设定中供未来使用，绝不假装已同时注入。
6. **RAG 的被动检索需要一个小补口。** 现有 `search_style_passages` 必须先知道 `template_id`，无法“在库中找相近小说”。在 `StoryTemplateService` 新增跨模板检索 facade，复用已有向量库、embedding 和 `template_id` metadata，不新建索引或表。

## 交付边界与验收

完成后应满足：

- `GenreFactory.list_genres()` 能列出 `xianxia`、`wuxia`、`infinite_flow`；`get_template()` 每次返回独立副本。
- 将武侠或无限流设定传给 `WebGameSession.reset(world_setting=...)` 后，开局地点、目标、tier、角色档案、prompt context 和序列化 state 全来自该设定；不出现修仙默认文本。
- 默认调用路径仍得到当前修仙开局，且不提供 `world_setting` 时原有 web API 行为不变。
- 对话流程每回合只询问一个固定字段、返回候选项；只有完整且校验通过的设定才可被应用。
- 被动/主动模板参考都必须由用户确认后才写进 `template_ref`；模板服务异常只得到无参考候选，不中断对话。

---

## Task 1：补齐通用运行时上下文与开局注入

**目的：** 先让任意合法的、带 tiers 的 `WorldSetting` 可以贯穿 session、状态、提示词和存档。此任务是题材工厂的前置，不能跳过。

**Files:**

- Create: `WorldSetting/runtime.py` — 纯函数：读取 setting、产生最小 `world_context`、按 tiers 计算后继 tier/transition 文案
- Modify: `WorldSetting/applier.py` — 产出显式的角色默认字段和开场描述；不再让非修仙档案落回默认灵根/功法
- Modify: `session_bootstrap.py` — `build_state_from_world_setting()`，并使 `build_default_state()` 仅作为 xianxia 兼容包装
- Modify: `GameState.py` — `PlotState` 增加 `world_setting: dict[str, Any]`
- Modify: `web_session.py`, `web_server.py` — config/reset/snapshot/serialize 接受并保留 `world_setting`
- Modify: `PlayerWriter/PlayerWriterFormatter.py`, `PlayerWriter/StoryPlanningHeuristics.py`, `Graph/story_planning_state.py`, `Graph/transition_payloads.py` — 用 runtime helper 代替直接的 `Cultivation` 序列函数
- Modify: `Narrator/NarratorAgent.py`, `Narrator/NarrationFallback.py` — 动态 world context，fallback 不再固定仙侠措辞
- Test: `tests/test_world_setting_session.py`, `tests/test_world_setting_prompt_context.py`, `tests/test_world_setting_transition.py`

### 1.1 先锁定兼容行为

- 为无 `world_setting` 的 `WebGameSession.reset()` 与 `build_default_state()` 加回归测试：地点、默认角色、当前 realm 与已有期望相同。
- 用一份最小武侠 setting 写失败测试，断言 `reset(world_setting=ws)` 后 state 的 `plot.world_setting`、开场地点、目标、tier、角色和 snapshot 都来自 `ws`。
- 测试 invalid setting 在 API 边界抛可读错误，且不替换当前 session 状态。

### 1.2 定义最小 runtime helper

`WorldSetting/runtime.py` 只提供以下纯函数，不建立 class hierarchy：

```python
world_context(world_setting) -> dict[str, str]
tier_pair(world_setting, current_index=None) -> tuple[str, str]
chapter_tier_sequence(world_setting, start_tier, count) -> list[tuple[str, str]]
transition_requirement(world_setting, current_tier, next_tier) -> str
```

- `world_context` 仅包含 `genre_tag`、`tone`、`core_drive`、`core_conflict`、`power_system`、`progression.system_name`，不传递整个 setting 给 prompt。
- `transition_requirement` 为 event/threshold/composite/narrative 生成可读提示；只描述条件，不调用 `can_advance()`，更不引入计数器玩法。
- xianxia 的 transition 文案维持现有表现；其他题材使用 tier 名和结构化 condition。所有边界（顶层、未知 tier）都有稳定 fallback。

### 1.3 让开局和角色档案以 setting 为准

- 新建 `build_state_from_world_setting(world_setting, *, player_character, player_profile)`：先 `validate_world_setting`，再用 `apply_world_setting` 的 `opening_kwargs` 与角色 seeds 建 state。
- 合并优先级固定为：**题材 preset/setting → setting protagonist seed → 用户 `player_profile`**；用户明确输入永远最后覆盖。
- 在 `apply_world_setting` 给 profile 补入该世界的中性默认值（例如武侠的 `spiritual_root="根骨"`、`main_technique="基础拳法"`），从而不触发 `ensure_character_profile` 的仙侠默认文本。旧字段名暂保留兼容，但任何面向模型/用户的文案取 `world_context`，不用“灵根/功法”标签。
- `build_default_state()` 调 `build_state_from_world_setting(build_xianxia_world_setting(), ...)`；如果必须保留原子境界数值链路，限制在 xianxia 兼容分支并用单测锁定，不能影响其他题材。
- `build_opening_state()` 写入 `plot["world_setting"]`。只从 `template_ref[0]` 派生 `selected_template_id`。

### 1.4 接入 session、状态与 API

- `SessionConfig` 增加 `world_setting: dict[str, Any] | None`，`WebGameSession` 只从 `config.world_setting` 重建。
- `reset(..., world_setting=None)` 的 `None` 表示“不改当前选择”；新增 `clear_world_setting` 只在确有产品入口时再加，当前不在该 API 偷偷把 `None` 解读为清除。
- web reset payload 只允许 JSON object；服务端先校验，之后才调用 session reset。
- runtime snapshot 存完整 setting；序列化状态额外提供只读 `world_summary`（title / genre_tag / tone），避免前端重复解析完整契约。
- 既有 `selected_template_id` 仍可单独设置；显式 API 选择优先于 setting 派生值，且需在 README/API 注释中说明。

### 1.5 提示词与旁白去题材化

- 系统提示改成题材无关的“多角色中文叙事游戏”；原本的 xianxia、cultivation、longevity、one realm per chapter 等硬规则从静态 prompt 删除。
- Playwright 每个 instruction 都加入 `world_context`，用它替代 `fixed_global_goal`/`creative_goal` 的固定修仙描述；章节排序由 `chapter_tier_sequence` 返回，保留既有 JSON 字段 `realm_stage`/`next_realm`。
- Narrator 的 action 与 intro instruction 都加入 `world_context`，约束改为“符合该世界的语域与规则”。fallback 使用 `genre_tag`/`tone` 的中性句式，禁止“修士、仙途、气机、云气”等固定词。
- Graph 和 heuristic 只调用 runtime helper 来生成 tier 序列和 transition requirement；不得在非 xianxia 路径调用 `Cultivation`。

### 1.6 验收

- 武侠全链路测试：开局、一次故事 premise/outline formatter、旁白 intro、一次章节 transition，断言 prompt/state/fallback 无仙侠默认词，且 tier 为“三流→二流”。
- 无限流全链路测试：threshold condition 生成“完成 N 轮”类 transition 文案，不要求实现计数器递增。
- xianxia 精确回归 + 既有 `test_session_bootstrap.py`、story-planning、narrator 测试全绿。

---

## Task 2：实现 `GenreFactory` 与三个可开局预设

**目的：** 把预设选择变为 `WorldSetting` 的单一来源，不把题材逻辑散回 session 或前端。

**Files:**

- Create: `WorldSetting/genre_factory.py`
- Create: `WorldSetting/wuxia_preset.py`
- Create: `WorldSetting/infinite_flow_preset.py`
- Modify: `WorldSetting/__init__.py`
- Test: `tests/test_genre_factory.py`

### 2.1 工厂契约

```python
list_genres() -> list[dict[str, str]]
get_template(genre_tag: str) -> WorldSetting
```

- `list_genres` 只返回 `genre_tag`、`title`、`summary`；不在列表接口泄露可变模板对象。
- `get_template` 对未知 tag 抛 `WorldSettingError`；每次 `deepcopy` 后再 `validate_world_setting`，调用者改动返回值不污染下一局。
- xianxia 直接复用 `build_xianxia_world_setting()`，禁止复制第二份同样的阶梯常量。

### 2.2 内置模板内容（最小而完整）

- `wuxia`：江湖地位阶梯，至少“三流 / 二流 / 一流 / 宗师”；event/narrative 条件组合；主角、师父或同伴、一个城镇/门派种子。
- `infinite_flow`：轮回权限阶梯，至少“新人 / 正式行者 / 资深行者”；下一阶至少含一个 `threshold(counter_key="cleared_rounds")`；主角、队友、初始副本种子。
- 每个预设均写明 `tone`、`core_drive`、`core_conflict`、`power_system`，并包含 1 个 location + 至少 1 个 key character；不要为了“可选性”增加配置文件、数据库或插件机制。

### 2.3 验收

- 参数化测试三个 tag：合法、独立副本、阶梯有序、每个 preset 可直接通过 Task 1 的 session reset。
- 未知 tag、外部改动返回模板、倒序 tiers 都有负例。

---

## Task 3：提供题材选择 API（无前端 UI）

**目的：** 让现有 web/API 客户端能一键选择预设；UI 以后只消费此接口。

**Files:**

- Modify: `web_session.py`
- Modify: `web_server.py`
- Modify: `frontend/js/api.js`（仅增加 API 方法；不增加页面或入口）
- Test: `tests/test_web_world_settings.py`

### 接口

- `GET /api/world-settings` → `GenreFactory.list_genres()`
- `GET /api/world-settings/{genre_tag}` → 预设完整 setting（只用于编辑/预览）
- `POST /api/reset` 支持二选一：`world_setting`（完整 object）或 `genre_tag`（服务端 factory 展开）。两者同时提供返回 400，避免“谁覆盖谁”的隐式规则。

### 验收

- 使用 `genre_tag="wuxia"` reset 后状态与直接传 `get_template("wuxia")` 等价。
- 传入未知 tag、非法 object、tag 与 object 同时传入不会重建当前 session。
- 不改现有 entry/select 前端页面；仅 `api.js` 具备日后调用能力。

---

## Task 4：实现可测试的世界设定对话工作流

**目的：** 让多轮交互可被 fake LLM 验证，LLM 只做建议/结构化填充，不拥有状态机或校验权。

**Files:**

- Create: `WorldSetting/builder.py` — 纯状态机与 draft 合并
- Create: `WorldSetting/WorldBuilderFormatter.py` — instruction/payload 组装
- Create: `WorldSetting/WorldBuilderSchema.py` — response JSON schema
- Create: `WorldSetting/WorldBuilderAgent.py` — `BaseAgent` 薄封装
- Modify: `WorldSetting/__init__.py`, `web_session.py`, `web_server.py`, `frontend/js/api.js`
- Test: `tests/test_world_builder.py`, `tests/test_world_builder_api.py`

### 4.1 状态机与安全边界

- 固定顺序：`genre_tag → tone → core_drive → core_conflict → power_system → progression → protagonist → key_characters → factions_geography → title/summary`。
- 每个 turn 状态固定为：`draft`、`current_field`、`question`、`options`、`reference_candidates`、`status`。只允许当前 field 的 patch 进入 draft，阻止模型一次改掉用户已确认的字段。
- 每轮给 2–4 个可选建议，但自由文本始终可用。用户可退回任一已完成字段；退回后清除其后的未确认字段，避免自相矛盾。
- 只有最后一项完成后调用 `validate_world_setting`；校验失败返回具体待补字段并继续，绝不自动“修正”用户设定。
- `WorldBuilderAgent` 的 JSON response 至少含 `field_patch`、`next_question`、`options`、`reference_query`。纯 workflow 清洗/限制 patch，agent 输出不能直接入 session。

### 4.2 Session 与 API

- `WebGameSession` 仅保存一个内存中的 builder workflow；同一 session 的锁保护其读写。重启、reset 或 load 时丢弃未完成 draft，并明确返回状态而非尝试持久化半成品。
- `POST /api/world-builder/start`：可选 `genre_tag`，以 factory 模板作为草稿起点或空 setting 作为草稿；返回第一问。
- `POST /api/world-builder/answer`：接受 `answer` 和可选 `reference_action`，返回下一问或 `complete` setting。没有完成前不重建游戏。
- `POST /api/world-builder/apply`：只接受本 session 已完成且未被篡改的 draft；调用已有 reset(world_setting=...)。该显式确认避免一次回答意外重置游戏。
- 端点先用 fake agent 和 fake template service 测试；实际 agent 的创建沿用 `ComponentFactory`/`BaseAgent` 注入方式，不在 HTTP handler 直接创建 OpenAI client。

### 4.3 验收

- fake agent 可完整走一份武侠 setting；每次只推进一个字段，最终通过 validator。
- 无效 progression、越界 tier、模型试图改已确认 field、apply 未完成草稿均为负例。
- apply 后的 session state 与 Task 1 直接 reset 世界设定相同。

---

## Task 5：补足双向 RAG 参考，并纳入 builder 确认流

**目的：** 真正复用 `StoryTemplateService`，而不是用标题猜测“相似小说”。检索只提供参考，不能把小说内容或模板直接覆盖用户世界设定。

**Files:**

- Modify: `StoryTemplate/StoryTemplateService.py`
- Modify: `WorldSetting/builder.py`, `WorldSetting/WorldBuilderAgent.py`
- Modify: `web_session.py`, `web_server.py`
- Test: `tests/test_story_template_world_search.py`, `tests/test_world_builder_rag.py`

### 5.1 最小跨模板检索 facade

新增：

```python
search_template_passages(query: str, *, top_k: int = 6) -> list[dict[str, Any]]
```

- 复用现有 embedding 与 `vector_store.search(..., filters={"doc_type": "style_passage"})`；不加 `template_id` filter。
- 从每个命中 doc 的 metadata 读取 `template_id`，用已有 `list_templates()` 映射标题；返回 `template_id`、`source_title`、`passage`、`score`。
- service 内按 template id 去重，最多返回 3 个模板、每模板最多 2 条短片段。`query` 空白直接返回空列表，异常交给上层静默降级。

### 5.2 两条 builder 路径

- **被动：** 在用户确认题材/核心驱动后，用当前已知文本查询跨模板 facade；只展示最多 3 个候选，问“是否参考”，不自动写入草稿。
- **主动：** agent 将用户“参考《X》/类似某桥段”的意图输出为 `reference_query`。workflow 调用跨模板检索；用户选择候选后，才调用已有 `get_template_detail`、`search_style_passages`、`suggest_plot_beats` 获取有限片段和桥段建议。
- 确认后仅把 `{template_id, passages}` append 至 `template_ref`，并把经用户确认的摘要填入当前 field；绝不从模板自动复制人物或完整剧情。应用 setting 时按 Task 1 的“第一条引用”规则连到 `selected_template_id`。
- 检索服务缺失、报错或无结果时返回正常的下一问且不附候选；日志可记录异常，但 HTTP 响应不暴露基础设施详情。

### 5.3 验收

- fake vector search 验证跨模板结果按 template 去重、metadata 正确映射标题、空 query 不检索。
- 被动命中只产生候选，不变更 `template_ref`；接受后才写入。
- 主动查询可返回 passages/beats；拒绝、无结果、服务异常均能继续完成纯对话设定。

---

## Task 6：回归、文档与发布门槛

1. 新增 API/行为写入 `README.md` 或 web API 文档：世界设定是 reset 级操作、一个运行时模板限制、草稿不持久化。
2. 更新阶段 1–2 计划的状态说明：Task 1–6 已完成的范围与本计划承担的运行时补口；不要补勾每一个历史子步骤而伪造 TDD 记录。
3. 运行分层测试：

```powershell
python -m pytest tests/test_world_setting_*.py tests/test_genre_factory.py tests/test_world_builder*.py tests/test_web_world_settings.py -q
python -m pytest tests/test_session_bootstrap.py tests/test_web_session_templates.py tests/test_agent_template_injection.py tests/test_narrator_intro_flow.py -q
python -m pytest tests/ -q
```

4. 当前解释器必须为 Python 3.11+（项目已有 `typing.NotRequired` 依赖），且必须安装 pytest；在修复环境之前，不能把“全绿”写进提交说明。
5. 任何业务代码编辑前遵循仓库 `AGENTS.md`：对被改 symbol 做 GitNexus impact 分析；提交前运行 `detect_changes()`，确认只影响该计划涉及的调用流。

## 推荐执行顺序

`Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6`

先交付预设可开局（Task 1–3），再加自定义对话和 RAG（Task 4–5）。这样即使阶段 4 延后，武侠/无限流也已经可用，且不会在尚未打通的运行时链路上堆一个不可验证的 Agent。
