# 分片并行角色响应（Parallel Beat Response Groups）设计

日期：2026-08-11
状态：决策已定稿，待用户过目

## 1. 背景与目标

一轮对话约 2min。经代码确认，主要耗时来自 `run_beat_loop`
（`Graph/beat_subgraph.py`）里对 `pending_beat_actors` 的**严格串行**处理：每个角色
一次阻塞、非流式的 LLM 调用（`BaseAgent.command`，无 `stream=True`），N 个角色的
首字延迟 + 全量生成时间线性累加。

**目标**：在同一 beat 内，把"互相不需要接话"的角色打包成并行组，组内并发发起
`perform_turn`，把 N 段串行压缩成"分组数 × 每组最慢角色"，显著降低整轮总耗时。

**本次范围**：只做后端并行。前端保持一次性返回（`web_session.apply_player_action`
在锁内跑完整轮后 `serialize_state`），不引入 SSE / 流式。流式作为后续独立迭代。

**非目标**：不改角色记忆隔离语义、不改 narration 汇总逻辑、不动前端。

## 2. 关键约束：为什么现在是串行

`Actor/ActorFormatter.py:71` 给每个角色喂 `recent_history = state["history"][-8:]`。
`run_beat_loop` 每个角色行动后经 `history_commit_node`（`apply_resolved_act`）把发言
写入 `state["history"]`。因此**后发言角色能看见先发言角色本轮刚说的话**——这是一个
真实的轮内依赖，串行由此而来（不是疏忽）。

分片并行的本质取舍：**用"同组内对话连贯性"换"延迟下降"**。同组并行的角色只能看到
"本组开始前"的 history，组内互相听不见本轮发言。这与"角色记忆隔离"的初衷一致，
代价可控——只要 Director 把"需要接前者话"的角色放进后续组即可。

## 3. 分片策略：Director 语义分组（已定）

由 Director 判断哪些角色"独立开口"（可并行）、哪些"回应前者"（必须在后续组），
而非按 tier 猜测。

### 3.1 Director schema 扩展

在 `Director/DirectorSchema.py` 的 `who_should_respond`（保持不变，仍是有序 actor id
列表）之外，新增一个可选字段 `response_groups`：

```json
"response_groups": {
  "type": "array",
  "items": {
    "type": "array",
    "items": {"type": "string"}
  }
}
```

- `response_groups` 是"组的有序列表"，每组是一个 actor id 列表。
- 组间语义：**串行**——后一组能看见前一组本轮的发言。
- 组内语义：**并行**——同组角色各自基于"本组开始时的 state"独立发言，互不预读。
- 约束（写进 `DIRECTOR_SYSTEM_PROMPT`）：
  - 把"独立起头、彼此不接话"的角色放同一组。
  - 把"明确回应/反驳前一个角色"的角色放到后续组。
  - `focus_character` 若承担对话中心，倾向单独成组或置于首组。
  - 每组人数建议 ≤ 3（避免同组过多角色互相失聪）。
  - `response_groups` 展平后必须等于 `who_should_respond`（同一集合、同样顺序）。

### 3.2 归一化与降级（`Director/DirectorRuntime.py`）

`normalize_director_brief` 新增对 `response_groups` 的处理，写入 `DirectorBrief`：

1. 过滤：只保留 `future_on_stage` 内的 actor id，去重。
2. 一致性校验：展平后的集合必须与归一化后的 `who_should_respond` 一致。
   - 若不一致或字段缺失/为空 → **降级为全串行**：每个 actor 单独一组
     （`[[a], [b], [c]]`），行为与今天完全等价。这是安全兜底。
3. 结果连同 `pending_beat_actors` 一起，落到 runtime 的新字段
   `pending_response_groups`（见 §5）。

### 3.3 heuristic 模式

`_prioritize_active_actors` 产出的 fallback 顺序无法判断语义依赖 →
heuristic 模式下 `response_groups` 一律降级为全串行（每人一组），保持现状。

## 4. 组内并行执行

### 4.1 执行位置

改造 `run_beat_loop`（`Graph/beat_subgraph.py`）：由"每次取一个 actor"改为
"每次取一个组"。组内用 `ThreadPoolExecutor` 并发（`Graph/builder.py:107` 已用同款，
线程池对 IO-bound 的 LLM HTTP 调用足够；每个 agent 有独立 OpenAI client）。

### 4.2 单组执行流程

对一个组 `G = [a1, a2, a3]`（`group_start_state` = 进入本组时的 state）：

```
1. 并发提交：对每个 ai，用 group_start_state 复制出以 ai 为 next_act 的子 state，
   提交 perform_turn(ai) 到线程池。各自读同一份 group_start history，互不预读。
2. 收集：等待组内全部 future（带重试队列，见 §6）。
3. 回收（串行、确定性）：按 who_should_respond 原始顺序，对每个 ai 依次：
   - director_lead_in（如需，纯内存/或消费 brief 文本）
   - apply_resolved_act（写 history / 关系 / 情绪 / 记忆）
   - cultivation_progress
   - 冲突合并裁决（见 §5）
4. 组结束后：narration（沿用现有批量逻辑，组内多条一起进 narration_queue）。
5. scene_end 评估。
```

注意：并行的只是**第 1 步（LLM 生成）**。第 3 步 apply 是纯内存操作、很快，
严格按 Director 原始优先级顺序执行 → 保证 history 可读性与确定性。

### 4.3 director_lead_in / wrap_up 的处理

`director_lead_in_node` 目前在每个 actor 前消费一次 `lead_in_text`。并行后，一组只在
组首消费一次 lead_in（否则组内多次消费同一文本）。`wrap_up` 逻辑不变（仍在 beat 收束
或交还玩家时触发）。

## 5. 冲突合并规则

组内多角色并发产出，回收时可能互斥。规则：

### 5.1 终场标志仲裁（已定）

- **终场标志（`should_end_scene` / `should_end_chapter`）：仅最高优先级角色生效。**
  组内只有 `who_should_respond` 优先级最高的角色置 true 才终场；低优先级角色单方面
  置 true 会被忽略。避免支线角色单方面提前终结全组。

### 5.2 其余冲突规则（已定）

以下冲突在并行下才会出现，串行时天然被顺序化解，规则如下：

- **关系 / 情感变化（`relationship_update` / `emotion_update`）**：**叠加**而非覆盖。
  同组多人对目标 X 有增量时，按序累加各自 delta，保留每个角色的独立变化。
- **按原序列回收**：所有 apply 严格按 `who_should_respond` 顺序，确定性。
- **`revealed_facts`**：并集去重。
- **`triggered_plot_flags`**：同一 flag 被组内多人触发时，按优先级取首个非空值；
  不同 flag 取并集。
- **`allow_interrupt` / interrupt**：并行组内不支持打断语义。归一化时若某角色被标为
  interrupt，**把它单独拆成后续串行组**（组内禁用 interrupt）。
- **`target` 指向组内另一并行角色**：允许（apply 顺序化后目标已在 on_stage）；
  被指向者本轮不会感知到被 @（并行时未看见），可接受。

## 6. 失败处理：重试队列（已定）

组内每个角色的 `perform_turn` 用**重试队列，每任务重试 3 次**：

- 单个 actor 的 LLM 调用超时/报错 → 重新入队，最多重试 3 次（共 4 次尝试）。
- 超过 3 次仍失败 → 该 actor 标记为失败，收集其错误信息。
- **部分成功 + 报告（已定）**：成功的角色照常结算并 apply，失败的角色本轮缺席；
  向用户报告哪些 actor 失败及最后一次异常摘要。不因单个失败而中断整轮。

实现要点：
- 重试在**组内并发层**完成（每个 future 内部自带重试循环），不阻塞其他 actor。
- 回收时跳过失败的 actor（其在 history 中本轮无发言）。
- 错误信息聚合：记录失败的 actor id + 最后一次异常摘要，通过 state 或返回值上抛，
  由 `web_session` 转成用户可见提示（如追加一条 system 消息）。
- 边界：若**整组全部失败**，该组无任何发言，beat 继续推进后续组/收束；用户会看到
  失败提示。

## 7. 涉及改动的模块

| 模块 | 改动 |
|------|------|
| `Director/DirectorSchema.py` | 新增 `response_groups` 字段（可选） |
| `Director/DirectorAgent.py` | system prompt 增加分组规则说明 |
| `Director/DirectorRuntime.py` | `normalize_director_brief` 归一化 + 一致性降级 |
| `Director/DirectorBrief.py` | `DirectorBrief` TypedDict 增加 `response_groups` |
| `GameState.py` | runtime 增加 `pending_response_groups` |
| `Graph/beat_subgraph.py` | `run_beat_loop` 改为按组消费 + 组内 ThreadPool 并发 + 重试 |
| `Graph/nodes.py` | `apply_director_brief` 落 `pending_response_groups`；回收/合并逻辑 |
| `Graph/narration_nodes.py` | lead_in 每组只消费一次（微调） |

`Scheduler` 逐个 pop 的语义在"组内"仍适用（组内每个 actor 仍走 next_act 机制），
主要是把"取 1 个"改成"取 1 组"。

## 8. 测试计划

- **归一化降级**：`response_groups` 缺失/不一致/含非法 actor → 降级为全串行，
  行为与旧快照一致（回归）。
- **组内并行正确性**：mock LLM 客户端，验证同组角色读到的是同一份 group_start
  history（互不预读），组间后组能看到前组发言。
- **回收确定性**：固定 mock 输出，多次运行 apply 结果顺序/状态完全一致。
- **冲突合并**：构造同组双方 should_end_scene / 同目标 relationship_update /
  同 plot_flag，验证仲裁与叠加规则。
- **重试队列**：mock 前 N 次抛错，验证重试 3 次；第 4 次仍失败 → 该 actor 缺席、
  其余角色正常结算，且失败信息被上报（部分成功语义）。整组全失败 → beat 正常推进。
- **端到端**：agent-first mock pipeline 跑一轮多角色 beat，断言总调用数与分组数一致。

