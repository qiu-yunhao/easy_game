# easy_game 代码走读 —— 未完成的改动项

> **来源**：2026-08-03 全项目走读结论。
> **状态**：优先级 #1（`actor_create_agent.py` 拆分 + 切断 `Graph/nodes.py:66` 反向依赖）已在 `2026-08-03-split-actor-create-agent.md` 中完成，本文档保留剩余尚未修改的问题清单。
> **背景规模**：约 11K LOC / 60+ 文件；架构（transport → session → Graph → agents → domain/persistence）可辨认，但边界靠约定不靠代码约束。

---

## 一、架构混杂（层级泄漏）

> ✅ 第 3 项中「`Graph/nodes.py:66` 反向导入根目录 `actor_create_agent`」已随 #1 拆分修复；`GraphDependencies` 巨型 dataclass 未拆，仍列在下方。

**1. 传输层直接握持领域逻辑**
- `web_server.py:110-156` HTTP handler 直接编排 `create_new_game / save / load`。
- `web_server.py:33` 在 `__init__` 就 `bind_save_context`。
- 存档业务应下沉到 session 层之下。

**2. `WebGameSession`(702 行) 变成第二条状态写入路径**
- `web_session.py:369-467` 的 `_maybe_handle_player_intent_plan_unlocked` / `_append_tool_message_unlocked` 直接改 `state["history"] / runtime / player`。
- 绕过 `Graph.builder.resolve_story_turn` 与 `Graph/nodes.py:504 history_commit_node`。
- Graph 本该是唯一状态机。

**3. `GraphDependencies` 巨型 dataclass**
- `Graph/nodes.py:74-98` 定义 19 个可选字段的 `GraphDependencies`。
- 每个 node 都能拿到全部依赖 → 应按子图切分 Deps。
- （反向依赖问题本身已在 #1 里通过 `from Actor.ActorCreateAgent import ActorCreateAgent` 修复。）

**4. Persistence 反向依赖 domain**
- `Persistence/Store.py:19` 从顶层 `StoryStateUtils` 导入 `build_character_roster_summary`。
- `Store.py:340-443 query_character_roster` 100 行里混 ORM 查询 + 业务过滤 + 展示层字段拼装。

**5. `session_bootstrap.py` 不是纯 composition root**
- `_warm_model_client`(54-89) 在 wiring 路径上做并发预热与副作用绑定。

**6. 三个入口默认值分叉**
- `demo_run.py:24-89 build_demo_*`
- `session_bootstrap.py:111-361 build_default_*`
- `web_session.py:469-479 _rebuild_session`
- 各自装配一份开局 profile + scene_config + state。

---

## 二、代码冗余（复制粘贴）

**1. Actor 三胞胎 fork-and-modify**
- `ActorAgent / L1ActorAgent / L2ActorAgent` 的 `__init__` 与 `perform_turn` 逐字重复。
- 只差 system prompt 与温度：`Actor/ActorAgent.py:40-65` vs `L1ActorAgent.py:26-52` vs `L2ActorAgent.py:29-71`。
- Formatter 三入口同一 payload：`ActorFormatter.py:214-249`。
- 应参数化为 `ActorAgent(tier=...)`。

**2. Agent boilerplate 遍布**
- "组 payload → render_json_instruction → self.command" 在以下文件各写一遍：
  - `Actor/ActorFormatter.py:64-72`
  - `Narrator/NarratorAgent.py:107-125`
  - `StylisticPolish/StylisticPolishAgent.py:45-90`
  - `PlayerControl/SemanticParserAgent.py:44-66`
  - `Director/DirectorFormatter.py:180-216`
- `BaseAgent`(`BaseAgent.py:69-145`) 只覆盖 `chat.completions`，不覆盖 payload/重试/fallback。

**3. 两套重试互不知情**
- `PlayerWriterAgent._execute_with_retry`(`PlayerWriter/PlayerWriterAgent.py:70-100`) + 4 组 `_xxx_is_complete / _missing_xxx_fields`(102-188) 是「schema 后校验重试」。
- `BaseAgent._repair_json_response`(`BaseAgent.py:159-199`) 是「JSON 修复重试」。
- 其它 Agent 遇到字段空无补救。

**4. ResolvedAct 抽取二次实现**
- `PlayerControl/SemanticParserAgent.py:69-108 build_resolved_act_payload` 手工把 11 个字段逐个 `raw_result.get(...)`。
- 绕过 `Actor/ActorFormatter.py:123-211 normalize_resolved_act` 再喂回去。

**5. `clone_json` 重复**
- `Persistence/store_common.clone_json` 已存在。
- `web_session.py:56 _json_clone` 又实现一次 `json.loads(json.dumps(...))`。

**6. 字符串清洗散点**
- `StoryStateUtils.clean_text` 已是公共函数。
- `Narrator/NarratorAgent.py:52-63 _clean_intro_snippet`、`StylisticPolish/StylisticPolishAgent.py:93-95 deterministic_nonverbal_cleanup` 又各写一份「trim + 合并空白 + 去引号」。

**7. Heuristics 无共同契约**
- `Actor/ActorHeuristics.build_heuristic_resolved_act`
- `PlayerWriter/StoryPlanningHeuristics` 4 个 `build_heuristic_*`
- `PlayerIntentPlannerAgent.build_heuristic_player_intent_plan`
- 都是「LLM 失败 fallback → 同型 dict」，没有基类 / 注册表。

---

## 三、God 文件

> ✅ 根目录 `actor_create_agent.py`（1112 行）已在 #1 中拆分为 `Actor/ActorCreate{Schema,Prompt,Heuristics,Agent}.py` 并删除根 shim。

| 文件 | 行数 | 问题 |
|---|---|---|
| `web_session.py` | 702 | 22 方法混合锁 / 存档 / 快照 / 依赖构造 / 游戏推进 / 序列化 |
| `Actor/ActorRuntime.py` | 695 | 无类，25+ 私有函数，实际含 3 个子域：关系 / 记忆 / 玩家印象 |
| `PlayerWriter/PlayerWriterFormatter.py` | 654 | 名为 formatter，实际含 `normalize_*` / `build_*_instruction` / `scene_candidate_to_plan` 全套 |
| `Actor/ActorCreateAgent.py` | 672 | ⚠️ #1 拆分后仍偏大（含中文 docstring）；后续如再拆可按方法组切分 |
| `Graph/nodes.py` | 521 | 事实上的门面 module；`CULTIVATION_SIGNAL_MARKERS`(101-115) 是领域词表应在 `Cultivation.py` |
| `Persistence/Store.py` | 493 | `query_character_roster`(340-443) 100 行混三层职责 |
| `ToolSkillRegistry.py`（根目录） | 473 | `TOOL_SKILLS` 几百行字面量数据 + 文件系统副作用挤在一起 |
| `Director/DirectorRuntime.py` | 460 | 三组 LLM 输出清洗常量(15-47)混入 runtime |

---

## 四、顶层"倾倒场"

根目录 20+ 个 `.py` 无分层：

```
CharacterProfile / CharacterMemory / Cultivation / GameState /
ScenePlan / SceneConfig / ResolvedAct* / StoryStateUtils /
StoryToolContext / SupportingSceneIntentPolicy / GameplayTuning /
PromptUtils / LazyImport / ComponentFactory / BaseAgent /
ToolSkillRegistry / actor_create_agent(已删)
```

- 建议归入 `Domain/{Character, Story, System}/` + `Common/`。
- `SceneConfig.py`(260B)、`ScenePlan.py`(548B) 这种单类文件应合入 `Domain/Story/schemas.py`。
- 根目录 `__init__.py`(0B) 把它变成一个包，加剧混乱 —— 要么删掉，要么明确其用途。

---

## 建议改动优先级（剩余）

> ✅ 原优先级 #1 已完成，编号沿用原顺序。

- [x] **#1 已完成** — `actor_create_agent.py` → 拆 `Actor/ActorCreateAgent.py + ActorCreateSchema.py + ActorCreatePrompt.py + ActorCreateHeuristics.py`；切断 `Graph/nodes.py:66` 反向依赖。
- [ ] **#2** — `WebGameSession` 抽出 `PlayerActionOrchestrator`（处理 intent_plan + tool_call 分支）+ `SessionPersistenceMixin`；`_append_tool_message_unlocked` 的 state 写入交回 Graph node。
- [ ] **#3** — `Actor/{ActorAgent, L1ActorAgent, L2ActorAgent}` 合并为 tier 参数化单类。
- [ ] **#4** — `BaseAgent` 上提「SceneContextPayload 构造 + schema 后校验重试」契约，收敛 Agent boilerplate。
- [ ] **#5** — `GraphDependencies` 按子图切；`CULTIVATION_SIGNAL_MARKERS` 迁至 `Cultivation.py`。
- [ ] **#6** — 根目录 20 个 `.py` 归入 `Domain/*`；合并极小单类文件；删掉根目录空 `__init__.py` 或明确其用途。
- [ ] **#7** — `Persistence/Store.query_character_roster` 抽 `RosterQueryService`，切断对 `StoryStateUtils` 的反向依赖；删掉 `_json_clone` 用 `store_common.clone_json`。
