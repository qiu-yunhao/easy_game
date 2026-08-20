# 异步记忆压缩 + 长期 RAG 记忆 设计

日期：2026-08-20
状态：已通过 brainstorming 评审，待写实现计划

## 背景与动机

单次玩家行动实测耗时约 16–28s。埋点定位到 `narration.after` 上注册的记忆刷新 hook（`_refresh_history` → `HistoryManager.build_memory`）单次约 **4.3s**，且因 `session_bootstrap.py:388` 把 `compression_trigger_size` 误设为 `1`（默认应为 30），该 hook 几乎每轮都触发全量压缩，成为关键路径上的稳定开销。

`build_memory` 实际做两类事：

- **慢 / 可延迟**：压缩——对未压缩历史打分（1 次 LLM）+ 分块摘要（每个 mid/low 块 1 次 LLM）。
- **快 / 紧急**：从**已有** `compressed_blocks` 派生各 Agent 记忆视图（`build_scene_memory_from_blocks` → playwright/director/scheduler），叙事当轮就要读。

关键洞察：派生视图依赖的是**已存在**的压缩块，不是这一轮新产出的块。因此派生可以同步、快速完成，而压缩挪到后台异步执行，下一轮 join。

## 目标记忆形态（用户锁定）

- 短期记忆队列长度 **45**（`summary_horizon_turns = 45`，可见窗口）。
- 未压缩历史超过 **30** 触发压缩（`compression_trigger_size = 30`）。
- 压缩时选**最远的相关事件**（最老的、滑出/接近滑出窗口的块）。
- 压缩完成后，把对应原始事件**移出短期记忆**——但**仅在后台成功后**才移出。
- 压缩过的记忆作为**长期记忆**存入 RAG 向量库（pgvector）。
- 长期记忆既**写**（压缩块 → pgvector）也**查**（召回旧块，作为一等记忆注入各 Agent 视图）。

## 当前记忆结构（核对后的现状 vs 目标态）

短期记忆是**一份全量 + 一个游标**，不是两个并列队列：

- **原始消息**：`state["history"]`——全部 `HistoryItem`，现状**永不删除**（全量留存）。
- **压缩块**：`state["memory"]["scene_memory"]["compressed_blocks"]`（`CompressedHistoryBlock` 列表）。
- **游标**：`state["memory"]["last_compressed_turn"]`——`turn > last_compressed_turn` 即「未压缩」。

现状与目标态的差异（本设计要补的行为）：

| 行为 | 现状 | 目标态（本设计） |
|------|------|------------------|
| 未压缩数 ≥30 触发压缩 | 有（但 trigger 误设为 1） | 修正为 30 |
| 压缩结果落 `compressed_blocks` | 有 | 保持 |
| 压缩后删除 `history` 已压缩原始项 | **无**（原始项原封留着） | **新增**：压缩成功回调删除 `turn ≤ new_last_compressed_turn` 的 history 项 |
| 压缩块写 RAG | **无**（只进内存） | **新增**：同时 upsert pgvector |
| 块内 `raw_items` 副本 | 保留 | **保留**（high 价值块靠它留逐字原文，删 history 不清块内副本） |

因此用户描述的「原始满 30 压缩、压缩后移出原始、写入 RAG」是**目标态**，其中「移出原始」和「写 RAG」是当前代码没有、本次新增的。

## 已确认的范围决策

| 决策点 | 选择 |
|--------|------|
| 异步粒度 | 跨轮异步，下一轮 join |
| 移出短期时机 | 后台压缩**成功后**才移出 |
| join 方式 | 无超时阻塞 join |
| 本次范围 | 同时接写入（压缩→pgvector）与查询（召回→注入） |
| 长期召回注入位置 | 作为一等记忆流经 `build_*_memory`，非 scene_memory 上的浮动字段 |
| 短期/长期去重 | **查询时限定 turn 范围**（`turn < 可见窗口下界`），源头不相交，不写专门去重代码 |

## 架构总览

```
玩家行动
  │
  ├─ 当轮同步：
  │   ├─ (轮首) join 上一轮后台压缩结果 → 合并 pending_result（成功则移出已压缩的原始 history）
  │   ├─ 长期召回 query_recall(turn < window_start)  ← 只查滑出窗口的旧块（缓存）
  │   ├─ 派生 Agent 记忆视图（recalled_blocks + visible_blocks 合并）← 快，叙事读这个
  │   └─ MemoryRefreshPolicy 判定是否需要压缩 → 若需要，snapshot enqueue 到后台
  │
  └─ 后台（AsyncMemoryCompactor 单守护线程）：
      对 snapshot 打分 + 摘要 → 生成新压缩块 → upsert pgvector（doc_type="memory_block"）
      → 成功则把结果放入 pending_result（下一轮轮首 join 取走）；失败仅记日志，可重试
```

## 单元 1：MemoryRefreshPolicy（纯函数）

把「是否/如何刷新记忆」的判定从副作用里剥离成纯函数，便于测试与复用。

- 输入：`GameState`（读 `runtime.turn_index`、`memory.last_compressed_turn`、`scene_finished`、未压缩历史数量）。
- 输出：一个决策对象，描述：
  - `should_compress: bool`
  - `compress_all: bool`（幕结束时全量 flush）
  - 待压缩的目标区间（最远的未压缩项，即最老的一批）。
- 规则：
  - 开场（turn==0 且无块）：不压缩（沿用现有 opening 特判，避免开场额外 LLM）。
  - 未压缩数 ≥ `compression_trigger_size(30)`：压缩最远的一批。
  - `scene_finished`：全量 flush（把所有未压缩项压完）。
  - 其余：不压缩。
- 常量修正：`session_bootstrap.py:388` 的 `HistoryManager(compression_trigger_size=1)` 改回 `30`；`summary_horizon_turns` 设为 `45`。

## 单元 2：AsyncMemoryCompactor（仿 AsyncSceneIndexer）

复用 `Recall/service/async_indexer.py` 的模式：单守护线程、enqueue 非阻塞、join 同步点、幂等标记。

- `enqueue(snapshot)`：轮末非阻塞投递当前状态快照（含待压缩项 + 打分/摘要所需上下文）。快照隔离：后台只读快照，不碰活 state。
- 后台 `_process`：打分（1 LLM）+ 分块摘要（每 mid/low 块 1 LLM）→ 生成 `CompressedHistoryBlock` → `build_block_docs` → upsert pgvector。
- 成功：把 `(new_blocks, new_last_compressed_turn)` 放入 `pending_result` 槽（带锁）。失败：记日志，不写 pending，可下轮重试。
- `join()`：无超时阻塞，轮首调用；取走 `pending_result`，合并进活 state 的 `compressed_blocks`，推进 `last_compressed_turn`，并**此时**执行移出回调——从 `state["history"]` 删除 `turn ≤ new_last_compressed_turn` 的已压缩原始项（成功后才移出）。**块内 `raw_items` 副本保留**：high 价值块（`kind="raw"`）靠它保留逐字原文，只删 `history` 队列、不清块内副本。

## 单元 3：build_block_docs（压缩块 → VectorDoc）

- 把 `CompressedHistoryBlock` 映射为 `VectorDoc`，`doc_type="memory_block"`（与现有 `scene_summary`/`act_chunk` 隔离，互不干扰）。
- 幂等 `doc_id`：由 tenant（user_id/player_id）+ 块 turn 区间派生，重复 upsert 覆盖同一 id，不产生副本。
- 与场景级索引（`index_completed_scenes`）并行存在，各用各的 doc_type。

## 单元 4：长期召回注入（一等记忆）

改 `build_scene_memory_from_blocks` 的签名，让长期召回块与可见块合并成同一份输入，流经全部 `infer_*` 与下游 playwright/director/scheduler 视图。

- 新签名：`build_scene_memory_from_blocks(state, blocks, summary_horizon_turns, *, recalled_blocks=())`
- 内部：`memory_blocks = list(recalled_blocks) + get_visible_blocks(...)`，按 turn 排序（长期在前=更老，可见在后=更近），再喂给所有 infer。
- 召回来源：查询串由 `scene.focus_character` + 最近 history 构成；结果缓存（同一轮多视图复用，避免重复查库）。
- **turn 范围边界（去重的根）**：`query_recall` 只召回 `turn_end < window_start` 的块，其中 `window_start = max(0, turn_index - summary_horizon_turns + 1)`（与 `get_visible_blocks` 完全一致）。因此召回块永远严格早于可见窗口，两层天然不相交，无需专门去重代码。
- 召回块形状即 `CompressedHistoryBlock`（长期库存的就是压缩块），与可见块同构，可直接混合。

## 数据流：短期 vs 长期的分区

- **短期（可见窗口）**：最近 45 轮内的块，由活 state 直接提供，永远权威优先。
- **长期（RAG 召回）**：只贡献已滑出 45 轮窗口的旧块——把短期已「忘掉」的相关旧事重新捞回。
- 重叠区间永远短期赢（短期是当前 state 的权威，长期只是其持久化副本）。查询 turn 上界保证源头不重叠。

## 错误处理

- 后台压缩失败：仅记日志，不写 pending_result，原始 history 不移出短期，下轮可重试（幂等 doc_id 保证重试安全）。
- pgvector 不可用 / 召回失败：召回返回空，派生视图退化为仅用可见块（现有行为），不阻断叙事。
- join 无超时阻塞：若后台异常卡死需另行监控；本设计接受阻塞语义（用户已确认）。

## 测试策略

- MemoryRefreshPolicy：纯函数单测，覆盖 opening / <30 / ≥30 / scene_finished 四类。
- AsyncMemoryCompactor：enqueue→join 往返；成功后 pending 合并 + 原始项移出；失败不移出 + 可重试；快照隔离（后台不改活 state）。
- build_block_docs：幂等 doc_id（重复 upsert 不增副本）；doc_type 隔离。
- 召回注入：`turn_end < window_start` 边界（召回块严格早于可见窗口，验证不重叠）；召回为空时退化；多视图共用缓存只查一次。
- 端到端：关键路径不再每轮承担 4.3s 压缩；下一轮正确 join 上一轮结果。

## 影响面 / 需改动的已有点

- `session_bootstrap.py:388`：`compression_trigger_size` 1 → 30；`summary_horizon_turns` → 45。
- `session_bootstrap.py:register_default_hooks`：`_refresh_history` 拆为「同步派生 + 后台 enqueue」，并在轮首加入 join。
- `History/HistoryInference.py:build_scene_memory_from_blocks`：加 `recalled_blocks` 参数与合并逻辑。
- 新增 AsyncMemoryCompactor（仿 async_indexer）、build_block_docs、MemoryRefreshPolicy。
- 复用 `Recall/service` 现有 pgvector_store / query_recall（新增 doc_type="memory_block" 分支）。

## 未决 / 后续

- 更新项目记忆决策（原「只索引已结束的幕」）以记录：新增块级索引（与场景级并行，doc_type 隔离）。
