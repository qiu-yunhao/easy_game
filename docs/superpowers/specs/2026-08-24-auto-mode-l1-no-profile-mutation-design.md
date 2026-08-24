# 自动模式:玩家 L1 演绎改用运行时标志(不篡改共享档案)— 设计方案

> 日期:2026-08-24
> 状态:待 review(仅设计,不含实现)
> 关联 / 修正:**supersede** `2026-08-17-auto-mode-player-as-l1-design.md` 的 §3.2 与 §8
> 第一条风险。本轮只改"自动模式如何让玩家角色被 L1 agent 演绎"这一机制;逐拍推进
> (`advance` 的 `max_beats` / `stop_on_chapter_end`)、章节暂停、前端轮询、路由等**保持不变**。

---

## 1. 背景与目标

### 1.1 起点(现状)
自动模式已上线并可运行。当前实现(`web_session.py:487-512`)在开启时**临时篡改共享档案**:
把玩家 profile 的 `agent_type` 改成 `"L1"`,使 `_resolve_agent_for_actor`
(`Graph/dialogue_nodes.py:130-148`)选中 `l1_actor_agent`;关闭时再改回原值,存档导出
(`web_session.py:415-427`)时也要把玩家 `agent_type`/`enabled` 还原。

### 1.2 问题
玩家的 `agent_type` 存放在**共享的 `CharacterRepository`(`deps.character_profiles`)**。
自动模式期间它被就地改成 `"L1"`,意味着:
- 任何在"开启中"读该档案的路径(Director tier 分组、记忆系统 L1 判定、并发读、还原前
  的快照)都会读到**脏 L1 状态**——玩家平时并不应被全局当作 L1 对待。
- 为消除脏状态,代码被迫维护 `_player_saved_agent_type` 存/还原,并在快照导出里追加一段
  "还原玩家 agent_type"的补偿逻辑。链路多了一处易错的可逆篡改。

### 1.3 目标
把"玩家在自动模式下被 L1 agent 演绎"从**篡改共享档案**改为**运行时标志驱动**:
- 共享档案 `character_profiles` 的玩家 `agent_type` **全程不被改动**。
- 在 `PlayerState` 增加一个 `auto_mode: bool` 标志;调度层据此判断"当前 actor 是玩家
  且处于自动模式 → 用 `l1_actor_agent`",而**不读该档案的 `agent_type`**。
- 删除因篡改而存在的补偿代码:`_player_saved_agent_type` 字段、开/关时的
  `update_field(..., "agent_type", ...)`、以及快照导出里还原 `agent_type` 的分支。

### 1.4 已澄清的设计决策(用户拍板,2026-08-24)
- **玩家动作来源**:自动模式下复用现有 `l1_actor_agent`(不新建专用 agent)。
- **玩家档案定位**:玩家平时(手动模式)**不应被全局当 L1**;只在自动模式下临时"表现为
  L1"来驱动 agent。因此选择"运行时标志"而非"档案恒为 L1"。
- **零篡改共享档案**:这是本轮的核心动机——`character_profiles` 的玩家 `agent_type`
  任何时刻都不被写。
- **标志落点**:`PlayerState.auto_mode`(玩家控制态语义,随 `player.enabled` 一起管理),
  而非 `RuntimeState`(每拍频繁变动、参与快照,不适合承载会话级开关)。
- **`is_player_turn` 保持不变**:仍靠自动模式下 `player.enabled=False` 让玩家回合流向
  actor 分支——这个机制本身是对的,只需让 agent 解析不再依赖被篡改的 `agent_type`。

---

## 2. 现状盘点(已核对源码)

### 2.1 玩家回合的调度分叉
- `Graph/beat_subgraph.py:37-43` `is_player_turn(state)`:True 需三条件——`next_act 非空`
  ∧ `player.enabled` ∧ `next_act.actor == player.controlled_character`。
- `Graph/dialogue_nodes.py:151-167` `actor_node`:`is_player_turn` True → `resolve_player_turn_state`
  (等玩家输入);否则 → `_resolve_agent_for_actor` 选 agent → `resolve_npc_turn_state`。
- `Graph/dialogue_nodes.py:130-148` `_resolve_agent_for_actor(deps, actor_id)`:
  读 `deps.character_profiles.get(actor_id).agent_type`,`"L1"` → `l1_actor_agent`,
  否则 → `actor_agent`。**这是唯一读 `agent_type` 选 agent 的点,也是当前被迫篡改档案的根因。**

### 2.2 当前自动模式实现(将被修正)
- `web_session.py:487-499` `_enable_auto_unlocked`:存 `_player_saved_agent_type` →
  `update_field(player_id,"agent_type","L1")` → `player.enabled=False` → `auto_mode=True`。
- `web_session.py:501-512` `_disable_auto_unlocked`:`update_field` 还原 `agent_type` →
  `_player_saved_agent_type=None` → `player.enabled=True` → `auto_mode=False`。
- `web_session.py:415-427` `_export_runtime_snapshot_unlocked`:`auto_mode` 为真时,把导出
  快照里玩家 `agent_type` 还原为 `_player_saved_agent_type`、`state.player.enabled=True`。
- `web_session.py:207-208`:`self.auto_mode=False`、`self._player_saved_agent_type=None` 初始化。
- `web_session.py:696-700` `_reset_auto_mode_flags_unlocked`:会话重建/载档时清临时叠加态。

### 2.3 GameState / PlayerState
- `GameState.py:141-146` `PlayerState`:`enabled`、`controlled_character`、`last_input`、
  `last_parsed_act`。**本轮在此新增 `auto_mode: bool`。**

### 2.4 L1 agent 对 `l1_profile` 的依赖(旧设计 §9 悬念,现已核实)
- `Actor/L1ActorAgent.py:20`:"**When** `l1_profile` **is present**, let its internal conflict,
  outer goal, and relationship pressure shape the turn." —— 有则用。
- `Actor/ActorFormatter.py:71`:`"l1_profile": actor_profile.get("l1_profile", {})` —— 缺失兜底空 dict。
- **结论**:玩家 profile 即使未填 `l1_profile`,L1 agent 也能正常运行(退化为无深层戏剧
  张力),不崩、不阻塞。玩家 profile schema 本就支持 `l1_profile`(`player_profile.schema.json:100`),
  若已填则自动被用上。**本轮不强制补全 `l1_profile`。**

### 2.5 `agent_type` 的 schema 残留(顺带记录,非本轮)
- `player_profile.schema.json:73-82` 的 `agent_type`/`story_layer` enum 仍含 `"L2"`,
  而 L2 已于 2026-08-21 全局移除。属遗留脏 enum,**不在本轮**,仅记录。

---

## 3. 设计

### 3.1 PlayerState 增加 auto_mode 标志
`GameState.py` `PlayerState` 新增字段:
```python
class PlayerState(TypedDict):
    enabled: bool
    controlled_character: Optional[str]
    auto_mode: bool          # 新增:玩家回合是否由 L1 agent 自动演绎
    last_input: str
    last_parsed_act: Optional[ResolvedAct]
```
- 初始 state 构造处需补 `auto_mode: False`(玩家 state 初始化的地方,随 `enabled` 一起设)。
- 语义:`auto_mode=True` 且轮到玩家角色时,该回合交 `l1_actor_agent` 演绎;为 False 时
  维持现状(手动或普通调度)。

### 3.2 _resolve_agent_for_actor 识别"玩家自动态"
`Graph/dialogue_nodes.py:130-148` 增加"玩家 + 自动模式 → L1 agent"的判断,**优先于**读
`agent_type`,且该分支完全不读 `character_profiles`:
```python
def _resolve_agent_for_actor(
    deps: GraphDependencies,
    actor_id: str,
    state: GameState,          # 新增入参:用于读取 player 自动态
) -> ActorAgent | None:
    player = state["player"]
    if player.get("auto_mode", False) and actor_id == player.get("controlled_character"):
        # 玩家在自动模式下由 L1 agent 演绎;不读也不改 character_profiles.agent_type。
        return _resolve_component(deps, "l1_actor_agent", "build_l1_actor_agent",
                                  required_name="an L1ActorAgent")
    actor_profile = deps.character_profiles.get(actor_id, {})
    agent_type = _clean_text(actor_profile.get("agent_type", ""), "actor")
    if agent_type == "L1":
        return _resolve_component(deps, "l1_actor_agent", "build_l1_actor_agent",
                                  required_name="an L1ActorAgent")
    return _resolve_component(deps, "actor_agent", "build_actor_agent",
                              required_name="an ActorAgent")
```
调用点 `actor_node`(`dialogue_nodes.py:160`)相应改为 `_resolve_agent_for_actor(deps, actor_id, state)`。
- 注:非玩家 actor 若档案本身 `agent_type=="L1"`(创建期定的 L1 角色)仍走第二个分支,行为不变。

### 3.3 web_session:标志化开/关,删除档案篡改
`_enable_auto_unlocked`(不再碰 `character_profiles`):
```python
def _enable_auto_unlocked(self) -> None:
    # 玩家回合改由 L1 agent 演绎:只设运行时标志,不篡改共享档案。
    self.state = {
        **self.state,
        "player": {**self.state["player"], "enabled": False, "auto_mode": True},
    }
    self.auto_mode = True
    self.last_handoff_reason = "自动模式已开启：玩家角色由核心角色 agent 自动演绎。"
```
`_disable_auto_unlocked`:
```python
def _disable_auto_unlocked(self) -> None:
    self.state = {
        **self.state,
        "player": {**self.state["player"], "enabled": True, "auto_mode": False},
    }
    self.auto_mode = False
    self.last_handoff_reason = "自动模式已关闭：下一个玩家回合恢复等待输入。"
```
删除:
- `self._player_saved_agent_type` 字段(`web_session.py:208` 初始化、开/关处的读写)。
- 开/关中的 `character_profiles.update_field(player_id, "agent_type", ...)` 两处。

> `self.auto_mode`(session 级)与 `state.player.auto_mode`(state 级)保留两份:前者是
> Web 会话的开关真值(`set_auto_mode`/`auto_step` 校验用),后者随 state 流入调度层供
> `_resolve_agent_for_actor` 读。二者在开/关时同步翻转,`_reset_auto_mode_flags_unlocked`
> 一并归位。

### 3.4 快照导出:去掉 agent_type 还原,保留 enabled/auto_mode 归正
`_export_runtime_snapshot_unlocked`(`web_session.py:415-427`)简化为:
```python
def _export_runtime_snapshot_unlocked(self) -> dict[str, Any]:
    state = _json_clone(self.state)
    profiles = _json_clone(_profiles_as_dict(self.character_profiles))
    if self.auto_mode and isinstance(state.get("player"), dict):
        # 存档只落地正常游玩态:把临时自动叠加还原为手动态(enabled=True, auto_mode=False)。
        # 档案未被篡改,无需还原 agent_type。
        state["player"]["enabled"] = True
        state["player"]["auto_mode"] = False
    return { ... 其余不变 ... }
```
- 删除对 `profiles[player_id]["agent_type"]` 的还原(档案本就没被改)。
- `_load_runtime_snapshot_unlocked` 末尾仍调 `_reset_auto_mode_flags_unlocked`
  (`web_session.py:476`),它需确保载入后 `state.player.auto_mode=False` 与 `self.auto_mode=False`。

### 3.5 _reset_auto_mode_flags_unlocked
确保重置时同时归正两处:`self.auto_mode=False`、`self._player_saved_agent_type` 相关行删除、
且若 `state.player` 存在则 `enabled=True`、`auto_mode=False`(具体依现有实现补 `auto_mode`)。

---

## 4. 数据流(修正后)
```
[开启] 前端 toggle on
  → POST /api/auto {enabled:true}
  → set_auto_mode(True): player.enabled=False, player.auto_mode=True, session.auto_mode=True
    # 不动 character_profiles

[逐拍] pollAutoStep(每 ~1.5s)  # 逐拍机制不变
  → POST /api/auto/step {max_beats:4}
  → auto_step: controller.advance(never_stop, max_beats=4, stop_on_chapter_end=True)
    → actor_node: is_player_turn=False(enabled=False) → _resolve_agent_for_actor(deps, actor_id, state)
      → player.auto_mode && actor_id==controlled_character → l1_actor_agent(读玩家自己的 l1_profile)
  → 返回 state(chapter_paused / scene_finished 语义不变)

[关闭] 前端 toggle off
  → POST /api/auto {enabled:false}
  → set_auto_mode(False): player.enabled=True, player.auto_mode=False, session.auto_mode=False
  → 下一个玩家回合 is_player_turn 恢复 True,重新等输入

[存档] export_runtime_snapshot
  → 若 auto_mode 开着:导出 state 里 player.enabled=True, player.auto_mode=False
  → character_profiles 原样导出(从未被改)
```

---

## 5. 错误处理(沿用现有语义)
- `auto_step`/`set_auto_mode` 的入口校验、幂等(靠 `self.auto_mode` 现值判定开/关 no-op)
  保持不变。幂等语义因不再存/还原 `agent_type` 而更简单:重复开/关只翻标志。
- `l1_actor_agent` 遇玩家 profile 缺 `l1_profile`:兜底空 dict,退化演绎,不报错(见 §2.4)。

---

## 6. 测试策略
**改造现有** `tests/test_web_session_auto_mode.py`(当前断言 `agent_type=="L1"` 的用例需改):
1. **开启**:断言 `state.player.enabled==False`、`state.player.auto_mode==True`、
   `session.auto_mode==True`,且**玩家档案 `agent_type` 未被改动**(仍是原值,如 `"actor"`)。
2. **关闭**:断言 `enabled==True`、`player.auto_mode==False`、`session.auto_mode==False`,
   档案 `agent_type` 始终原值。
3. **幂等**:连开两次 / 连关两次不报错,标志稳定,档案不被碰。
4. **快照导出**:开启中导出 → 快照 `state.player.enabled==True`、`auto_mode==False`,
   且快照里玩家档案 `agent_type` == 原值(不含 L1)。
5. **reset/load**:载档后 `state.player.auto_mode==False`、`session.auto_mode==False`。

**新增** `tests/test_beat_resolution.py`(或就近):
6. **玩家自动态派发 L1**:构造 `state.player={auto_mode:True, controlled_character:"player"}`、
   `next_act.actor=="player"`、玩家档案 `agent_type=="actor"`(故意非 L1)→ 断言
   `_resolve_agent_for_actor` 返回 `l1_actor_agent`(证明走标志分支、不依赖 agent_type)。
7. **非玩家 actor 不受标志影响**:`auto_mode:True` 但 `actor_id != controlled_character` 且
   档案 `agent_type=="actor"` → 返回普通 `actor_agent`。
8. **创建期 L1 角色仍走 agent_type 分支**:`auto_mode:False`、某 NPC 档案 `agent_type=="L1"`
   → 返回 `l1_actor_agent`(回归,保 `test_actor_node_dispatches_to_l1_actor_agent` 等价)。

**回归**:守住现有全绿套件(455 测试基线)。`PlayerState` 新增 `auto_mode` 为必填 key —
需排查所有手工构造 `player` state 的测试夹具与生产初始化点,补 `auto_mode: False`。

---

## 7. 文件结构
- **修改** `GameState.py`:`PlayerState` 增 `auto_mode: bool`。
- **修改** `Graph/dialogue_nodes.py`:`_resolve_agent_for_actor` 增 `state` 入参 + 玩家自动态
  分支;`actor_node` 调用点补传 `state`。
- **修改** `web_session.py`:`_enable_auto_unlocked`/`_disable_auto_unlocked` 改为只翻标志、
  设 `player.auto_mode`;删 `_player_saved_agent_type` 字段与 `update_field(agent_type)` 两处;
  简化 `_export_runtime_snapshot_unlocked`;`_reset_auto_mode_flags_unlocked` 补 `auto_mode` 归零;
  玩家 state 初始构造补 `auto_mode: False`。
- **修改** `tests/test_web_session_auto_mode.py`:改断言(见 §6.1-5)。
- **扩充** `tests/test_beat_resolution.py`:玩家自动态派发用例(§6.6-8)。
- 排查并修正:所有构造 `player` state 的夹具/初始化,补 `auto_mode` key。

前端(`frontend/`)、路由(`web_server.py`)、`advance` 的 `max_beats`/`stop_on_chapter_end`、
章节暂停逻辑 **均不改动**。

---

## 8. 风险与权衡
- **`auto_mode` 双份状态(session + state.player)**:`self.auto_mode` 作会话开关真值,
  `state.player.auto_mode` 作调度层可读的流动标志,二者必须同步翻转。风险在漏同步;
  用集中在 `_enable/_disable/_reset` 三处翻转 + 测试断言两者一致来守。
- **`_resolve_agent_for_actor` 新增 `state` 入参**:签名变更,`impact` 需确认全部调用点
  (当前仅 `actor_node` 一处调用)。属低风险内部函数。
- **`PlayerState` 新增必填 key**:TypedDict 加字段会让所有手工构造 `player` 的地方缺 key;
  实现时须全量排查夹具/初始化并补 `auto_mode: False`,否则测试/运行 KeyError。
- **玩家 `l1_profile` 缺失**:退化演绎(§2.4),可接受;若后续要玩家自动演绎更"入戏",
  再评估为玩家 profile 补最小 `l1_profile`(不在本轮)。

## 9. 不在本轮
- 为玩家 profile 补全 `l1_profile` 字段。
- 清理 `player_profile.schema.json` 里 `agent_type`/`story_layer` 的 `"L2"` 残留 enum。
- 通用"NPC actor → L1 后天升格"(`can_promote_to_l1` 消费端缺失)——这是独立的、更大的
  设计问题,与本轮"玩家自动演绎"正交,另开 spec。
