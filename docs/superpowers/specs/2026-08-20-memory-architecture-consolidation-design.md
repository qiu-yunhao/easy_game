# 记忆系统架构梳理与收敛设计

日期：2026-08-20
状态：架构梳理中（brainstorming，本轮不写代码）

## 缘起

排查「单次玩家行动 16–28s」时定位到记忆刷新 hook 约 4.3s（`session_bootstrap.py:388` 把 `compression_trigger_size` 误设为 1，导致几乎每轮全量压缩）。原本只想「把压缩异步化 + 接 RAG」，但深入代码后发现**记忆模块本身已有结构性混乱**：短期队列重叠、两套长期记忆并存、L1/L2/Actor 三分无实质差异。因此先梳理现状、定目标架构，再决定分几步实现。

---

## 一、现状全景：喂给一个 Actor Agent 的完整数据

装配点 `Actor/ActorFormatter.py:_build_actor_payload`（56–89 行），一个 Actor 收到：

| 模块 | 字段 | 来源 |
|------|------|------|
| 剧情 | `plot` | state.plot |
| 人设 | `actor_profile` | 工厂 persona（CharacterProfile） |
| 契约 | `agent_contract` | persona（agent_type / L1 / L2 profile / memory_profile 队列上限） |
| 场景 | `scene` / `scene_plan` / `director_brief` | state |
| 运行时 | `actor_runtime` | state.characters[id]（emotion/intent/known_facts/relationship） |
| 待执行 | `next_act` | state.runtime |
| **记忆（见下）** | 5 条队列 | 两条链路 |

## 二、记忆的两条链路（关键）

### 链路 A：工厂投影（`DefaultActorMemoryProvider` → `ActorMemoryContext`）

不落 state.characters，**每次现从 state 算**：

- `recent_history` = `short_term`：`filter_history_by_presence(state["history"], …)` 在场过滤 + 最近数轮，**逐条原文明细**。
- `recalled_memories` = `retrieved`：`recall_service.query_recall` 的 RAG 检索结果（**当前恒空**，检索通道已接线但没喂数据）。

### 链路 B：角色自有主观记忆（`CharacterMemoryState`，存 `state.characters[id].memory`）

由 `Actor/ActorRuntime.py` 在**每次角色行动后**主动维护，是一套完整的「多视角主观记忆」管线：

- `pinned_long_term_memory` / `long_term_memory`：`LongTermMemoryEvent`，带 `subjective_interpretation`（主观解读）、`belief_formed`（形成的信念）、priority、tags、linked_characters。
- `consolidated_memory`：`ConsolidatedMemoryBlock`，超限时把旧长期批量整合。
- `short_term_memory`：`ShortTermMemoryEvent`，带 summary 的精简近期条目。
- `player_memory`：`PlayerImpressionMemory`，该角色对玩家的印象（关系值 + 关键事件）。

写入逻辑要点（ActorRuntime.py）：
- `_build_long_term_memory_event` 的 `perspective_id`（213 行）：一次行动从**行动者/被指向者/旁观者**各自视角分别记一条，解读不同 → 天然带归属。
- `_should_record_long_term_memory`（199 行）：门槛过滤（揭露事实 / 关系剧变 ≥1.5 / 幕章结束 / interrupt / event）。
- 整合：`_append_long_term_memory` 超限批量合并成 consolidated。

### 第三份（编排链路，非 Actor）

`state.memory.{scene,playwright,director,scheduler}_memory` 由 `HistoryManager.build_memory` 从 `compressed_blocks` 派生，喂给 **Playwright/Director/Scheduler** 编排类 Agent（`StoryToolContext`）。**Actor 说台词不读这个。** 这就是最初 4.3s 压缩的产物。

---

## 三、诊断出的混乱点

1. **两个「短期」职能重叠**：payload 同时有 `recent_history`（链路 A，客观原文投影）和 `recent_short_term_memory`（链路 B，角色自有精简条目）。同一个「最近发生了什么」喂两份，格式不同。
2. **两套「长期」概念混淆**：
   - 全局客观：`state.memory.compressed_blocks`（CompressedHistoryBlock，上帝视角事实）。
   - 角色主观：`state.characters[id].long_term_memory`（带主观解读/信念，per-character）。
   两者名字都叫「长期/压缩」，实为不同东西。
3. **L1/L2/Actor 三分无实质差异**：仅差队列上限数字 + depth（full/compact），行为无本质分叉。用户判断：退成「主要角色 / NPC」两级即可。
4. **player_memory 澄清**：链路 A 与链路 B 并非各有一个——payload 里只有一个 `player_memory`，取自 `CharacterMemoryState`。不冗余（此前列表列重了）。

---

## 四、目标架构（已定稿）

### 4.0 核心原则
- **所有记忆由 Factory（记忆模块工厂）解耦管理。** `state` 不再背各角色的记忆队列。
- **`state.characters[id]` 只保留：角色 id + 角色信息（人设/运行时情绪 intent 等）。** 记忆构建全部由工厂在装配 Agent 时现算。
- 客观事实的唯一权威仍是 `state.history`（+ 压缩块 + 游标）。角色不再各存主观副本。

### 4.1 角色两级
- 用 **L1（主要角色） / NPC-Actor** 替代 L1/L2/Actor 三分。删掉 L2 档与三分的行为分叉。
- 两级差异只体现在「拥有哪些记忆部分」（见 4.2），不再是队列上限数字的微调。

### 4.2 记忆三部分（取代现有 5 队列）
工厂为 Agent 组装的记忆收敛为三部分：

| 部分 | 内容 | 来源 | L1 | NPC-Actor |
|------|------|------|----|-----------|
| **短期记忆** | 在场信息队列 | 工厂从 `state.history` 在场过滤 + 最近数轮**现算**，不预存 | ✅ | ✅ |
| **长期记忆** | 客观旧事 | **RAG 召回**（compressed_blocks→pgvector），用时现查，无预存 | ✅ | ❌ |
| **玩家印象** | 对玩家的印象（关系/好感） | 角色对玩家印象 | ✅ | ❌ |

- **NPC-Actor 只有：短期记忆 + 角色信息。** 无长期、无玩家印象。
- **L1 有全部四项**（短期 + 角色信息 + 长期RAG + 玩家印象）。

### 4.3 废弃「主观长期记忆」，改由导演执导替代
- 现有 `subjective_interpretation` / `belief_formed` 是**写死的模板串**（ActorRuntime.py:222 起）+ 从人设抄字段，并非真主观。
- **导演拥有全局视角，「导演 → 角色」是单向执导过程。** 角色的立场/解读不该是角色自存的静态队列，而由导演基于全局统筹。这就是「主观记忆放错了层」——它本质想干「告诉角色怎么演」，该属导演，不属角色自存。
- **导演只下发幕级整体指导**（当前 beat 该怎么演、谁主导、张力方向），不精确到 per-character。具体到人由 Actor 依据幕级指导 + 自身人设去演。→ **`DirectorBrief` 现有字段（`beat_goal` / `who_should_respond` / `focus_character` / `notes` / `lead_in_text` / `wrap_up_text`）已够用，本设计不新增 per-character 执导映射。**
- **角色跨场景一致性**：L1 主角靠**自带 RAG 召回 + 导演指导**双重保证（主角有自我连续性）；NPC 完全听导演。
- **删除**：`CharacterMemoryState` 里的 `long_term_memory` / `consolidated_memory` / `short_term_memory` 队列；`ActorRuntime.py` 中维护它们的逻辑（`_build_short_term_memory_event`/`_append_short_term_memory`/`_build_long_term_memory_event`/`_derive_long_term_belief`/`_append_long_term_memory`/整合）。
- **保留**：玩家印象（`player_memory`，仅 L1）。

### 4.4 长期记忆 = 客观 RAG 召回（仅 L1）
- 长期完全等同 RAG 召回的客观压缩块，无任何预存主观队列、无 pinned。
- 挂链路 A 的 `retrieved`（Agent 组装时填）。写入端把 `compressed_blocks` 以 `doc_type="memory_block"` 落 pgvector（与现有幕级 `scene_summary`/`act_chunk` 并存）。
- **归属过滤（按条 on_stage）**：写入时把逐条 `on_stage` 快照落 metadata；召回时只返回「该角色当时在台」的条目。与短期的 `filter_history_by_presence` 在场语义对称。
- **去重（查询限 turn 范围）**：只召回 `turn_end < window_start` 的旧块，与可见短期窗口天然不相交。

### 4.5 异步压缩（原始动机）
- `compression_trigger_size` 1 → 30；`summary_horizon_turns` → 45。
- 压缩挪后台（仿 `AsyncSceneIndexer`）：轮末 snapshot enqueue → 后台打分+摘要+写 RAG → 下轮轮首无超时 join，合并结果、推进游标、删除 `state["history"]` 已压缩原始项（**成功后才删**；块内 `raw_items` 副本保留）。

### 4.6 记忆写入收归 Factory（读写分离 + 纯函数风格）

现状：记忆的**写入**分散三处——(a) `ActorRuntime._apply_memory_updates` 直接 mutate `state.characters[id].memory`；(b) `HistoryManager.build_memory` 派生压缩块/视图；(c) `Persistence/Store` 整体序列化 `state`。收敛目标：把记忆写入统一由 Factory 侧一个**写管理器**管，读侧 `DefaultActorMemoryProvider` 维持只读不变。

- **读写分离（已定稿）**：保留 `DefaultActorMemoryProvider`（读，`build()`）及其「必须只读」协议不动；**新增独立写管理器 `MemoryStore`**（Memory 模块下），与 provider 并列挂 `GraphDependencies`。「Factory」概念 = 读 provider + 写 store 两个协作对象，职责清晰。
- **纯函数风格（已定稿）**：`MemoryStore` 的写方法一律 `(state, ...) -> state 片段/新 state`，**不持有记忆状态、不内部 mutate**。调用方（ActorRuntime / 压缩 hook / 存档层）负责把返回片段合回 state。与现有 LangGraph immutable 风格、以及 `insert_snapshot` 整体序列化 `state` 的存档层完全兼容。

收归的三条写入路径：

| 写入路径 | 现状入口 | 收归后 | 备注 |
|----------|----------|--------|------|
| **玩家印象** | `ActorRuntime._apply_memory_updates`→`_append_player_memory` 直接改 `state.characters` | `MemoryStore.record_player_impression(state, actor_id, event) -> new_characters` | 仅 L1 生效；ActorRuntime 只调用、不再手搓 `state.characters` mutation |
| **压缩块/视图派生** | `HistoryManager.build_memory` | `MemoryStore.compact(state) -> (blocks, new_last)` + `MemoryStore.derive_views(state, blocks) -> memory_state`（与步骤 2 的 `compact_snapshot`/`derive_views` 同一份，落到 MemoryStore 名下） | 步骤 2 的后台压缩改调 MemoryStore；HistoryManager 保留纯算子被 MemoryStore 复用 |
| **存档序列化** | `Persistence/store_sync.insert_snapshot` 整体 `clone_json(state)` | `MemoryStore.serialize_memory(state) -> dict` / `MemoryStore.deserialize_memory(dict) -> memory 片段`，存档层调 MemoryStore 取记忆片段 | 记忆片段的形状收敛后由 MemoryStore 定义，存档层不再直接理解记忆内部结构 |

- **不收归**：RAG 向量写（`compressed_blocks`→pgvector）仍留在 `AsyncMemoryCompactor`（步骤 3），不进 MemoryStore——向量索引是外部副作用、异步、可失败重试，与「记忆状态的纯函数写」性质不同。
- **依赖注入**：`MemoryStore` 与 `DefaultActorMemoryProvider` 一样可注入、可 mock，挂 `GraphDependencies`（如 `deps.memory_store`）。

---

## 五、实现分步（初步，待定稿后细化）

- **步骤 1｜记忆工厂收敛**：角色两级；工厂输出三部分记忆；删除 `CharacterMemoryState` 的 long/consolidated/short 队列 + `ActorRuntime` 维护逻辑；`state.characters` 瘦身为「id + 角色信息 + 玩家印象(L1)」。导演执导字段承接原主观定位。**新增 `MemoryStore`（读写分离的写侧），玩家印象写入改由 `MemoryStore.record_player_impression` 纯函数处理，ActorRuntime 只调用。**
- **步骤 2｜异步压缩**：修常量、压缩挪后台、跨轮 join、成功后删原始项。解决 4.3s 延迟。**压缩/派生纯算子（`compact`/`derive_views`）落 `MemoryStore` 名下，后台压缩调 MemoryStore。**
- **步骤 3｜RAG 写入+召回**：compressed_blocks 写 memory_block（带 on_stage metadata）、召回接链路 A retrieved（归属过滤 + turn 去重），仅 L1 启用长期召回。（向量写留在 AsyncMemoryCompactor，不进 MemoryStore。）
- **步骤 4｜存档序列化收归**：`MemoryStore.serialize_memory`/`deserialize_memory` 定义记忆片段形状，`Persistence` 存档层改调 MemoryStore 存取记忆片段，不再直接理解记忆内部结构。

---

## 六、仍需细化（进入 writing-plans 前）

1. **导演执导（已定稿）**：只下发幕级整体指导，复用 `DirectorBrief` 现有字段，不新增 per-character 映射。L1 一致性靠自带 RAG 召回 + 导演；NPC 听导演。
2. 玩家印象（仅 L1）现有写入逻辑（`_player_memory_targets` 等）保留哪些、如何只对 L1 生效。
3. 步骤 1 是重构但会改 Actor payload 形状（删预存队列、短期改统一投影）——需盘点对现有 Actor prompt / 测试的影响面。
4. `DirectorFormatter` / `_serialize_stage_character` 里的 L2 分支（`_group_actor_ids_by_tier`、`scene_support_bias`、`tiered_directing_contract` 的 L2 规则）随两级化一并清理的范围。
