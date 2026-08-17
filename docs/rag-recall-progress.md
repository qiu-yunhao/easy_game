# RAG 用户回忆系统 — 进度存档

> 存档日期：2026-08-13
> **重大更新：2026-08-17** —— 项目已完成基础模块体系重构，向量后端由 Redis 改为 pgvector。
> 本文档下方「二～五」的部分旧假设已作废，**以本节顶部的「※ 2026-08-17 重新规划」为准**。
> 权威 spec：`docs/superpowers/specs/2026-08-15-foundation-modules-design.md`。

---

## ※ 2026-08-17 重新规划（当前有效，优先级最高）

> **组装已完成（2026-08-17）**：多库混排抽象层 `db/access.py::DataAccess`（存档=MySQL、回忆=Postgres，回忆库可选懒建）+ 回忆栈工厂 `Recall/service/factory.py::build_recall_stack`（未配置返回 (None,None) 且不加载 embedding；三工厂可注入）+ `web_demo.py` 接线（`--recall-database-url`/`STAGEBOUND_RECALL_DATABASE_URL`、`_setup_recall` bind_recall_service/indexer 并 start、关闭 stop、失败降级）。全套 262 测试全绿。**回忆栈至此端到端接通**，剩下的只是真实 pg 环境部署 + bge 模型下载。

### 已发生的方向变更
1. **向量后端 Redis Stack → pgvector**（`vector(512)` + HNSW `vector_cosine_ops`）。旧文档所有 Redis/RediSearch 假设**作废**。
2. **公共能力已剥离为分层基础模块**（第一层互不依赖，第二层组合）：
   - `datatypes/`：`VectorDoc(doc_id, doc_type, text, metadata)` + `ScoredDoc(doc, score, factors)` + `tenant_prefix(user,player)="u{user}:p{player}:"` / `template_prefix(...)`。
   - `db/`：`DatabaseConfig` + `Database`（engine/session 封装，`session()` 上下文管理器、`create_all`）。
   - `vectordb/`：`VectorStore` 抽象 + `PgVectorStore(database_url, *, table="vector_docs", dim=512)`（doc_id 主键幂等 upsert、`<=>` 余弦、metadata `meta->>key` 过滤、`reset()` 测试用）。
   - `embedding/`：`EmbeddingModel` 抽象 + `BgeEmbeddingModel(model_name="BAAI/bge-small-zh-v1.5", batch_size=32)`（归一化、懒加载 sentence_transformers）。
   - `hybrid_retrieval/`：`HybridRetrieval(*, embedding, vector_store, sparse_search=None)`，入口 `search(query, *, top_k=10, filters=None, weights=None, fetch_k=50) -> list[ScoredDoc]`。**检索全流程已实现**（稠密→稀疏→RRF k=60→三因子重排）。三因子从 `doc.metadata["importance"]` / `["recency"]` 读；`RerankWeights(relevance=0.6, recency=0.2, importance=0.2)`。稀疏为可注入回调 `SparseSearch`，不注入则退化纯稠密（仍可用）。
   - 这批（基础模块 MVP）已全部 commit（见 git log `5747ea5`~`2b88984`），21 个新测试全绿。

### 因此 Recall 的规划变化（推翻旧「二～五」）
- **旧「检索层 RRF+三因子重排自研」作废** → Recall **不再自研检索**，改为**调用 `HybridRetrieval.search`**。`Recall/retrieval/`、`Recall/storage/`、`Recall/embedding/` 三个空目录**不再自行实现**，改为组合基础模块。
- **`RecallDoc` 改造** → 索引层产出的文档要能喂给 `PgVectorStore`/`HybridRetrieval`，即最终要落成 `datatypes.VectorDoc`：业务字段（user_id/player_id/scene_id/chapter_id/turn_start/turn_end/**importance**/**recency**）放进 `VectorDoc.metadata`。当前 `Recall/domain/documents.py` 的 `RecallDoc` 是重构前的独立 dataclass，需要一个到 `VectorDoc` 的映射（继承/组合/转换函数，实现时定）。
- **`_tenant_prefix` 去重** → 当前 `scene_indexer.py` 里私有 `_tenant_prefix` 与 `datatypes.tenant_prefix` 重复，应改用 datatypes 的统一实现。
- **recency 因子** → 重排要读 `metadata["recency"]`。Recall 索引时按 `turn_end` 距当前 turn 计算并写入（衰减策略待定；也可由查询期动态算，实现时定）。

### 重新规划后的下一步待办（按顺序，均 TDD + 中文注释 + 按内容拆 commit 不 push）
1. **【已完成 commit 5d6873e】Recall 数据类型对齐 datatypes**：`scene_indexer` 三个 build 函数已改为返回 `VectorDoc`，业务字段（含 importance/recency）进 metadata，复用 `tenant_prefix`，删除重构前的 `Recall/domain`(RecallDoc)。22 测试全绿。
2. **【已完成，服务层 commit】Recall 存储/检索接线**：`Recall/service/RecallService` 依赖注入组合 embedding + VectorStore + HybridRetrieval。`index_completed_scenes(scenes, *, user_id, player_id)`（逐幕 build_scene_docs→embed→upsert）与 `query_recall(query, *, user_id, player_id)`（粗召回 scene_summary 定位幕→逐幕细召回 act_chunk，全程带租户 filters）。删除不再自研的 retrieval/storage/embedding 空目录。8 测试全绿。
3. **索引触发点【方案已推翻重定，2026-08-17】**：
   - **旧「存档时批量索引已结束未索引的 scene」作废**——调研（Explore）证明不可行：`HistoryItem` 无 scene_id、history 全局扁平且 scene 转换不重置，无法按 scene 精确切分；`memory.scene_memory` 只保留「当前幕」、随 HistoryManager 覆盖、chapter 转换时清空；PlotState 无 completed_scenes 列表。**旧幕的 history+SceneMemory 在事后（存档时）已被覆盖/清空，回溯不可行。**
   - **新方案：幕结束时即时索引**（用户 2026-08-17 拍板）。唯一能拿到「完整且未被覆盖的单幕 history+SceneMemory」的窗口 = `scene_finished` 刚翻 True 的当下。接入点：`web_session.apply_player_action`(:375-388) 与 `apply_player_action_streaming`(:401-428) 两条路径 advance 之后（还有 `_maybe_handle_player_intent_plan_unlocked` :474 工具路径）检测 `scene_finished`。取数：scene_id/chapter_id 取 `state["plot"]`；scene_memory 取 `state["memory"]["scene_memory"]`；history 用 scene_memory 的 `turn_range` 从全局 `state["history"]` 按 turn 区间筛出当前幕。
   - **embed+upsert 异步/后台**（用户拍板）：幕结束时只把单幕数据交给后台，不阻塞玩家交互（bge 编码耗时）。需处理线程安全/失败重试。
   - **防重复**：仍建独立 `recall_index_log` 表（player_id+scene_id 唯一键），即时索引成功后写日志；同一幕若被重复触发（如流式+工具路径都命中）靠它去重。schema 在 `Persistence/Models.py` + `mysql_schema.sql`。
4. **注册 `query_recall` 工具**（3 处链路，见下方「下一步待办·第三批」，仍然有效）。
5. **稀疏轨（已落地）**：给 HybridRetrieval 注入 `sparse_search` 回调；不注入则纯稠密也能跑通。实现为 `hybrid_retrieval/sparse/PgTrgmSparseSearch`（与向量库共用同表，读 text/meta 列）。**原方案 A（tsvector+GIN+zhparser）因本机无 zhparser 等中文分词扩展作废**，改用**已装好的 pg_trgm**：中文无空格，`word_similarity/similarity` 对「短查询 in 长文本」常给 0，故用 `ILIKE '%query%'` 子串做召回门槛（GIN + gin_trgm_ops 加速），`similarity` 做相对排序。稀疏回调现返回**完整 ScoredDoc**，`retriever.py` 已改为把「仅稀疏命中、稠密未取回」的 doc 补取进候选（原 line 69 的 skip 已修）。尚未在 web_session/组装层把该回调接进 RecallService 用的 HybridRetrieval——留待整体接线。

### 仍然有效的旧决策（未受影响）
- 云端多用户；MySQL 保留主存；本地 bge-small-zh；scene 结束/存档批量索引；双粒度分块（整幕摘要+行动片段）。
- 两条检索轨：物品/属性走 SQL（`query_inventory`），叙事走向量；物品**不进**向量库。
- doc_id 必须带租户前缀（致命坑，现由 `datatypes.tenant_prefix` 统一提供）。
- scene 层级说明（见「三」）、场景结束判定链路、工具注册 3 处链路（见「四·第三批」）。

---

## 一、总体目标

为文本游戏引擎构建一个 RAG「用户回忆系统」(用户回忆系统)：把历史剧情存入向量数据库，
让玩家能用自然语言查询「我经历过什么」「我拥有什么物品」，通过**混合索引**(向量 + 关键词/结构化)检索。

### 已锁定的场景假设(不要再改)
- **云端多用户**部署
- **MySQL 保留为主存储**，不动
- **独立 Redis Stack (RediSearch) 向量服务**
- **本地 bge-small-zh-v1.5** embedding(512 维)
- **scene 结束 / 存档时批量索引**(不在 beat 热路径内联)
- **双粒度分块**：整幕摘要 + 行动片段

### 关键设计原则
- **两条检索轨**：结构化事实(物品/属性)走 SQL(`query_inventory`/`query_player_status`)，
  叙事事件走向量库。**物品不进向量库**。
- **物品查询继续走 `query_inventory`**，RAG 只处理叙事回忆；意图路由靠 `PlayerIntentPlannerAgent`
  的 enum 天然区分「查物品」vs「查回忆」。

---

## 二、已完成(已 commit，未 push)

提交栈(main 分支，均为中文 commit message)：

| commit | 内容 |
|--------|------|
| `534dedc` | feat(recall): 回忆子系统索引层，双粒度文档(9 文件，17 测试全绿) |
| `522f962` | refactor(graph): beat 子图步骤改为 hook(与 RAG 无关，历史遗留改动) |
| `01c9696` | refactor(actor): actor_create_agent 拆分到 Actor 包(与 RAG 无关) |
| `f9f731f` | feat(stream): 整轮输出改为逐条事件流式推送(Phase 1，更早的会话) |

> 注意：`522f962` / `01c9696` 是当时工作区里遗留的、与 RAG 无关的重构，一并按内容拆分提交了。

### Recall 子系统当前结构(按职责分子包)
```
Recall/
├── __init__.py               # 统一出口
├── domain/documents.py       # RecallDoc 数据模型(frozen dataclass，中文字段说明)
├── indexing/scene_indexer.py # 双粒度分块(已完成)
├── retrieval/                # 检索层(空，下一步)
├── embedding/                # bge-small-zh(第二批，空)
└── storage/                  # Redis/RediSearch(第二批，空)
```

### 索引层已实现的契约(`Recall/indexing/scene_indexer.py`)
- `build_scene_summary_doc(scene_memory, *, scene_id, chapter_id, user_id, player_id) -> Optional[RecallDoc]`
  - 正文 = `SceneMemory.summary` + `key_events`
  - importance = 各 `compressed_blocks[].max_score` 的最大值
  - **空摘要返回 None**
- `build_act_chunk_docs(history, *, scene_id, chapter_id, user_id, player_id, chunk_size=4) -> list[RecallDoc]`
  - 每 `chunk_size` 条 history 合成一块，正文按「角色: content」逐行拼接
  - importance = 块内 `importance_score` 的**最大值**(与摘要口径一致)
  - **正文只用 `content`**(有依据：`content` 是引擎公认的完整文本表示，HistoryCompression 也只用它)
- `build_scene_docs(*, history, scene_memory, scene_id, chapter_id, user_id, player_id, chunk_size=4) -> list[RecallDoc]`
  - 索引层主入口，组合摘要 + 片段；摘要为 None 时只返回片段

### RecallDoc 字段(`Recall/domain/documents.py`)
`doc_id, doc_type(scene_summary|act_chunk), user_id, player_id, scene_id, chapter_id,
turn_start, turn_end, importance, text`

### Code Review 已修复的关键问题
1. **[HIGH] doc_id 加租户前缀** `u{user}:p{player}:{scene_id}:...`
   - 原因：`scene_id` 由 `chapter+序号` 拼成(见 `Graph/transition_payloads.py:43,82`)，
     **各玩家共用同一套**，不加前缀会导致跨用户 upsert 覆盖、数据丢失。这是最重要的发现。
2. [MED] 空摘要跳过(避免空文本向量化)
3. [MED] importance 用块内 max 而非 mean(避免单条高分被稀释)
4. [LOW] `turn_range` 兼容单回合形态 "12" → (12,12)

### 尚未处理(暂缓，接存储层时统一做)
- 脏数据静默降级为 (0,0) 时缺少日志/计数
- chunk 循环里 `int()/float()` 强转未做防御性 try(仅 `_parse_turn_range` 做了)

---

## 三、场景(scene)层级说明(易混淆，务必记住)

系统层级从小到大：
- **act**(一次行动) = 一条 history 记录 = `ResolvedActSchema`
- **turn**(一轮) = 玩家输入一次 → `resolve_story_turn`
- **beat**(节拍) = `run_beat_loop` 一次循环
- **scene**(场景/幕) = `runtime["scene_finished"]` 翻 True 才结束，**一个 scene 跨多轮对话**
- **chapter**(章节) = 玩家预设的 10 个大结构，含多个 scene

**scene ≠ 章节，也 ≠ 一轮对话。** 一个章节内部动态切成多个 scene(每个 scene 有独立
`exit_condition`/`must_happen`/`scene_goal`，见 `GameState.py:40-47`)。

### 场景结束判定链路(索引触发点的依据)
`should_end_scene`(每 act 由 LLM 输出解析，可被 `contextual_scene_handoffs.py:363-370` 强制)
→ scene_end 节点 `apply_scene_end_evaluation`(`Graph/nodes.py:565`)评估
→ `runtime["scene_finished"] = True`(带 `scene_end_evaluation.reason`)

`scene_finished` 是全系统唯一权威判据(`beat_subgraph.py:138`、web_session、
`transition_nodes.py:56/126-127` 都 gate 在它上面)。

---

## 四、下一步待办(按顺序)

### 第一批剩余：检索层 `Recall/retrieval/`(纯逻辑 + TDD，不碰 Redis/模型)
实现 **RRF 融合 + 三因子重排**：
- 输入：两个已排序的候选列表(稠密 KNN 结果、稀疏关键词结果) + 当前 turn
- **RRF 融合**(k=60)合并两个排名
- **三因子重排**：
  - `relevance` = RRF 分
  - `recency` = 用 `turn_end` 距当前 turn 的衰减
  - `importance` = RecallDoc.importance
- 输出：重排后的结果列表
- 先粗召回 `scene_summary` 定位，再在命中 scene 内细召回 `act_chunk`
- 建 `tests/test_recall_retrieval.py`(或 `test_recall_rrf.py`)先写测试

### 第二批：外部依赖接入(需要先确认部署)
- `Recall/embedding/`：本地 bge-small-zh-v1.5 加载 + `encode`(带 batch)，依赖注入便于测试
- `Recall/storage/`：Redis 连接 + `FT.CREATE`(HNSW 512 COSINE + TAG user_id/player_id + TEXT)
  + upsert + KNN/TEXT 检索。开 AOF 持久化
- **需要用户确认**：Redis 是否部署好、bge 模型下载路径

### 第三批：编排 + 接线
- `Recall/RecallService.py`(或 `Recall/service/`)：`index_completed_scenes()` / `query_recall()`
- **索引触发点**：挂到 `web_session.save_player_session`(存档时批量索引已结束但未索引的 scene)
  - 需要在 MySQL 加一列 `indexed` 或建 `recall_index_log` 表，防重复索引
- **注册 `query_recall` 工具**(3 处链路，参照 `query_inventory`)：
  1. `ToolSkillRegistry.py`(:88 query_inventory / :218 query_story_memory)加 "query_recall"
  2. `PlayerControl/PlayerCommandTools.py:190` 参照 `_query_inventory` 加 `_query_recall` 方法
     (getattr 自动分发，`:150`)
  3. enum 自动进 `PLAYER_TOOL_NAMES`(`:37`)和 `PlayerIntentPlannerAgent.py:55`

---

## 五、Redis Stack / RediSearch 注意点
- 内存数据库，持久化靠 RDB/AOF(用 AOF 防重启丢向量)
- RRF **不内置**，需在应用层实现(所以放检索层做)
- 需要 `redis/redis-stack` 镜像(不是普通 redis)

---

## 六、关键数据结构参考(来自 History/GameMemory.py)
- `HistoryItem`: `{turn, actor(可为None=旁白), mode, content, spoken_text?, nonverbal_action?, message_kind?, tool_name?}`
- `ScoredHistoryItem` 追加：`importance_score, importance_bucket, score_reason`
- `SceneMemory`: `{turn_range(如"10-15"), summary, key_events, compressed_blocks, ...}`
- `CompressedHistoryBlock`: `{turn_start, turn_end, avg_score, max_score, ...}`
- 物品：`CharacterProfile.BackpackItem = {id,name,quantity}`；
  `Store.query_inventory` 返回 `{item_id,item_name,quantity,icon}`(字段名不一致，但物品不进 RAG，无影响)

---

## 七、工作约定(用户偏好)
- **全程中文回复 + 中文函数注释/docstring**
- **按内容拆分 commit**，中文 commit message，**不 push**
- **代码按模块分子包**，不堆在一个文件夹
- **TDD**：先写测试(红)，再实现(绿)
- 新文件放 `/src`、`/tests`、`/docs` 等，不放根目录
