# 角色三层记忆注入系统 — 设计方案

> 日期:2026-08-14
> 状态:待 review(仅设计,不含实现)
> 关联:对话引擎解耦(阶段4 由"每角色专属 DTO"演进为"记忆注入工厂")

---

## 1. 背景与目标

### 1.1 起点
当前所有 agent 入口(`ActorAgent.perform_turn`、`SemanticParserAgent.parse_action`、
`DirectorAgent.update_stage`、`SchedulerPolicy.decide_next_turn`)都直接接收整个
`GameState`,自行从中翻取所需字段。问题:

- **接口过宽**:从签名看不出 agent 实际依赖 state 的哪些部分,GameState 字段难以安全演进。
- **难测试**:测一个 agent 要先造完整的 9 字段 GameState。
- **无"在场"约束**:角色能读到自己不在场时发生的对话,不符合"不在场则无记忆"的设定。

### 1.2 目标
为角色 agent 提供**三层记忆**,通过一个**可注入的记忆工厂**组装后喂给 agent:

1. **短期记忆** — 最近约 3 轮、且发生在角色**在场**期间的对话明细。
2. **长期记忆** — 角色对自身状态的概览,约每 3-5 轮重读一次。
3. **检索记忆** — 对话触发时按语义搜到的相关历史(依赖 Recall 子系统,本轮仅定接口)。

### 1.3 关键约束(review 时确认)
- 工厂**只读**:复用现有的存/写机制(HistoryManager 压缩、Recall 索引),工厂自身不落任何存储。
- 人设**沿用 `CharacterProfile`**,不新建人设结构。
- **本轮只出文档,不改代码。**

---

## 2. 现状盘点(复用什么、缺什么)

### 2.1 已有、可直接复用
| 部件 | 位置 | 提供什么 |
|---|---|---|
| `CharacterMemoryState` | 定义 `CharacterMemory.py:71`;**实例挂在 `state["characters"][actor_id]["memory"]`**(`CharacterRuntimeState.memory`,GameState.py:95) | **每角色一份**三层记忆内容:`short_term_memory` / `long_term_memory` / `consolidated_memory` / `pinned_long_term_memory` / `player_memory` |
| `CharacterProfile` | `CharacterProfile.py`(存在 `CharacterRepository`) | **人设**(name/persona/realm/base_style/分层…)+ **记忆配置** `memory_profile`(限额/深度参数,**非记忆内容**) |
| `CharacterRuntimeState` | `GameState.py:89` | 每角色运行时:`emotion` / `intent` / `known_facts` / `relationship_delta` / `last_turn` / `memory` |
| `CharacterRepository` | `CharacterRepository.py` | 角色档案的单一读写入口(阶段1 建立) |
| `HistoryManager` | `History/HistoryManager.py` | 场景级压缩(≥30 条触发),产出 `scene_memory` 等**视角**记忆(全局,存 `state["memory"]`) |
| `scene["on_stage"]` / `scene["location_id"]` | `GameState.py:78` | 在场角色列表、当前地点 |
| `state["history"]` | `GameState.py:151` | 原始对话明细(逐条 `{turn,actor,mode,content...}`,全局) |

**关键结论(已核对源码,纠正早前推断)**:三层记忆的**数据结构与每角色实例都已具备**,
存放在 `state["characters"][actor_id]["memory"]`(**不是** profile 里;profile 里只有
记忆的**配置** `memory_profile`)。本阶段不造记忆结构,只造"读取 + 在场过滤 + 组装"的工厂。

### 2.2 缺失 / 待衔接
| 缺口 | 说明 | 本方案处理 |
|---|---|---|
| Recall 检索层 | `Recall/retrieval/` 为空,无检索入口函数 | 第三层**只定接口 + 占位**,不实现 |
| "在场"过滤 | 短期层目前是全局 `history[-8:]`,无在场约束 | 工厂新增在场过滤(本方案核心新增值) |
| 长期"重读节奏" | HistoryManager 是"攒够 30 条压缩",非"每 3-5 轮读" | 工厂侧加"至少每 N 轮重读一次"下限(默认 N=4) |
| agent 侧收窄 | agent 仍收整个 state | 本轮**不改 agent 签名**,只新增工厂与 DTO;agent 接入留待独立小步 |

---

## 3. 架构设计

### 3.1 模块归属
新建顶层包 `Memory/`(与 `Recall/` 平级),专管三层记忆的读取与组装:

```
Memory/
  __init__.py
  context.py        # ActorMemoryContext DTO(三层 + 人设引用)
  provider.py       # ActorMemoryProvider 协议(工厂接口)
  default_provider.py  # 默认实现:读 + 在场过滤 + 组装
  scene_filter.py   # "在场才有记忆" 的过滤规则(可配置粒度)
```

工厂实例像 `history_manager` 一样挂到 `GraphDependencies`(可注入、可替换、可 mock):

```python
# Graph/dependencies.py 新增字段(设计意图,非最终代码)
actor_memory_provider: "ActorMemoryProvider | None" = None
```

### 3.2 三层数据来源(工厂只读)

```
ActorMemoryContext(actor_id)
 ├─ persona        ← CharacterRepository[actor_id](CharacterProfile,人设 + memory_profile 配置)
 ├─ short_term     ← state["history"] 经【在场过滤】取最近约 3 轮
 │                    (也可复用 state["characters"][actor_id]["memory"]["short_term_memory"])
 ├─ long_term      ← state["characters"][actor_id]["memory"] 的
 │                    consolidated_memory / long_term_memory / pinned_long_term_memory
 │                    (由 HistoryManager 等维护,工厂只读)
 └─ retrieved      ← Recall.retrieval 检索结果(本轮占位,返回空列表)
```

> 注:角色的三层记忆内容存于 `state["characters"][actor_id]["memory"]`;
> 人设与记忆**配置**存于 `CharacterProfile`。工厂读两处、只读不写。

### 3.3 DTO 形态:只读投影
`ActorMemoryContext` 是 frozen dataclass,构建时从 state / profile **按需抽取**引用
(不深拷贝大对象)。它对 agent 暴露的是**收窄后的只读视图**,而非整个 GameState。

```python
@dataclass(frozen=True)
class ActorMemoryContext:
    actor_id: str
    persona: CharacterProfile          # 人设(沿用现有结构)
    short_term: list[HistoryItem]      # 在场过滤后的最近数轮明细
    long_term: LongTermView            # 角色自我状态概览(读现有字段)
    retrieved: list[RecallHit]         # 检索命中(本轮恒为空)
```

---

## 4. 三层细节

### 4.1 短期记忆 —— 在场过滤(本方案核心新增)
规则(默认严格粒度,可调):

- 遍历 `state["history"]`,只保留满足以下条件的条目,再取最近 3 轮:
  - **严格粒度(默认)**:该条目所属回合,`actor_id ∈ scene["on_stage"]`(角色当时在台上)。
  - **地点粒度(可选备选)**:该条目发生地点 `location_id` == 角色当前所在地点。
- 判定"某回合角色是否在场"需要历史里能追溯当时的 on_stage。**已核对源码**:
  `HistoryItem`(`History/GameMemory.py:6`)**只有** `turn/actor/mode/content` 及若干
  文本/工具字段,**不带** `on_stage` / `location_id`。逐条明细无法直接追溯当时在场者;
  现有的 `on_stage` 快照只存在于 `SchedulerMemory.on_stage`(视角级)与压缩块
  (`HistoryCompression.py:26/31` 的 `location_id`/`on_stage`,块级),粒度都比逐条粗。
  - 备选 1(**补记**):写 history 时给每条 `HistoryItem` 增补 `on_stage`/`location_id`
    快照(存侧小改),之后可精确逐条过滤。**推荐**,一劳永逸。
  - 备选 2(**兜底**):不改存侧,短期层先用全局最近 3 轮兜底,后续再收窄。改动最小,
    但"不在场则无记忆"约束此时是**未完全满足**的。
  - review 决策点 A:选"补记"(前置一小步存侧改动)还是"先全局兜底"(约束延后满足)。

### 4.2 长期记忆 —— 复用为主 + N 轮下限兜底
- 数据源:`state["characters"][actor_id]["memory"]` 里的 `consolidated_memory[-k]` +
  `long_term_memory[-k]` + `pinned_long_term_memory`(全部已由现有压缩机制维护)。
- 节奏:默认复用 HistoryManager 的压缩产物;工厂额外维护"距上次为该角色组装长期视图
  已过 N 轮(默认 4)则重新组装一次",避免长时间不压缩导致自我认知过期。
  - 该"上次组装轮次"是工厂的**读缓存**,不写回 state。
  - review 决策点 B:N 的取值(3 / 4 / 5),以及是否需要这个兜底(若嫌复杂可去掉,纯复用)。

### 4.3 检索记忆 —— 仅定接口 + 占位
- 接口(工厂内部,Recall 检索层做好后填实现):

```python
def retrieve(self, actor_id: str, query: str, *, user_id: str, player_id: str,
             top_k: int = 5) -> list[RecallHit]:
    # 本轮:return []
    # 未来:调 Recall.retrieval,doc_id 带 u{user}:p{player}: 租户前缀,
    #       RRF + 三因子重排,失败降级为空
    ...
```

- 契约要点(与 `docs/rag-recall-progress.md` 对齐):
  - **租户隔离**:检索必须带 `u{user_id}:p{player_id}:` 前缀,禁止跨租户命中。
  - **降级**:Recall 不可用 / 超时 → 返回空列表,绝不阻断对话回合。
  - 触发时机:玩家或其他角色发话后、该角色 perform_turn 前。
- review 决策点 C:检索的 `query` 用什么(最近一句玩家输入?当前 beat 主题?),本轮可先不定死。

---

## 5. 与对话引擎的接入点(本轮不实现)

未来接入时,`actor_paths.py` 的 NPC 回合会变成:

```
# 现状:actor_agent.perform_turn(state=state, character_profiles=...)
# 目标:
ctx = deps.actor_memory_provider.build(actor_id, state)   # 工厂组装三层
actor_agent.perform_turn(ctx)                              # agent 只拿收窄视图
```

分步落地(每步独立提交 + 测试,不在本轮):
1. 建 `Memory/` 包与 DTO / Provider 协议 / 默认实现(短期+长期两层,检索占位)。
2. `GraphDependencies` 挂 `actor_memory_provider`,builder 里默认构建。
3. Actor 一条路径先接入(NPC + 玩家回合),验证"在场才有记忆"。
4. 视效果决定是否推广到 Director / Narrator / Scheduler,以及是否收窄它们的签名。
5. Recall 检索层做完后,填实第三层。

---

## 6. 测试策略(实现阶段用)
- **在场过滤单测**:构造含"角色 A 在场 / 下场 / 再上场"的 history,断言 A 的短期记忆
  只含其在场期间的对话。
- **长期兜底单测**:模拟 N 轮未压缩,断言工厂触发重组。
- **检索降级单测**:Recall 抛错 / 返回空,断言工厂返回空且不影响回合。
- **DTO 只读**:断言 frozen、断言不深拷贝大对象(引用一致)。
- 全程守住现有 153 回归。

---

## 7. 待 review 决策点汇总
- **A(短期过滤前置依赖)**:已核实 `HistoryItem` **不带** on_stage/location 快照(只有视角级/块级快照)。选"补记逐条快照"(推荐,精确)还是"先全局最近3轮兜底"(改动最小,约束延后)。
- **B(长期节奏)**:N 轮下限取值,以及是否保留该兜底。
- **C(检索 query)**:第三层检索用什么查询文本(本轮可暂缓)。
- **D(在场粒度)**:默认严格 on_stage,是否改用/并存 location 粒度。
- **E(推广范围)**:本轮是否只做 Actor 一条路径,Director/Narrator/Scheduler 留后。
