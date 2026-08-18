# 情节模板运行时注入设计

> 建游戏/大章开始时选定一个已入库的情节模板（StoryTemplate），在剧情规划的
> **chapter 展开**与 **scene 候选**两层，把模板检索到的骨架/桥段作为**软指导**
> 参考素材注入 LLM 提示词，指导剧情走向。模板纯可选，缺失/故障时静默降级为现有
> 纯 LLM 规划。

## 背景与目标

**现状：** `StoryTemplate` 子系统的解析侧已完成——小说 → 4 类模板（风格/角色/桥段/骨架）
入库（MySQL 4 表 + pgvector），并经 `StoryTemplateService` Facade 暴露 4 个检索接口
（`suggest_plot_beats` / `next_skeleton_nodes` / `get_style_bible` / `search_style_passages`）。
但**消费侧完全未接线**：`GraphDependencies`、`PlaywrightAgent`、`PlayerWriterFormatter`
里没有任何模板引用；剧情四层规划（premise → outline → chapter → scene）全部是纯
LLM/启发式生成，不看模板。这正是 `memory/project_story_template.md` 标注为
「以后消费（不在本次范围）」的那部分。

**本次目标：** 打通「读选定模板 → 检索 → 注入两层规划」这条运行时链路，让玩家选中的
情节模板能实际指导剧情发展。

**范围边界：**
- **只注入 chapter 展开 + scene 候选两层**（不动 premise / outline）。
- **软指导**：模板作参考素材，LLM 可借鉴可偏离，不强制靠拢；保留开放世界灵活性。
- **手动指定 template_id**（本次不做自动相似性匹配）。
- **单一当前模板**：state 存一个 `selected_template_id`，建游戏时设定、每个大章开始可覆写。
- **静默降级**：模板缺失/无效/检索空/服务故障时，行为与现有纯 LLM 规划逐字节一致。
- **本次做 state 字段 + 设置接口**；写这个字段的 UI/存档逻辑不在范围（接口留给上层调用）。

## 探查已确认的关键事实

1. **两层规划入口**（`Graph/story_planning.py`）：`_ensure_chapter_expansion`（:272）调
   `playwright_agent.expand_current_chapter(...)`；`_ensure_scene_candidates`（:327）调
   `playwright_agent.generate_scene_candidates(...)`。二者都在 agent 方法里走
   `self.formatter.build_*_instruction(...)` 构造提示词 + `_execute_with_retry`。
2. **agent 两方法**（`PlayerWriter/PlayerWriterAgent.py`）：`expand_current_chapter`（:258）、
   `generate_scene_candidates`（:299），当前签名末位均有 `history=None`。
3. **formatter 两方法**（`PlayerWriter/PlayerWriterFormatter.py`）：
   `build_chapter_expansion_instruction`（:436）、`build_scene_candidates_instruction`（:538），
   内部构造 `payload` dict 再序列化成 instruction 文本。
4. **检索接口返回类型**（`StoryTemplate/TemplateSchema.py`）：
   - `next_skeleton_nodes(tid, *, chapter_hint)` → `list[PlotSkeletonNode]`
     （字段 `node_id/order_index/title/event_summary/preconditions/maps_to_chapter_hint`）
   - `suggest_plot_beats(tid, *, query, top_k=5)` → `list[PlotBeat]`
     （字段 `beat_id/label/tags/summary/dramatic_function/reusable_conflict`）
5. **state 更新为不可变风格**（`Graph/story_planning_state.py`，`_apply_*` 系列）：
   `dict(state["plot"])` 拷贝后返回新 state，不原地改。
6. **PlotState**（`GameState.py:50`）已有 `chapter_id`、`chapter_goal`、`story_outline` 等字段。
7. **GraphDependencies**（`Graph/dependencies.py:32`，`@dataclass(slots=True)`）是运行时依赖集散地，
   现有 agent 字段均默认 None。

## 架构

依赖流向单一：`组装期 → GraphDependencies.story_template_service → 编排层读 deps →
作方法参数下传 agent → agent 检索 + 格式化 → 作 template_guidance 传 formatter →
拼进 instruction`。agent 不持有 service（无状态），service 是「规划时才用」的临时入参。

```
apply_selected_template(state, tid)         # 上层调用：建游戏/大章开始设定 selected_template_id
        │
        ▼
state.plot.selected_template_id ── 读 ──► _ensure_chapter_expansion / _ensure_scene_candidates
                                              │ 下传 deps.story_template_service
                                              ▼
                                   agent.expand_current_chapter(..., template_service=svc)
                                   agent.generate_scene_candidates(..., template_service=svc)
                                              │ build_template_query(state, history)
                                              │ svc.next_skeleton_nodes / svc.suggest_plot_beats
                                              │ format_skeleton_guidance / format_beat_guidance
                                              ▼
                                   formatter.build_*_instruction(..., template_guidance=text)
                                              │ 非空则作 payload 字段拼进提示词
                                              ▼
                                          LLM 生成（软指导：可借鉴可偏离）
```

## 组件与文件结构

- **Modify** `GameState.py` — `PlotState` 加 `selected_template_id: int`（默认 0=无模板）。
- **Modify** `Graph/story_planning_state.py` — 加 `apply_selected_template(state, template_id) -> GameState`
  （不可变更新；`template_id<=0` 清为 0）。
- **Modify** `Graph/dependencies.py` — `GraphDependencies` 加
  `story_template_service: "StoryTemplateService | None" = None`（TYPE_CHECKING 下 import）。
- **Create** `PlayerWriter/StoryTemplateGuidance.py` — 3 个纯函数：
  - `build_template_query(state, history) -> str`：拼「章节目标（`chapter_goal` + `active_outline_chapter_id` 对应 outline 条目的 `title`/`main_goal`）+ 最近剧情」检索线索；history 为空则只用章节目标。
  - `format_skeleton_guidance(nodes: list[PlotSkeletonNode]) -> str`：骨架节点 → 软指导文本；空列表返回 `""`。
  - `format_beat_guidance(beats: list[PlotBeat]) -> str`：桥段 → 软指导文本；空列表返回 `""`。
- **Modify** `PlayerWriter/PlayerWriterAgent.py` — `expand_current_chapter` / `generate_scene_candidates`
  各加 `template_service=None` 参数；内部检索 + 格式化（含 try/except 降级），把 guidance 传 formatter。
- **Modify** `PlayerWriter/PlayerWriterFormatter.py` — `build_chapter_expansion_instruction` /
  `build_scene_candidates_instruction` 各加 `template_guidance: str = ""` 参数；非空时作 payload
  新字段（chapter→`reference_skeleton`，scene→`reference_beats`）拼进 instruction。
- **Modify** `Graph/story_planning.py` — `_ensure_chapter_expansion` / `_ensure_scene_candidates`
  调 agent 方法时传 `template_service=deps.story_template_service`。

## 数据流：两层注入细节

**检索线索（两层共用 `build_template_query`）：**
- 章节目标：`state["plot"]["chapter_goal"]` + 当前 outline 条目的 `title`/`main_goal`（当前条目 = `story_outline` 中 `chapter_id == active_outline_chapter_id` 的那条；找不到则跳过 outline 部分，只用 `chapter_goal`）。
- 最近剧情：从 `history` 取最近若干条内容拼接；`history` 为空（大章刚开始）→ 只用章节目标。

**chapter 层（`expand_current_chapter`）：**
1. `tid = state["plot"].get("selected_template_id", 0)`；`template_service` 与 `tid>0` 均满足才注入。
2. `query = build_template_query(state, history)`。
3. `nodes = template_service.next_skeleton_nodes(tid, chapter_hint=query)`。
4. `guidance = format_skeleton_guidance(nodes)`（软指导措辞：可参考骨架走向，不必严格遵循）。
5. `formatter.build_chapter_expansion_instruction(..., template_guidance=guidance)`。

**scene 层（`generate_scene_candidates`）：**
1. 同样门槛（service + tid>0）。
2. `query = build_template_query(state, history)`（同一线索）。
3. `beats = template_service.suggest_plot_beats(tid, query=query, top_k=5)`。
4. `guidance = format_beat_guidance(beats)`（软指导措辞：桥段作场景候选灵感参考，不必照搬）。
5. `formatter.build_scene_candidates_instruction(..., template_guidance=guidance)`。

## 错误处理（静默降级）

净效果：任一降级路径都使输出与现有纯 LLM 规划**逐字节一致**。

- `deps.story_template_service is None` → 不下传，`template_service=None` → 跳过注入。
- `selected_template_id <= 0` → 跳过注入。
- 检索返回空列表 → `format_*` 返回 `""` → formatter 不加该段。
- **检索抛异常**（服务/DB 故障）：agent 内 `try/except` 包住检索，异常时记日志、`guidance=""`
  继续跑纯 LLM 规划——模板故障绝不阻断游戏。
- `template_guidance=""` 时 formatter 不加 `reference_skeleton`/`reference_beats` 字段，payload 结构与现状一致。

## 测试（全部免真 LLM/DB，用 fake）

1. **`build_template_query`**：有 history / history 为空（退化只用章节目标）两例。
2. **`format_skeleton_guidance` / `format_beat_guidance`**：正常多条 / 空列表返回 `""`。
3. **`expand_current_chapter`**：注入生效（fake service 返回骨架 → guidance 拼进 instruction）、
   `tid=0` 跳过、`service=None` 跳过、检索抛异常降级——4 例。
4. **`generate_scene_candidates`**：对称 4 例（fake service 返回桥段）。
5. **编排层** `_ensure_chapter_expansion` / `_ensure_scene_candidates`：从 `deps.story_template_service`
   正确下传（fake deps + fake agent 断言收到 service）。
6. **`apply_selected_template`**：设正值 / `<=0` 清零 / 返回新 state 不改原 state。
7. **回归**：deps 不挂 service 时，两层规划输出与改动前一致（formatter payload 无新增字段）。

## 复用的现有能力（不改）

- `StoryTemplateService` 及其 4 个检索接口（`StoryTemplate/StoryTemplateService.py`）——仅调用。
- formatter 现有 payload 结构——只加可选字段，不改既有键。
- 生产调用方默认行为——所有新参数带默认值（None/""/0），不传即现状。

## 边界

- **向后兼容第一**：`selected_template_id` 默认 0、`story_template_service` 默认 None、
  agent/formatter 新参数默认 None/""——不选模板/不挂服务时全链路逐字节退化为现有行为。
- **软指导，不强制**：注入的是「参考素材」提示词，LLM 可偏离；不做硬约束/骨架对齐校验。
- **只动两层**：不注入 premise/outline，不改检索算法、不改模板解析侧、不改摘要粒度。
- **手动 template_id**：本次不做自动相似性匹配（记忆里规划的「大章按相似性偏移」是后续独立特性）。
- **不做写字段的 UI**：`apply_selected_template` 供上层调用；何时/如何触发（建游戏向导、存档、配置）留给调用方。
- TDD 红→绿→中文 commit，**不 push**。
