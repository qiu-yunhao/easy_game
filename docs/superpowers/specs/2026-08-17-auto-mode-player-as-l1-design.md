# 自动模式:玩家角色升格 L1 Agent + 逐拍推进 — 设计方案

> 日期:2026-08-17
> 状态:待 review(仅设计,不含实现)
> 关联:承接阶段5 `2026-08-15-conversation-controller-extraction-design.md` 预留的
> `advance(stop_when=never_stop)` 自动推进接口;本轮把它接到 Web。

---

## 1. 背景与目标

### 1.1 起点
阶段1-5 已完成对话引擎解耦。`ConversationController.advance(state, *, stop_when, ...)`
已就位,`never_stop` 谓词已存在但尚无入口使用。当前 Web 只有"等玩家输入"这一种模式:
玩家回合必须由前端提交文本才能推进。

### 1.2 目标
新增**自动模式**:玩家开启后,轮到玩家角色行动时不再等输入,而是**把玩家角色临时
升格为 L1 Agent**(高叙事权重的核心角色),交给 L1 actor agent 自动演绎,一路逐拍推进;
玩家关闭开关后,下一个玩家回合恢复为正常等待输入。前端用"开关 + 逐拍推进(轮询)"控制。

### 1.3 已澄清的设计决策(用户拍板)
- **玩家动作来源**:自动模式下把玩家角色当成 L1 Agent 参与剧情(不是普通 NPC——NPC 叙事
  权重太低,也不是占位输入)。
- **前端交互**:开关 + 逐拍推进(轮询),非 SSE 流。
- **逐拍粒度**:每次轮询 `/api/auto/step` 推少量拍(3-5 拍)。
- **关闭后恢复**:关闭开关后还原 `enabled`/`agent_type`,当前正在推进的一批演完,
  到下一个玩家角色回合自然停下等待输入。

---

## 2. 现状盘点(已核对源码)

### 2.1 玩家回合的调度分叉(核心机制)
- `Graph/beat_subgraph.py:37-43` `is_player_turn(state)`:返回 True 的三个条件——
  `next_act 非空` ∧ `state["player"]["enabled"]` ∧ `next_act.actor == controlled_character`。
- `Graph/dialogue_nodes.py:159-175` `actor_node`:`is_player_turn` 为 True → 走
  `resolve_player_turn_state`(需玩家文本输入);否则 → `_resolve_agent_for_actor` 按
  `agent_type` 选 agent → `resolve_npc_turn_state`。
- `Graph/dialogue_nodes.py:131-156` `_resolve_agent_for_actor`:读 `profile.agent_type`,
  `"L1"` → `l1_actor_agent`,`"L2"` → `l2_actor_agent`,否则 → `actor_agent`。

**关键推论**:只要自动模式下把玩家 `player.enabled` 设 False,玩家角色的回合就会
自动流向 `_resolve_agent_for_actor`;再把玩家 profile 的 `agent_type` 设 `"L1"`,
就会选中 `l1_actor_agent`,由它按人设自动演绎玩家角色。两者都可在关闭时还原。

### 2.2 一次 resolve_story_turn = 一拍
- `Graph/builder.py:149-155` `resolve_story_turn` → `beat_resolution_node` →
  `run_beat_loop`。`run_beat_loop`(`beat_subgraph.py:102-166`)会跑完当前 beat 的
  所有剩余角色回合才返回。故 `advance` 循环里每执行一次 `resolve_story_turn` 即"一拍"。

### 2.3 advance 现状(为何需要 max_beats)
- `Graph/conversation_controller.py:81-121` `advance`:while 到 `max_hops`(默认 24)才
  `raise`;中途只在 `stop_when(state)` / `scene_finished` / `next_act is None` 时 return。
- 自动模式 `stop_when=never_stop` 永不触发,`advance` 会一直演到 `scene_finished` 或撞
  `max_hops` **抛错**——无法用它做"推 3-5 拍就正常返回"。因此需要给 `advance` 增加一个
  **拍数上限**参数,达到即正常返回(不抛错)。

### 2.4 玩家 profile
- `session_bootstrap.py:150-168` `build_player_profile` 不设 `agent_type`,经
  `_resolve_agent_type`(`CharacterProfile.py:148-158`)兜底为 `"actor"`(最低权重)。
- profile 存在 `CharacterRepository`(`deps.character_profiles`),`_resolve_agent_for_actor`
  从这里 `.get(actor_id)` 读。

### 2.5 Web 层
- `web_session.py:412-430` `apply_player_action`:锁 + 两次 `advance(stop_at_player_turn)`。
- `web_server.py:160-206` `_handle_post_api_request`:POST 路由分发。
- `frontend/app.js`(1794 行)+ `frontend/index.html`(382 行):vanilla JS SPA,
  `API.action = "/api/action"`;`streamAction` 走 SSE。

---

## 3. 设计

### 3.1 ConversationController.advance 增加 max_beats
```python
def advance(
    self,
    state,
    *,
    stop_when,
    max_hops: int = 24,
    max_beats: int | None = None,   # 新增:推进的拍数上限;达到即正常返回(不抛错)
    on_event=None,
) -> tuple[dict[str, Any], str]:
```
语义:
- `max_beats is None`(默认):行为与现状完全一致(现有 5 个调用点零改动)。
- `max_beats` 给定:每成功执行一次 `resolve_story_turn`(即一拍)后计数 +1;计数达到
  `max_beats` 时**正常返回** `(state, "已自动推进 {max_beats} 拍。")`,不抛错。
- `max_hops` 仍是硬安全阀:自动模式一批推进的拍数不会超过 `max_beats`,而
  `max_hops` 需 ≥ `max_beats`(否则先撞 hops 抛错)。故 `auto_step` 传
  `max_hops = max_beats + 1` 以上的安全余量,或直接把 `max_hops` 设足够大。

循环改动(最小):在 `resolve_story_turn` 后、`npc_acted = True` 附近插入拍计数与提前返回:
```python
        state = resolve_story_turn(state, self._deps, on_event)
        npc_acted = True
        beats_done += 1
        if max_beats is not None and beats_done >= max_beats:
            return state, f"已自动推进 {beats_done} 拍。"
```
(`beats_done = 0` 在循环前初始化。)

### 3.2 WebGameSession 自动模式状态
新增字段(在 `__init__`):
```python
self.auto_mode: bool = False
self._player_saved_agent_type: str | None = None  # 关闭时还原玩家 agent_type
```

`set_auto_mode`(加锁):
```python
def set_auto_mode(self, enabled: bool) -> dict[str, Any]:
    with self._lock:
        if enabled and not self.auto_mode:
            self._enable_auto_unlocked()
        elif not enabled and self.auto_mode:
            self._disable_auto_unlocked()
        return self.serialize_state()
```

`_enable_auto_unlocked`:
```python
def _enable_auto_unlocked(self) -> None:
    player_id = self.config.player_character
    profile = self.deps.character_profiles.get(player_id, {})
    self._player_saved_agent_type = str(profile.get("agent_type", "actor") or "actor")
    # 玩家角色升格 L1:改 profile.agent_type,使 _resolve_agent_for_actor 选 l1_actor_agent。
    self.deps.character_profiles.update_field(player_id, "agent_type", "L1")
    # 关掉玩家等待,让玩家回合自动流向 actor agent。
    self.state = {
        **self.state,
        "player": {**self.state["player"], "enabled": False},
    }
    self.auto_mode = True
    self.last_handoff_reason = "自动模式已开启：玩家角色临时升格为核心角色自动演绎。"
```

`_disable_auto_unlocked`:还原 `agent_type` 与 `player.enabled=True`;
`auto_mode=False`;`last_handoff_reason = "自动模式已关闭：下一个玩家回合恢复等待输入。"`。
> 注:`CharacterRepository.update_field(actor_id, field, value)` 是单一写入口(已核实:
> 直接写字段、不重归一化),用它改 `agent_type`;关闭时用同一入口还原原值。

`auto_step`(加锁):
```python
def auto_step(self, max_beats: int = 4) -> dict[str, Any]:
    with self._lock:
        if not self.story_initialized:
            raise RuntimeError("请先初始化场景，再启动自动推进。")
        if not self.auto_mode:
            raise RuntimeError("自动模式未开启。")
        if self.state["runtime"].get("scene_finished", False):
            raise RuntimeError("当前场景已经结束，请重置后继续。")
        self.state, self.last_handoff_reason = self._controller.advance(
            self.state,
            stop_when=never_stop,
            max_beats=max_beats,
            max_hops=max_beats + 8,   # 硬安全余量,防 group/补拍导致 hops 略多于 beats
        )
        self._maybe_index_finished_scene_unlocked()
        return self.serialize_state()
```
import 增补:`from Graph.conversation_controller import (..., never_stop)`。

### 3.3 web_server 路由
`_handle_post_api_request` 增两个分支:
```python
        if path == "/api/auto":
            enabled = bool(payload.get("enabled", False))
            return HTTPStatus.OK, self.server.session.set_auto_mode(enabled)
        if path == "/api/auto/step":
            max_beats = payload.get("max_beats", 4)
            try:
                max_beats = int(max_beats)
            except (TypeError, ValueError):
                raise RuntimeError("`max_beats` 必须是整数。") from None
            max_beats = max(1, min(8, max_beats))   # 收窄 1~8,防滥用
            return HTTPStatus.OK, self.server.session.auto_step(max_beats=max_beats)
```

### 3.4 前端(frontend/app.js + index.html)
- `API` 表加 `auto: "/api/auto"`、`autoStep: "/api/auto/step"`。
- `index.html`:在动作输入区附近加一个"自动"开关(checkbox 或 toggle button)+ 状态提示。
- `app.js`:
  - `autoTimer`(setInterval 句柄)、`autoBusy`(防重入)。
  - 开关打开 → `POST /api/auto {enabled:true}` → 渲染 state → 启动
    `setInterval(pollAutoStep, ~1500ms)`。
  - `pollAutoStep`:若 `autoBusy` 或 `scene_finished` 则跳过;`autoBusy=true`;
    `POST /api/auto/step {max_beats:4}` → 渲染新历史/state;`scene_finished` 时
    自动停轮询并把开关复位;`finally autoBusy=false`。
  - 开关关闭 → 停 `setInterval` → `POST /api/auto {enabled:false}` → 渲染 state。
  - 自动模式期间禁用手动输入框与提示按钮(复用现有 `isBusy` 禁用逻辑,自动开启即 busy 态)。

### 3.5 数据流
```
[开启] 前端 toggle on
  → POST /api/auto {enabled:true}
  → set_auto_mode(True): 存原 agent_type、profile.agent_type=L1、player.enabled=False
  → 前端 setInterval 轮询

[逐拍] 前端 pollAutoStep(每 ~1.5s)
  → POST /api/auto/step {max_beats:4}
  → auto_step: controller.advance(never_stop, max_beats=4)  # 玩家角色由 L1 agent 演绎
  → 返回 state(含新历史);scene_finished 则前端停轮询 + 复位开关

[关闭] 前端 toggle off
  → 停 setInterval
  → POST /api/auto {enabled:false}
  → set_auto_mode(False): 还原 agent_type、player.enabled=True
  → 下一个玩家回合 is_player_turn 恢复 True,apply_player_action 重新等输入
```

---

## 4. 错误处理(沿用现有语义)
- `auto_step`:未初始化 / 未开自动 / 场景已结束 → `RuntimeError`(Web 层入口校验,同
  `apply_player_action`)。
- `advance` 撞 `max_hops` 仍抛 `RuntimeError`(理论上 `max_hops = max_beats + 8` 足够;
  若某拍 group 补拍异常多导致 hops 超限,抛错即暴露问题,不静默吞)。
- `set_auto_mode` 幂等:重复开/重复关是 no-op(靠 `auto_mode` 现值判定),避免重复存/还原
  `agent_type` 导致原值丢失。
- 前端轮询:单飞(`autoBusy` 防重入),请求失败停轮询并复位开关 + 提示。

## 5. 关闭/存档交互
- 存档快照(`_export_runtime_snapshot_unlocked`)**不持久化 `auto_mode`**:自动模式是
  临时演绎态,存档只落地 `state`(含被改的 `player.enabled` 与 profile.agent_type)。
  → 为避免存档落进"L1 化的玩家 + enabled=False"这种半自动态,`save` 前若 `auto_mode`
  开着,应先在 `auto_step`/`save` 路径确保还原,或在 `set_auto_mode(False)` 后再存。
  **本轮策略**:文档标注"自动模式下建议先关自动再存档";实现上 `_disable_auto_unlocked`
  保证还原,存档语义不额外改动(最小改动,避免牵动存档链路)。

---

## 6. 测试策略
新增/扩充(fake deps/agents + 轻量 state,不碰 LLM):
1. **controller max_beats**:构造一串 NPC 拍,`advance(never_stop, max_beats=3)` →
   断言正好推进 3 拍后返回、reason 含"3 拍"、不抛错。
2. **controller max_beats=None 回归**:断言与现状行为等价(推到 scene_finished / stop)。
3. **controller max_beats 遇 scene_finished 提前**:不足 max_beats 就结束 → 返回结束 reason。
4. **web_session set_auto_mode 开**:断言 `player.enabled==False`、玩家 profile
   `agent_type=="L1"`、`auto_mode==True`、原 agent_type 已存。
5. **web_session set_auto_mode 关**:断言还原 `enabled==True`、`agent_type` 复原、
   `auto_mode==False`。
6. **web_session set_auto_mode 幂等**:连开两次不丢原值;连关两次不报错。
7. **web_session auto_step**:开自动后 `auto_step(max_beats=2)` → 断言 state 推进、
   调用 controller.advance 传了 `stop_when=never_stop` 与 `max_beats=2`(可用 fake controller
   或 monkeypatch 验证参数)。
8. **web_session auto_step 未开自动 / 未初始化 / 已结束 → RuntimeError**。

**回归**:守住现有 180 全绿(controller 新参数默认 None,现有调用零改动)。

---

## 7. 文件结构
- **修改** `Graph/conversation_controller.py`:`advance` 增 `max_beats` 参数 + 拍计数提前返回。
- **修改** `web_session.py`:新增 `auto_mode`/`_player_saved_agent_type` 字段、
  `set_auto_mode` + `_enable_auto_unlocked`/`_disable_auto_unlocked`、`auto_step`;补 import `never_stop`。
- **修改** `web_server.py`:`_handle_post_api_request` 增 `/api/auto`、`/api/auto/step` 两路由。
- **修改** `frontend/index.html`:加自动开关 UI。
- **修改** `frontend/app.js`:API 表 + 轮询逻辑 + 禁用态联动。
- **扩充** `tests/test_conversation_controller.py`:max_beats 测试。
- **新建/扩充** `tests/test_web_session_auto_mode.py`:set_auto_mode / auto_step 测试。

---

## 8. 风险与权衡
- **玩家 L1 化靠改 profile.agent_type**:直接改运行期 profile 字段,依赖
  `_resolve_agent_for_actor` 每拍重读 profile(已确认它每次从 repo 读)。代价是要在关闭时
  精确还原原值;用 `_player_saved_agent_type` + 幂等守卫保证。
- **max_beats 而非 stop_when 计数**:`stop_when(state)` 无状态、看不到拍计数,故拍数上限
  作为 `advance` 独立参数更干净,且默认 None 不影响现有 5 个调用点。
- **enabled=False 复用现有机制**:`is_player_turn` 本就依赖 `enabled`,关掉它让玩家回合自然
  流向 actor 调度,零新增分支——最小侵入。
- **轮询而非 SSE**:用户选定;实现简单、可随时停;代价是历史更新有 ~1.5s 粒度延迟,
  可接受。
- **存档半自动态**:靠"先关自动再存档"的约定 + `_disable_auto_unlocked` 还原规避,
  本轮不改存档链路。

## 9. 不在本轮
- 自动"写小说"的完整独立入口(无 Web、纯批量到成书):本轮只接 Web 交互式自动模式。
- CLI(`demo_run.py`)复用。
- 玩家 L1 化时动态补全 `l1_profile` 字段(本轮依赖 L1 agent 对缺字段的兜底;若 L1 agent
  强依赖 `l1_profile`,实现阶段再评估是否补最小 l1_profile)。
