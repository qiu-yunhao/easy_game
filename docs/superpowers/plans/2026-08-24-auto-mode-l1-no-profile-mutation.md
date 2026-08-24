# 自动模式 L1 演绎改用运行时标志 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自动模式通过 `PlayerState.auto_mode` 运行时标志驱动"玩家回合由 L1 agent 演绎",彻底不再篡改共享档案 `character_profiles` 的玩家 `agent_type`。

**Architecture:** 在 `PlayerState` 增加 `auto_mode: bool`;调度层 `_resolve_agent_for_actor` 优先识别"玩家 + 自动模式 → `l1_actor_agent`",不读 `agent_type`;`web_session` 的开/关只翻标志、删除 `agent_type` 存/改/还原的补偿逻辑;快照导出只归正 `enabled`/`auto_mode`,不还原 `agent_type`。

**Tech Stack:** Python(TypedDict `GameState`)、unittest、pytest 运行。

> 关联 spec:`docs/superpowers/specs/2026-08-24-auto-mode-l1-no-profile-mutation-design.md`

---

## 文件结构

- `GameState.py` — `PlayerState` TypedDict 加 `auto_mode` 字段;`create_player_state` 补默认值。**责任:玩家运行时状态的类型与工厂。**
- `Graph/dialogue_nodes.py` — `_resolve_agent_for_actor` 加玩家自动态分支 + `state` 入参;`actor_node` 调用点补传 `state`。**责任:玩家回合的 agent 解析。**
- `web_session.py` — `_enable/_disable_auto_unlocked` 改为只翻标志;删 `_player_saved_agent_type`;简化 `_export_runtime_snapshot_unlocked`;`_reset_auto_mode_flags_unlocked` 补 `auto_mode` 归零。**责任:Web 会话的自动模式开关与存档。**
- `tests/test_web_session_auto_mode.py` — 改断言(不再断言 `agent_type=="L1"`)。
- `tests/test_beat_resolution.py` — 新增玩家自动态派发 L1 的用例。

前端、`web_server.py` 路由、`advance` 的 `max_beats`/`stop_on_chapter_end`、章节暂停逻辑**均不改**。

---

## Task 1: PlayerState 增加 auto_mode 字段

**Files:**
- Modify: `GameState.py:141-146`(`PlayerState`)、`GameState.py:199-211`(`create_player_state`)

- [ ] **Step 1: 在 PlayerState 加字段**

编辑 `GameState.py` 的 `PlayerState`(当前 141-146 行),在 `controlled_character` 后插入 `auto_mode`:

```python
class PlayerState(TypedDict):
    enabled: bool
    controlled_character: Optional[str]
    auto_mode: bool
    last_input: str
    last_parsed_act: Optional[ResolvedAct]
```

- [ ] **Step 2: 在 create_player_state 补默认值**

编辑 `GameState.py` 的 `create_player_state`(当前 199-211 行),加入 `auto_mode` 参数并写进返回 dict:

```python
def create_player_state(
    *,
    controlled_character: str | None = None,
    enabled: bool | None = None,
    auto_mode: bool = False,
    last_input: str = "",
    last_parsed_act: ResolvedAct | None = None,
) -> PlayerState:
    return {
        "enabled": bool(controlled_character) if enabled is None else enabled,
        "controlled_character": controlled_character,
        "auto_mode": auto_mode,
        "last_input": last_input,
        "last_parsed_act": last_parsed_act,
    }
```

- [ ] **Step 3: 找出所有绕过工厂手工构造 player 的生产代码点**

Run: `grep -rn '"player"\s*:\s*{' --include="*.py" . | grep -v "/.pytest_cache/" | grep -v "/tests/"`
Expected: 命中 `web_session.py` 若干处(如 674-694 附近的 player dict、876 附近 `player_state.get(...)` 重建)。逐一确认:凡是**用字面 dict 直接构造完整 player**(而非 `{**self.state["player"], ...}` 展开)的,都要补 `"auto_mode": ...`。用 `{**old, "field": val}` 展开的因保留原 key 无需改。

- [ ] **Step 4: 修正 web_session 中手工构造 player 的点**

打开 `web_session.py`,定位到用字面量构造完整 `player` dict 的地方(约 674-694、876 附近)。对每个完整字面构造补 `"auto_mode": False`(重建/新建默认非自动)。对 `{**self.state["player"], "enabled": ...}` 这类展开式**不要动**(下一 Task 专门改)。

> 注:`web_session.py:876` 附近若是 `"enabled": player_state.get("enabled", False)` 形式重建,补一行 `"auto_mode": player_state.get("auto_mode", False)`。

- [ ] **Step 5: 运行全量测试,确认加字段没打破现有夹具**

Run: `python -m pytest tests/ -q`
Expected: 可能有测试因手工构造 `player` 缺 `auto_mode` 而 KeyError/失败。**记录失败清单**——这些夹具在 Task 5 统一补。若全绿则更好。

- [ ] **Step 6: Commit**

```bash
git add GameState.py web_session.py
git commit -m "feat(game-state): add PlayerState.auto_mode flag"
```

---

## Task 2: 调度层识别玩家自动态派发 L1 agent(先写失败测试)

**Files:**
- Test: `tests/test_beat_resolution.py`(在 `test_actor_node_dispatches_to_l1_actor_agent` 之后新增)
- Modify: `Graph/dialogue_nodes.py:130-167`

- [ ] **Step 1: 写失败测试——玩家自动态即使 agent_type=actor 也派 L1**

在 `tests/test_beat_resolution.py` 的 `test_actor_node_dispatches_to_l1_actor_agent` 方法之后,新增三个用例(同一 TestCase 类内)。注意:`_build_state` 用 `create_player_state`,玩家自动态通过直接改返回 state 的 `player` dict 设置。

```python
    def test_actor_node_dispatches_player_to_l1_when_auto_mode(self) -> None:
        # 玩家在自动模式下:即便档案 agent_type=actor,也应由 l1_actor_agent 演绎。
        state = _build_state(
            on_stage=["player"],
            focus_character="player",
            player_character="player",
        )
        state["player"]["enabled"] = False
        state["player"]["auto_mode"] = True
        state["runtime"]["next_act"] = {
            "actor": "player",
            "mode": "speak",
            "target": None,
            "motivation": "",
            "content": "",
        }
        profiles = _build_profiles(["player"])
        self.assertEqual(profiles["player"].get("agent_type"), "actor")  # 故意非 L1
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["player"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            actor_agent=FakeTierActor("default"),
            l1_actor_agent=FakeTierActor("l1"),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)
        next_state = actor_node(state, deps)
        self.assertEqual(next_state["runtime"]["resolved_act"]["spoken_text"], "l1:player")
        # 档案未被篡改。
        self.assertEqual(profiles["player"].get("agent_type"), "actor")

    def test_actor_node_non_player_ignores_auto_mode_flag(self) -> None:
        # auto_mode 为真,但当前 actor 不是玩家 → 仍按其档案 agent_type 走普通 agent。
        state = _build_state(
            on_stage=["npc_a"],
            focus_character="npc_a",
            player_character="player",
        )
        state["player"]["auto_mode"] = True
        state["runtime"]["next_act"] = {
            "actor": "npc_a",
            "mode": "speak",
            "target": None,
            "motivation": "",
            "content": "",
        }
        profiles = _build_profiles(["player", "npc_a"])  # npc_a agent_type=actor
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            actor_agent=FakeTierActor("default"),
            l1_actor_agent=FakeTierActor("l1"),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)
        next_state = actor_node(state, deps)
        self.assertEqual(next_state["runtime"]["resolved_act"]["spoken_text"], "default:npc_a")
```

- [ ] **Step 2: 运行新测试,确认失败**

Run: `python -m pytest tests/test_beat_resolution.py::BeatResolutionTest::test_actor_node_dispatches_player_to_l1_when_auto_mode -v`
Expected: FAIL —— 目前 `_resolve_agent_for_actor` 只读 `agent_type`,玩家档案是 `actor`,会派 `default` agent,`spoken_text` 得到 `"default:player"` 而非 `"l1:player"`。

> 若测试类名不是 `BeatResolutionTest`,先 `grep -n "class .*Test" tests/test_beat_resolution.py` 确认,用实际类名运行。

- [ ] **Step 3: 改 `_resolve_agent_for_actor` 加 state 入参 + 玩家自动态分支**

编辑 `Graph/dialogue_nodes.py`,把 `_resolve_agent_for_actor`(当前 130-148 行)改为:

```python
def _resolve_agent_for_actor(
    deps: GraphDependencies,
    actor_id: str,
    state: GameState,
) -> ActorAgent | None:
    player = state["player"]
    if player.get("auto_mode", False) and actor_id == player.get("controlled_character"):
        # 玩家在自动模式下由 L1 agent 演绎;不读也不改 character_profiles.agent_type。
        return _resolve_component(
            deps,
            "l1_actor_agent",
            "build_l1_actor_agent",
            required_name="an L1ActorAgent",
        )
    actor_profile = deps.character_profiles.get(actor_id, {})
    agent_type = _clean_text(actor_profile.get("agent_type", ""), "actor")
    if agent_type == "L1":
        return _resolve_component(
            deps,
            "l1_actor_agent",
            "build_l1_actor_agent",
            required_name="an L1ActorAgent",
        )
    return _resolve_component(
        deps,
        "actor_agent",
        "build_actor_agent",
        required_name="an ActorAgent",
    )
```

- [ ] **Step 4: 更新调用点传 state**

编辑 `Graph/dialogue_nodes.py` 的 `actor_node`(当前 160 行),把
`selected_actor_agent = _resolve_agent_for_actor(deps, actor_id)`
改为
`selected_actor_agent = _resolve_agent_for_actor(deps, actor_id, state)`。

- [ ] **Step 5: 运行三个新测试 + 原 L1 派发回归**

Run: `python -m pytest tests/test_beat_resolution.py -k "l1 or auto_mode or player_to_l1 or non_player_ignores" -v`
Expected: PASS —— 新增两个 + 原 `test_actor_node_dispatches_to_l1_actor_agent`(创建期 L1 角色仍走 `agent_type` 分支)全绿。

- [ ] **Step 6: Commit**

```bash
git add Graph/dialogue_nodes.py tests/test_beat_resolution.py
git commit -m "feat(dialogue): resolve player to L1 agent via auto_mode flag, not agent_type"
```

---

## Task 3: web_session 开/关只翻标志,删除 agent_type 篡改

**Files:**
- Modify: `web_session.py:487-512`(`_enable`/`_disable_auto_unlocked`)、`web_session.py:207-208`(字段初始化)

- [ ] **Step 1: 改 `_enable_auto_unlocked` 为只翻标志**

编辑 `web_session.py`(当前 487-499 行),替换为:

```python
    def _enable_auto_unlocked(self) -> None:
        # 玩家回合改由 L1 agent 演绎:只设运行时标志,不篡改共享档案 character_profiles。
        self.state = {
            **self.state,
            "player": {**self.state["player"], "enabled": False, "auto_mode": True},
        }
        self.auto_mode = True
        self.last_handoff_reason = "自动模式已开启：玩家角色由核心角色 agent 自动演绎。"
```

- [ ] **Step 2: 改 `_disable_auto_unlocked` 为只翻标志**

编辑 `web_session.py`(当前 501-512 行),替换为:

```python
    def _disable_auto_unlocked(self) -> None:
        self.state = {
            **self.state,
            "player": {**self.state["player"], "enabled": True, "auto_mode": False},
        }
        self.auto_mode = False
        self.last_handoff_reason = "自动模式已关闭：下一个玩家回合恢复等待输入。"
```

- [ ] **Step 3: 删除 `_player_saved_agent_type` 字段初始化**

编辑 `web_session.py`(当前约 208 行),删除这一行:
`self._player_saved_agent_type: str | None = None`

- [ ] **Step 4: 全量搜 `_player_saved_agent_type` 残留**

Run: `grep -rn "_player_saved_agent_type" --include="*.py" . | grep -v "/.pytest_cache/"`
Expected: 除了 Task 4 将改的 `_reset_auto_mode_flags_unlocked` 与测试文件,不应再有生产引用。若 `_reset` 里还有,留到 Task 4 删。

- [ ] **Step 5: 运行(预期部分 auto_mode 测试红,下一步改)**

Run: `python -m pytest tests/test_web_session_auto_mode.py -q`
Expected: 若干断言 `agent_type=="L1"` / `_player_saved_agent_type` 的用例失败——正常,Task 6 改测试。此步只确认没有 import/语法错误(NameError 之类应为 0)。

- [ ] **Step 6: Commit**

```bash
git add web_session.py
git commit -m "refactor(web-session): auto mode toggles flag only, no profile mutation"
```

---

## Task 4: 简化快照导出与 reset(去掉 agent_type 还原)

**Files:**
- Modify: `web_session.py:415-427`(`_export_runtime_snapshot_unlocked`)、`web_session.py:696-700`(`_reset_auto_mode_flags_unlocked`)

- [ ] **Step 1: 简化 `_export_runtime_snapshot_unlocked`**

编辑 `web_session.py`(当前 415-427 行的自动态处理块),把 `if self.auto_mode:` 那段替换为:

```python
    def _export_runtime_snapshot_unlocked(self) -> dict[str, Any]:
        state = _json_clone(self.state)
        profiles = _json_clone(_profiles_as_dict(self.character_profiles))
        if self.auto_mode and isinstance(state.get("player"), dict):
            # 存档只落地正常游玩态:把临时自动叠加还原为手动态。档案未被篡改,无需还原 agent_type。
            state["player"]["enabled"] = True
            state["player"]["auto_mode"] = False
        return {
```

保留其后 `"session": {...}` 到函数结尾原样不动(即从 `return {` 之后的字典体不变)。

- [ ] **Step 2: `_reset_auto_mode_flags_unlocked` 删 saved_agent_type、补 auto_mode 归零**

编辑 `web_session.py`(当前 696-700 行),替换为:

```python
    def _reset_auto_mode_flags_unlocked(self) -> None:
        # 会话被重建/换档时清掉自动模式的临时叠加态,避免脏标志残留到全新/载入的状态上。
        self.auto_mode = False
        self._last_chapter_advanced = False
        if isinstance(self.state.get("player"), dict):
            self.state = {
                **self.state,
                "player": {**self.state["player"], "auto_mode": False},
            }
```

> 注:`_reset_auto_mode_flags_unlocked` 的调用时机(`_rebuild_session` / `_load_runtime_snapshot_unlocked`)保持不变。若某调用发生在 `self.state` 尚未建立时,`isinstance(... , dict)` 守卫会跳过,安全。

- [ ] **Step 3: 运行(仍预期 auto_mode 测试红)**

Run: `python -m pytest tests/test_web_session_auto_mode.py -q`
Expected: 无 NameError(`_player_saved_agent_type` 已从生产代码清除),仅剩断言层面的失败留待 Task 6。

- [ ] **Step 4: Commit**

```bash
git add web_session.py
git commit -m "refactor(web-session): drop agent_type restore in snapshot/reset"
```

---

## Task 5: 补齐所有夹具/初始化的 auto_mode key

**Files:**
- Modify: Task 1 Step 5 记录的失败清单涉及的测试夹具;`tools/test_cleanup.py` 等手工构造 player 的点

- [ ] **Step 1: 找出所有手工构造 player(含测试)缺 auto_mode 的点**

Run: `grep -rn '"player"\s*:\s*{\|"enabled"\s*:\s*True\|"enabled"\s*:\s*False' --include="*.py" . | grep -v "/.pytest_cache/"`
逐一判断:凡是**字面构造完整 player dict**(不是 `{**old, ...}` 展开、也不是经 `create_player_state`)且缺 `auto_mode` 的,需补 `"auto_mode": False`。经 `create_player_state` 的因 Task 1 已有默认值,无需改。

- [ ] **Step 2: 补 key**

对上一步命中的每个字面 player dict,加入 `"auto_mode": False`。典型位置:`tools/test_cleanup.py`(多处)、以及 Task 1 Step 5 记录的失败测试。

- [ ] **Step 3: 运行全量测试(排除 auto_mode 专项,那个 Task 6 改)**

Run: `python -m pytest tests/ -q --deselect tests/test_web_session_auto_mode.py`
Expected: PASS —— 除 auto_mode 专项外全绿,证明加字段未破坏其它夹具。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: add auto_mode key to manual player-state fixtures"
```

---

## Task 6: 更新 auto_mode 专项测试断言

**Files:**
- Modify: `tests/test_web_session_auto_mode.py`

- [ ] **Step 1: 改开启用例——断言标志翻转且档案不被改**

编辑 `tests/test_web_session_auto_mode.py`。把 `test_enable_flips_enabled_and_upgrades_agent_type`(当前 16-29 行)替换为:

```python
    def test_enable_flips_flags_and_leaves_profile_untouched(self):
        session = _session()
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
        session.set_auto_mode(True)
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertTrue(session.state["player"].get("auto_mode"))
        # 共享档案全程不被篡改。
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
```

- [ ] **Step 2: 改关闭用例**

把 `test_disable_restores_enabled_and_agent_type`(当前 31-40 行)替换为:

```python
    def test_disable_restores_flags_and_leaves_profile_untouched(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(False)
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
```

- [ ] **Step 3: 改幂等用例**

把 `test_enable_twice_is_idempotent_and_keeps_original_agent_type`(当前 42-50 行)替换为:

```python
    def test_enable_twice_is_idempotent(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(True)  # 第二次 no-op
        self.assertTrue(session.state["player"].get("auto_mode"))
        session.set_auto_mode(False)
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
```

- [ ] **Step 4: 改快照导出用例**

把 `test_export_while_auto_restores_pre_promotion_player`(当前 119-136 行)替换为:

```python
    def test_export_while_auto_normalizes_player_to_manual(self):
        # 自动模式开着时导出快照:player.enabled 归 True、auto_mode 归 False;
        # 档案 agent_type 始终原值(从未被改);会话本体仍保持自动叠加态。
        session = _session()
        session.set_auto_mode(True)
        snapshot = session._export_runtime_snapshot_unlocked()

        self.assertEqual(
            snapshot["character_profiles"][PLAYER_CHARACTER_ID].get("agent_type"),
            "actor",
        )
        self.assertTrue(snapshot["state"]["player"].get("enabled"))
        self.assertFalse(snapshot["state"]["player"].get("auto_mode"))

        # 会话本体不受导出影响,仍在自动叠加态。
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertTrue(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
```

- [ ] **Step 5: 改 reset / load 用例(删 `_player_saved_agent_type` 断言,加 player.auto_mode)**

把 `test_reset_clears_auto_mode_flags`(当前 149-161 行)替换为:

```python
    def test_reset_clears_auto_mode_flags(self):
        session = _session()
        session.set_auto_mode(True)
        session._last_chapter_advanced = True
        session.reset(player_profile={"name": "重开玩家"})
        self.assertFalse(session.auto_mode)
        self.assertFalse(session._last_chapter_advanced)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
```

把 `test_load_snapshot_clears_auto_mode_flags`(当前 163-173 行)替换为:

```python
    def test_load_snapshot_clears_auto_mode_flags(self):
        session = _session()
        clean_snapshot = session._export_runtime_snapshot_unlocked()
        session.set_auto_mode(True)
        session._last_chapter_advanced = True
        session._load_runtime_snapshot_unlocked(clean_snapshot)
        self.assertFalse(session.auto_mode)
        self.assertFalse(session._last_chapter_advanced)
        self.assertFalse(session.state["player"].get("auto_mode"))
```

- [ ] **Step 6: 运行 auto_mode 专项全绿**

Run: `python -m pytest tests/test_web_session_auto_mode.py -v`
Expected: PASS —— 所有用例通过(`AutoStepTest` 那组因 `advance` 未改、`set_auto_mode` 行为等价,应继续通过)。

- [ ] **Step 7: Commit**

```bash
git add tests/test_web_session_auto_mode.py
git commit -m "test(auto-mode): assert flag-driven L1 dispatch, no profile mutation"
```

---

## Task 7: 全量回归

**Files:** 无(仅验证)

- [ ] **Step 1: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: PASS —— 全绿(基线约 455 + 本轮新增用例)。

- [ ] **Step 2: 若有失败,定位并修**

对每个失败:若是漏补 `auto_mode` key 的夹具 → 回 Task 5 补;若是断言过时 → 就地改。修完重跑直到全绿。

- [ ] **Step 3: 确认无 agent_type 篡改残留**

Run: `grep -rn 'update_field.*agent_type\|_player_saved_agent_type' --include="*.py" . | grep -v "/.pytest_cache/"`
Expected: 空(生产与测试均无残留)。

---

## 完成标准

- 全量测试绿。
- 自动模式开启时 `character_profiles[player].agent_type` 保持原值(不被写)。
- `state.player.auto_mode` 驱动 `_resolve_agent_for_actor` 派发 `l1_actor_agent`。
- 快照导出把玩家归正为手动态(`enabled=True`, `auto_mode=False`),不含 `agent_type` 还原。
- 无 `_player_saved_agent_type` / `update_field(...,"agent_type",...)` 残留。
