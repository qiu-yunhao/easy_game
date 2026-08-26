# 旁白 Token 级流式打字机 — 设计文档

- 日期：2026-08-26
- 分支：feat/auto-mode-l1-flag
- 范围：easy_game Web 模式的对话输出体验

## 背景与问题

当前 Web 前端一轮玩家动作后，多个角色的对话要等**整轮全部算完**才成块出现，玩家等待期间无反应。

诊断结论（已核实数据流）：

- 后端 `apply_player_action_streaming` → `resolve_story_turn(..., on_event)` → `run_beat_loop`
  已经在**每条 history entry 提交时**通过 SSE `entry` 事件逐条推送；前端 `chat.js` 的
  `onEntry` 收到即上屏。即“逐角色即时上屏”已实现。
- 真正瓶颈：每条 entry 是在该角色的 LLM 调用**完全返回后**才 emit。`BaseAgent._command_inner`
  用 `client.chat.completions.create(**params)` 一次性拿完整响应（无 `stream=True`），
  所以每个角色整段文字要等几秒才“啪”地整块出现，累加成长时间无反应。

## 目标

- **旁白**（`NarratorAgent`，纯文本输出）：token 级流式打字机，玩家读到的旁白文字逐段蹦出。
- **其他所有输出**（角色 `ResolvedAct`、导演调度等结构化 JSON）：生成完**整条立刻显示**，
  沿用现有 `entry` 事件，不做逐字。

非目标：结构化 JSON 的逐 token 展示；前端假打字机动画；对 heuristic 模式的改动。

## 范围界定：为什么只有旁白走流式

beat 循环里 Agent 输出分两类：

- **纯文本**（`response_format=None`）：只有 `NarratorAgent`。这是玩家连续阅读的文字，适合打字机。
- **结构化 JSON**（`ResolvedAct` / 导演调度）：`ActorAgent` / `L1ActorAgent` / `DirectorAgent`。
  角色“台词”先出 JSON，再由 Narrator 转成旁白文本。逐 token 吐 JSON 无展示意义，且会
  牵连其 fallback/repair 容错逻辑，保持整条 emit。

结论：打字机作用在**旁白文本**上；玩家实际逐字读到的正是旁白。结构化决策步骤走现有整条 `entry`
事件（通常很快，非逐字阅读内容）。

## 分层设计

数据流（新增 token 旁路，与现有 entry 通道并存）：

```
NarratorAgent.command(on_token=cb)
   ↑ narration 节点注入
narration 节点从透传下来的 token sink 取回调
   ↑ resolve_story_turn / run_beat_loop 透传 token sink
web_session.apply_player_action_streaming 把 SSE 接成 token sink
   ↑
web_server 新增 SSE 事件 token {entry_id, delta}（与 entry/done/error 并存）
   ↑
前端 chat.js：onToken 按 entry_id 定位旁白气泡，逐段 append（打字机）
```

### 第 1 层：BaseAgent（✅ 已完成）

- `command(instruction, history, response_format, on_token=None)` 与
  `_command_inner(..., on_token=None)` 新增可选 `on_token` 回调。
- 仅当 `response_format is None and on_token is not None` 时走流式：`stream=True`，
  逐 `chunk.choices[0].delta.content` 回调并累积，最终返回完整 content 字符串。
- **返回值与非流式完全一致**；不传 `on_token` 时行为不变（向后兼容，现有调用/测试不受影响）。
- 结构化 JSON 路径（含 fallback/repair）不改。
- 已加单测 `tests/test_base_agent_streaming.py`：逐 token 回调、无回调不流式、结构化不流式。

### 第 2 层：token sink 透传到旁白（待实施）

- 一个 `token sink` 回调（签名近似 `Callable[[entry_id, delta], None]` 或分步注入）由
  `apply_player_action_streaming` 经 `resolve_story_turn` → `run_beat_loop` → narration 节点透传。
- narration 节点在调用 `NarratorAgent.command` 时注入 `on_token`，把 delta 关联到即将提交的
  旁白 entry（需要一个稳定的 `entry_id` 关联流式片段与最终 entry）。
- 结构化 Agent 的调用**不接** `on_token`。
- 无 sink（如非 Web 入口、heuristic）时该路径为空操作，行为不变。

### 第 3 层：SSE token 事件（待实施）

- `apply_player_action_streaming` 把 token sink 接到 SSE 输出。
- `web_server` 新增 `token` 事件：`event: token` + `data: {entry_id, delta}`，与现有
  `entry` / `done` / `error` 并存，复用 `_write_sse_event`。

### 第 4 层：前端打字机（待实施）

- `streamAction` 的 `dispatch` 处理新的 `token` 事件类型。
- 旁白气泡按 `entry_id` 定位（首个 token 到达时若气泡不存在则创建占位气泡），逐段 append delta。
- 最终 `entry`（完整旁白）或 `done` 到达时对账为完整文本，避免流式片段与最终文本不一致。

## entry_id 关联策略

流式 token 与最终 history entry 需要一个稳定标识关联。实现计划阶段需确认：
history entry 是否已有稳定 id（若无，需在提交旁白 entry 时生成并同时用于 token 事件），
保证前端能把 `token{entry_id, delta}` 追加到正确气泡，并在最终 `entry` 到达时对账。

## 错误处理与降级

- 流式请求中途连接中断：沿用 `_write_sse_event` 已有的 BrokenPipe/ConnectionReset 兜底。
- LLM 流式异常：与现有 `error` 事件路径一致；旁白生成失败仍可回退启发式旁白（保持现有兜底）。
- token 通道是**旁路**：即使前端不识别 `token` 事件，最终 `entry` 仍带完整旁白，功能不退化。

## 测试策略

- 单元（已完成）：BaseAgent 流式回调 / 非流式 / 结构化不流式。
- 单元（待）：narration 节点注入 on_token 且结构化 Agent 不注入；token sink 透传。
- 集成（待）：`apply_player_action_streaming` 产生 token 事件序列，最终 entry 文本 == token 拼接。
- 人工验证：起服务，旁白逐字打出、角色结构化输出整条即显；跑相关测试确认无回归。

## 影响面

改动文件（预估）：`BaseAgent.py`（已改）、Graph 中 narration/beat/builder 透传层、
`web_session.py`、`web_server.py`、`frontend/js/pages/chat.js`。不改 heuristic 路径、
不改结构化 Agent、不改现有 `entry`/`done`/`error` 事件语义。
