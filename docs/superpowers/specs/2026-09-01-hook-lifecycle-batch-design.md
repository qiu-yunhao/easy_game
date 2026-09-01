# Hook 生命周期统一与响应组批处理设计

> 日期：2026-09-01  
> 状态：设计已确认，等待规格审阅  
> 范围：第一期仅修复 Hook 生命周期与并行组提交语义；第二期另行设计子图状态隔离和依赖拆分。

## 背景

当前串行 Beat 通过 `HookableNode` 执行 `before → run → after`，但并行响应组、强制旁白 flush 和 director wrap-up 直接调用裸节点函数。由此产生以下分叉：

- 并行组跳过 actor、narration、cultivation 和 scene-end Hook；默认的 contextual scene progression 也不会执行。
- flush 跳过 `narration.after`，wrap-up 跳过 `director_wrap_up.before/after`。
- `register_default_hooks(deps)` 可被重复调用，从而重复提交历史和重复刷新记忆。
- 并行组包含多条行动，而现有 `runtime.resolved_act` 只能表达一条行动；若让组只触发一次 `actor.after`，默认 history Hook 无法正确消费整组结果。

本期目标是在不引入新的子图 State 框架的前提下，让所有 Beat 路径遵循相同的 Hook 生命周期，并把并行组定义为一个确定顺序、一次提交的 actor 批次。

## 目标与非目标

### 目标

1. 固定并兑现 12 个 Hook 点：5 个主节点各自的 `before/after`，以及 `director_wrap_up.before/after`。
2. 串行、并行组、flush 和 wrap-up 不再绕开 Hookable 生命周期。
3. 并行响应组只触发一次 `actor.before` 和一次 `actor.after`；所有角色仍从同一输入快照生成。
4. 默认 actor 后置处理一次提交整组行动，随后只推进一次 contextual scene。
5. 默认 Hook 注册静默幂等，并保留已注册的自定义 Hook。
6. Hook 失败必须终止当前 Beat 并保留原异常，不吞异常、不继续后续节点。

### 非目标

- 不在本期为 Story Authoring、Chapter Preparation 或 Beat 建立独立的 LangGraph State。
- 不在本期拆分 `GraphDependencies` 或引入新的 DI/factory 框架。
- 不承诺跨进程重试下的 exactly-once 副作用；本期没有 checkpoint/恢复协议。
- 不修改调度策略、旁白批处理策略或并行角色的生成快照语义。

## 状态与批次模型

`RuntimeState` 新增两个仅在 actor 生命周期内有效的字段：

```python
class ActorFailure(TypedDict):
    actor_id: str
    error: str

resolved_acts: list[ResolvedAct]
pending_actor_failures: list[ActorFailure]
```

- 串行 `ActorNode.run` 将生成的一条行动写入 `resolved_acts`；并行 `ActorGroupNode.run` 按 scheduler 的组顺序写入全部成功行动。
- `resolved_act` 保留为兼容字段，始终指向本批最后一条成功行动；旁白、修炼和场景结束逻辑继续读取它。
- `pending_actor_failures` 保存并行生成失败的角色和错误文本，使历史系统事件与成功行动在同一个默认 actor 后置提交中写入，顺序保持为“所有成功行动，再失败提示”。
- 默认 actor 提交 Hook 消费批次，但不在 Hook 链内部清空它；这允许链上自定义 Hook 观察完整批次。
- 只有当 `actor.after` 的全部 Hook 成功时，actor 节点 finalize 才清空两个瞬态字段。若任一 Hook 失败，异常向上抛出且字段保留，便于诊断；运行器不自动重试该 state，也不回滚已经成功运行的 Hook 副作用。

为保持领域边界，`Actor/ActorRuntime.py` 新增批次提交函数，按既有 `apply_resolved_act` 的顺序更新 history、角色运行时状态、关系和 plot flags。`Graph/beat_group.py` 只负责并行生成、确定顺序和组级终止标志合并，不直接提交 history。

## Hook 契约

允许的 Hook 点是：

```text
director_lead_in.before / director_lead_in.after
actor.before / actor.after
narration.before / narration.after
cultivation_progress.before / cultivation_progress.after
scene_end.before / scene_end.after
director_wrap_up.before / director_wrap_up.after
```

`HookRegistry.register()` 必须拒绝未知 Hook 点，防止字符串拼写错误静默失效。Hook 仍使用 `GameState -> GameState` 签名；本期以约定约束 Hook 不改变控制流，第二期再以局部 State/patch 约束可写字段。

同一 Hook 点按注册顺序执行。Hook 或节点抛出的异常原样传播；after Hook 不会在对应 run 失败后执行。Hook 失败后当前 Beat 不再运行后续节点、flush 或 wrap-up。

## 生命周期实现

### 串行路径

保留现有五个 `HookableNode`：

```text
DirectorLeadInNode → ActorNode → NarrationNode → CultivationProgressNode → SceneEndNode
```

`ActorNode` 在 `run` 中建立单元素批次，在 `after` 链全部成功后清理瞬态批次字段。

### 并行响应组

新增 `ActorGroupNode`，其语义为一个逻辑 actor 步骤：

```text
DirectorLeadInNode.as_step()
→ ActorGroupNode.as_step()
→ NarrationNode.as_step()
→ CultivationProgressNode.as_step()
→ SceneEndNode.as_step()
```

`ActorGroupNode` 先运行 `actor.before`，再并行生成全部角色行动；生成阶段中的每个角色读取同一组起始快照。生成结束后，它将结果整理为批次并合并组级 flags，随后只执行一次 `actor.after`。因此默认 history 提交和 contextual progression 都只运行一次，且后者必定发生在整组历史写入之后。

### 收尾路径

- `flush_step` 改为 `NarrationNode(force_flush=True).as_step()`。
- `wrap_step` 改为 `DirectorWrapUpNode.as_step()`。

这两条路径也具备完整 Hook 语义；`DirectorWrapUpNode` 不再是未使用的伪扩展点。

## 默认 Hook 与注册生命周期

`GraphDependencies` 增加 `default_hooks_registered: bool = False`。`register_default_hooks(deps)` 的第一步检查该值：已注册时直接返回，不清空 registry，也不影响自定义 Hook。

首次注册顺序固定如下：

1. `actor.after`：批次 history/角色/关系提交。
2. `actor.after`：contextual scene progression。
3. `narration.after`：异步历史/记忆刷新。

完成注册后设置 `default_hooks_registered = True`。bootstrap 是默认注册的唯一生产调用方；测试和嵌入式装配可安全重复调用。

## 文件边界

| 文件 | 责任 |
| --- | --- |
| `GameState.py` | 声明 actor 批次和失败载荷的瞬态 runtime 字段。 |
| `Actor/ActorRuntime.py` | 按确定顺序提交行动批次，复用既有单行动领域更新。 |
| `Graph/beat_group.py` | 并行生成、结果排序、失败收集和组级 flags 合并。 |
| `Graph/beat_nodes.py` | 串行 actor、组级 actor 及 finalize 清理；复用 HookableNode。 |
| `Graph/dialogue_nodes.py` | 选择串行或组级节点；所有路径经 `.as_step()`。 |
| `Graph/hooks.py` | 固定 Hook 点注册校验与顺序执行。 |
| `Graph/dependencies.py` | 默认 Hook 注册状态。 |
| `session_bootstrap.py` | 幂等注册默认批次提交、场景推进和记忆刷新 Hook。 |

## 验收测试

1. 串行路径按顺序触发 12 个 Hook 点；强制 flush 和 wrap-up 的点也出现。
2. 并行组按顺序触发同一套生命周期，其中 `actor.before/after` 各仅一次。
3. 并行组内所有角色仍观察到同一 history 起始快照。
4. 并行组成功行动按 scheduler 组顺序写 history；失败提示保持既有相对顺序。
5. actor 批次提交后 contextual scene progression 恰好执行一次，并发生在所有行动写 history 之后。
6. 重复调用 `register_default_hooks` 后，`actor.after` 仍有两个默认 Hook，`narration.after` 仍有一个。
7. 注册未知 Hook 点抛出明确异常。
8. run 或 Hook 抛错时，后续 Hook/节点/flush/wrap 不执行，异常向上保留。
9. 现有串行、并行组、旁白和 beat-resolution 回归测试继续通过。

## 第二期预留

第二期以本期明确的批次边界为基础，建立子图局部 State 和白名单 patch 合并：Story Authoring、Chapter Preparation 与 Beat Control 仅接收其所需状态切片，并通过显式 adapter 合并回 `GameState`。同时将 `GraphDependencies` 拆分为面向节点的窄依赖视图，消除 `beat_nodes` 与 `dialogue_nodes` 的循环依赖。
