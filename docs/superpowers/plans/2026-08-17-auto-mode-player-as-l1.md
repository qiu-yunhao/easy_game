# 自动模式(玩家角色升格 L1 Agent + 逐拍推进)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让玩家开启"自动"开关后,玩家角色临时升格为 L1 核心角色由 L1 actor agent 自动演绎,逐拍推进(每次轮询推 3-5 拍);每个章节结束时停下等用户点"继续下一章",确认后自动续演;关闭后下一个玩家回合恢复等待输入。

**Architecture:** 复用阶段5 的 `ConversationController`。给 `advance` 增加 `max_beats` 拍数上限 + `stop_on_chapter_end`(检测 `plot.chapter_id` 变化以停在章节边界)两个参数(默认不影响现有调用)。`WebGameSession` 新增 `set_auto_mode`(改 `player.enabled=False` + 玩家 profile `agent_type="L1"`,关闭时还原)和 `auto_step`(调 `advance(never_stop, max_beats, stop_on_chapter_end=True)`,暴露 `chapter_paused`)。`web_server` 加 `/api/auto`、`/api/auto/step` 两路由。前端加开关 + 1.5s 轮询 + "继续下一章"按钮。

**Tech Stack:** Python(unittest + pytest),vanilla JS 前端,`http.server` 后端。测试用 `unittest.mock.patch` 在模块级打桩,`WebGameSession(SessionConfig(mode="heuristic"))` 起真实无 LLM/DB 会话。

**关联 spec:** `docs/superpowers/specs/2026-08-17-auto-mode-player-as-l1-design.md`

**基线:** 当前 299 测试全绿。本计划新增测试后应仍全绿。

---

## 文件结构

| 文件 | 职责 | 改动 |
|------|------|------|
| `Graph/conversation_controller.py` | mode-agnostic 推进控制器 | `advance` 增 `max_beats` 参数 + 拍计数提前返回 |
| `tests/test_conversation_controller.py` | controller 单测 | 扩充 `max_beats` 相关 3 个测试 |
| `web_session.py` | Web 会话(锁/序列化/存档/工具路由) | 新增 auto 状态字段 + `set_auto_mode`/`_enable_auto_unlocked`/`_disable_auto_unlocked`/`auto_step`;补 import `never_stop` |
| `tests/test_web_session_auto_mode.py` | auto 模式单测(新建) | set_auto_mode / auto_step 全套 |
| `web_server.py` | HTTP 路由分发 | `_handle_post_api_request` 增两路由 |
| `frontend/index.html` | 前端结构 | 加自动开关 UI |
| `frontend/app.js` | 前端逻辑 | API 表 + 轮询 + 禁用态联动 |

---

## Task 1: ConversationController.advance 增加 max_beats

**Files:**
- Modify: `Graph/conversation_controller.py:81-121`(`advance` 方法)
- Test: `tests/test_conversation_controller.py`

**背景:** 当前 `advance` 只在 `stop_when` / `scene_finished` / `next_act is None` 时返回,否则跑到 `max_hops` 抛错。自动模式用 `never_stop` 谓词,`stop_when` 永不触发,需要"推 N 拍就正常返回"。一次 `resolve_story_turn` = 一拍。

- [ ] **Step 1: 写失败测试 — max_beats 到达即返回**

在 `tests/test_conversation_controller.py` 末尾(`AdvanceNextActNoneTest` 类之后、`if __name__` 之前)追加:

```python
class AdvanceMaxBeatsTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_returns_after_max_beats(self):
        # 永不终止的 NPC 回合 + never_stop,但 max_beats=3 → 正好推 3 拍后正常返回,不抛错。
        calls = {"n": 0}

        def _fake_resolve(state, deps, on_event=None):
            calls["n"] += 1
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "npc_a"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(
                state, stop_when=never_stop, max_beats=3, max_hops=24
            )
        self.assertEqual(calls["n"], 3)
        self.assertIn("3 拍", reason)

    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_max_beats_stops_early_on_scene_finished(self):
        # 不足 max_beats 就 scene_finished → 提前返回结束 reason,而非"N 拍"。
        def _fake_resolve(state, deps, on_event=None):
            return {**state, "runtime": {**state["runtime"], "scene_finished": True,
                                         "scene_end_evaluation": {"reason": "剧终"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(
                state, stop_when=never_stop, max_beats=5, max_hops=24
            )
        self.assertTrue(result["runtime"]["scene_finished"])
        self.assertEqual(reason, "剧终")

    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_max_beats_none_is_current_behavior(self):
        # max_beats=None(默认)时行为与现状一致:一直推到 scene_finished。
        seq = iter([{"actor": "npc_a"}, {"actor": "npc_a"}])

        def _fake_resolve(state, deps, on_event=None):
            try:
                return {**state, "runtime": {**state["runtime"], "next_act": next(seq)}}
            except StopIteration:
                return {**state, "runtime": {**state["runtime"], "scene_finished": True,
                                             "scene_end_evaluation": {"reason": "自然结束"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(state, stop_when=never_stop, max_hops=24)
        self.assertTrue(result["runtime"]["scene_finished"])
        self.assertEqual(reason, "自然结束")

    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_stops_on_chapter_change(self):
        # stop_on_chapter_end=True 时,某拍 resolve 后 plot.chapter_id 变了(跨章)→ 提前停,
        # 返回"本章已结束"reason,不再继续下一章。
        seq = iter(["c1", "c2"])  # 第 2 拍把 chapter_id 从 c1 切到 c2

        def _fake_resolve(state, deps, on_event=None):
            return {
                **state,
                "plot": {**state["plot"], "chapter_id": next(seq)},
                "runtime": {**state["runtime"], "next_act": {"actor": "npc_a"}},
            }

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        state = {**state, "plot": {**state.get("plot", {}), "chapter_id": "c1"}}
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(
                state, stop_when=never_stop, max_beats=8, stop_on_chapter_end=True
            )
        self.assertEqual(result["plot"]["chapter_id"], "c2")
        self.assertIn("本章已结束", reason)
```

> 注:`_base_state` 若未含 `plot` 键,上面测试用 `{**state, "plot": {...}}` 显式补上;
> 实现读 `state["plot"].get("chapter_id", "")`,`_fake_resolve` 也写 `plot`,自洽。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_conversation_controller.py::AdvanceMaxBeatsTest -v`
Expected: FAIL — `TypeError: advance() got an unexpected keyword argument 'max_beats'`

- [ ] **Step 3: 实现 — 给 advance 加 max_beats 参数与拍计数**

修改 `Graph/conversation_controller.py` 的 `advance` 方法。改后整个方法应为:

```python
    def advance(
        self,
        state: dict[str, Any],
        *,
        stop_when: StopCondition,
        max_hops: int = 24,
        max_beats: int | None = None,
        stop_on_chapter_end: bool = False,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> tuple[dict[str, Any], str]:
        # 唯一一份推进循环。stop_when 决定何时停下交接:
        # Web 传 stop_at_player_turn,自动模式传 never_stop。
        # max_beats:推进的拍数上限(一次 resolve_story_turn = 一拍);达到即正常返回,
        # 供自动模式逐拍推进(never_stop 下不靠 stop_when 停,靠 max_beats 分批)。
        # stop_on_chapter_end:某拍跨了章(plot.chapter_id 变化)即正常返回,停在下一章开头,
        # 交前端等用户确认后再续章(chapter_finished 是一拍内瞬态,故检测 chapter_id 变化)。
        # 注意:never_stop 下 max_hops 是硬安全上限——须 >= max_beats,否则先撞 hops 抛错。
        hops = 0
        npc_acted = False
        beats_done = 0
        while hops < max_hops:
            hops += 1
            # _ensure_prepared_turn 内联:next_act 为空则补一个回合。
            if not state["runtime"].get("scene_finished", False) and state["runtime"].get("next_act") is None:
                state = prepare_chapter_turn(state, self._deps)
            if state["runtime"].get("scene_finished", False):
                reason = state["runtime"].get("scene_end_evaluation", {}).get("reason", "")
                return state, (reason or "当前场景已经结束。")
            next_act = state["runtime"].get("next_act")
            if next_act is None:
                return state, "当前没有新的自动后续动作。"
            if stop_when(state):
                if npc_acted:
                    return state, "场景角色动作已结算，等待玩家回应。"
                eligible = [
                    actor_id
                    for actor_id in state["runtime"].get("eligible_actors", [])
                    if actor_id != state["player"].get("controlled_character")
                ]
                return state, (
                    "等待玩家行动。当前仍有可响应角色在场：" + "、".join(eligible) + "。"
                    if eligible
                    else "等待玩家定义下一步行动。"
                )
            chapter_before = str(state["plot"].get("chapter_id", "") or "")
            state = resolve_story_turn(state, self._deps, on_event)
            npc_acted = True
            beats_done += 1
            if stop_on_chapter_end and str(state["plot"].get("chapter_id", "") or "") != chapter_before:
                return state, "本章已结束，等待确认后进入下一章。"
            if max_beats is not None and beats_done >= max_beats:
                return state, f"已自动推进 {beats_done} 拍。"
        raise RuntimeError("自动推进超过安全跳数，仍未到达稳定交接点。")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_conversation_controller.py -v`
Expected: PASS(原有 8 个 + 新增 4 个 = 12 个全过)

- [ ] **Step 5: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Graph/conversation_controller.py tests/test_conversation_controller.py
git commit -m "$(cat <<'EOF'
feat(conversation-controller): advance 增加 max_beats 拍数上限

自动模式用 never_stop 谓词,stop_when 永不触发;新增 max_beats 让 advance
推进固定拍数后正常返回(不抛错),供 Web 逐拍推进。默认 None 时行为与现状完全一致。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: WebGameSession 自动模式状态与开关

**Files:**
- Modify: `web_session.py`(`__init__` 加字段 `:191-205` 区域;import `:17-20`;新增方法)
- Test: `tests/test_web_session_auto_mode.py`(新建)

**背景:** `is_player_turn`(`Graph/beat_subgraph.py:37`)依赖 `player.enabled`;关掉它玩家回合就流向 `_resolve_agent_for_actor`(`Graph/dialogue_nodes.py:131`),后者读 `profile.agent_type` 选 agent。把玩家 profile `agent_type` 改 `"L1"` 就选中 `l1_actor_agent`。`CharacterRepository.update_field(actor_id, field, value)`(`CharacterRepository.py:46`)是单一写入口,直接写字段不重归一化。

- [ ] **Step 1: 写失败测试 — set_auto_mode 开/关/幂等**

新建 `tests/test_web_session_auto_mode.py`:

```python
import unittest

from session_bootstrap import PLAYER_CHARACTER_ID
from web_session import SessionConfig, WebGameSession


def _session():
    # heuristic 模式 + player_profile → 免 LLM/DB 起一个已初始化会话。
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.reset(player_profile={"name": "测试玩家"})
    return session


class SetAutoModeTest(unittest.TestCase):
    def test_enable_flips_enabled_and_upgrades_agent_type(self):
        session = _session()
        # 前置:玩家默认 enabled=True、agent_type=actor。
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
        session.set_auto_mode(True)
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "L1",
        )

    def test_disable_restores_enabled_and_agent_type(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(False)
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_enable_twice_is_idempotent_and_keeps_original_agent_type(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(True)  # 第二次 no-op,不能把已存的原值覆盖成 L1
        session.set_auto_mode(False)
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_disable_twice_is_noop(self):
        session = _session()
        session.set_auto_mode(False)  # 本就没开,no-op 不报错
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_web_session_auto_mode.py::SetAutoModeTest -v`
Expected: FAIL — `AttributeError: 'WebGameSession' object has no attribute 'set_auto_mode'`(或 `auto_mode`)

- [ ] **Step 3: 实现 — import、字段、set_auto_mode 三方法**

3a. 修改 `web_session.py` import(`:17-20`),给 `Graph.conversation_controller` 的 import 加上 `never_stop`。改后为:

```python
from Graph.conversation_controller import (
    ConversationController,
    never_stop,
    stop_at_player_turn,
)
```

3b. 在 `WebGameSession.__init__`(`:191`)里,`self.story_initialized = False` 那行之后、`self.character_profiles: dict...` 之前,加两个字段:

```python
        self.auto_mode = False
        self._player_saved_agent_type: str | None = None
        self._last_chapter_advanced = False
```

3c. 在 `apply_player_action`(`:412`)方法定义**之前**,插入三个新方法:

```python
    def set_auto_mode(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            if enabled and not self.auto_mode:
                self._enable_auto_unlocked()
            elif not enabled and self.auto_mode:
                self._disable_auto_unlocked()
            return self.serialize_state()

    def _enable_auto_unlocked(self) -> None:
        # 玩家角色升格 L1:存原 agent_type,改 profile.agent_type=L1(使调度选 l1_actor_agent),
        # 关掉 player.enabled 让玩家回合自动流向 actor 调度。
        player_id = self.config.player_character
        profile = self.deps.character_profiles.get(player_id, {})
        self._player_saved_agent_type = str(profile.get("agent_type", "actor") or "actor")
        self.deps.character_profiles.update_field(player_id, "agent_type", "L1")
        self.state = {
            **self.state,
            "player": {**self.state["player"], "enabled": False},
        }
        self.auto_mode = True
        self.last_handoff_reason = "自动模式已开启：玩家角色临时升格为核心角色自动演绎。"

    def _disable_auto_unlocked(self) -> None:
        # 还原玩家 agent_type 与 enabled;下一个玩家回合 is_player_turn 恢复 True,重新等输入。
        player_id = self.config.player_character
        restored = self._player_saved_agent_type or "actor"
        self.deps.character_profiles.update_field(player_id, "agent_type", restored)
        self._player_saved_agent_type = None
        self.state = {
            **self.state,
            "player": {**self.state["player"], "enabled": True},
        }
        self.auto_mode = False
        self.last_handoff_reason = "自动模式已关闭：下一个玩家回合恢复等待输入。"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_web_session_auto_mode.py::SetAutoModeTest -v`
Expected: PASS(4 个全过)

- [ ] **Step 5: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add web_session.py tests/test_web_session_auto_mode.py
git commit -m "$(cat <<'EOF'
feat(web-session): set_auto_mode 开关——玩家角色临时升格 L1

开启自动:存原 agent_type、改玩家 profile agent_type=L1、player.enabled=False,
使玩家回合自动流向 l1_actor_agent 演绎。关闭:还原两者,下一个玩家回合恢复等待。
开/关幂等,避免重复覆盖丢失原值。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: WebGameSession.auto_step 逐拍推进

**Files:**
- Modify: `web_session.py`(在 Task 2 新增的三方法之后追加 `auto_step`)
- Test: `tests/test_web_session_auto_mode.py`(追加类)

**背景:** `auto_step` 是前端轮询入口。调 `self._controller.advance(state, stop_when=never_stop, max_beats=...)` 推进固定拍数。入口校验沿用 `apply_player_action` 语义(未初始化/场景已结束报错),额外校验"自动模式未开启"。

- [ ] **Step 1: 写失败测试 — auto_step 参数透传 + 入口校验**

在 `tests/test_web_session_auto_mode.py` 末尾追加(`if __name__` 之前;文件顶部 import 加 `from unittest.mock import patch`):

```python
class AutoStepTest(unittest.TestCase):
    def test_auto_step_calls_advance_with_never_stop_and_max_beats(self):
        session = _session()
        session.set_auto_mode(True)
        captured = {}

        def _fake_advance(state, *, stop_when, max_beats=None, max_hops=24, stop_on_chapter_end=False, on_event=None):
            captured["stop_when"] = stop_when
            captured["max_beats"] = max_beats
            captured["stop_on_chapter_end"] = stop_on_chapter_end
            return state, "已自动推进 2 拍。"

        with patch.object(session._controller, "advance", _fake_advance):
            result = session.auto_step(max_beats=2)

        from Graph.conversation_controller import never_stop
        self.assertIs(captured["stop_when"], never_stop)
        self.assertEqual(captured["max_beats"], 2)
        self.assertTrue(captured["stop_on_chapter_end"])
        self.assertEqual(result["handoff_reason"], "已自动推进 2 拍。")

    def test_auto_step_sets_chapter_paused_when_chapter_changes(self):
        # advance 返回后 chapter_id 变了 → serialize_state 的 chapter_paused 为真。
        session = _session()
        session.set_auto_mode(True)
        original_chapter = str(session.state["plot"].get("chapter_id", "") or "")

        def _fake_advance(state, *, stop_when, max_beats=None, max_hops=24, stop_on_chapter_end=False, on_event=None):
            bumped = {**state, "plot": {**state["plot"], "chapter_id": original_chapter + "-next"}}
            return bumped, "本章已结束，等待确认后进入下一章。"

        with patch.object(session._controller, "advance", _fake_advance):
            result = session.auto_step(max_beats=4)
        self.assertTrue(result["chapter_paused"])

    def test_auto_step_raises_when_auto_not_enabled(self):
        session = _session()
        with self.assertRaises(RuntimeError):
            session.auto_step()

    def test_auto_step_raises_when_not_initialized(self):
        # 不给 player_profile → 未初始化。手动置 auto_mode 以越过"未开自动"校验,
        # 断言"未初始化"校验先命中。
        session = WebGameSession(SessionConfig(mode="heuristic"))
        session.auto_mode = True
        with self.assertRaises(RuntimeError):
            session.auto_step()

    def test_auto_step_raises_when_scene_finished(self):
        session = _session()
        session.set_auto_mode(True)
        session.state = {
            **session.state,
            "runtime": {**session.state["runtime"], "scene_finished": True},
        }
        with self.assertRaises(RuntimeError):
            session.auto_step()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_web_session_auto_mode.py::AutoStepTest -v`
Expected: FAIL — `AttributeError: 'WebGameSession' object has no attribute 'auto_step'`

- [ ] **Step 3: 实现 auto_step**

在 `web_session.py` 的 `_disable_auto_unlocked` 之后、`apply_player_action` 之前追加:

```python
    def auto_step(self, max_beats: int = 4) -> dict[str, Any]:
        with self._lock:
            if not self.story_initialized:
                raise RuntimeError("请先初始化场景，再启动自动推进。")
            if not self.auto_mode:
                raise RuntimeError("自动模式未开启。")
            if self.state["runtime"].get("scene_finished", False):
                raise RuntimeError("当前场景已经结束，请重置后继续。")
            chapter_before = str(self.state["plot"].get("chapter_id", "") or "")
            self.state, self.last_handoff_reason = self._controller.advance(
                self.state,
                stop_when=never_stop,
                max_beats=max_beats,
                max_hops=max_beats + 8,
                stop_on_chapter_end=True,
            )
            # 本批是否因跨章而停:chapter_id 变了即刚进下一章开头,前端据此暂停等确认。
            self._last_chapter_advanced = (
                str(self.state["plot"].get("chapter_id", "") or "") != chapter_before
            )
            self._maybe_index_finished_scene_unlocked()
            return self.serialize_state()
```

**同时**在 `serialize_state` 的返回 dict 里(`chapter_finished` 那一行附近,`web_session.py:708`)
补一个 `chapter_paused` 字段——章节暂停 = 本批跨了章 ∧ 仍在自动模式:

```python
            "chapter_paused": bool(getattr(self, "_last_chapter_advanced", False)) and self.auto_mode,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest tests/test_web_session_auto_mode.py -v`
Expected: PASS(SetAutoModeTest 4 + AutoStepTest 5 = 9 个全过)

- [ ] **Step 5: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add web_session.py tests/test_web_session_auto_mode.py
git commit -m "$(cat <<'EOF'
feat(web-session): auto_step 逐拍推进入口

前端轮询入口:advance(never_stop, max_beats) 推进固定拍数;max_hops=max_beats+8
留安全余量。入口校验沿用 apply_player_action 语义(未初始化/未开自动/场景已结束报错)。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: web_server 路由 /api/auto 与 /api/auto/step

**Files:**
- Modify: `web_server.py:160-206`(`_handle_post_api_request`)
- Test: 无独立单测(HTTP handler 依赖 socket,现有代码库无 handler 级单测;经 Task 5 前端手测覆盖)

**背景:** `_handle_post_api_request`(`web_server.py:160`)按 `path` 分发,返回 `(HTTPStatus, payload)`;`RuntimeError` 会被 `do_POST`(`:59`)捕获转 400。沿用同一模式加两分支。

- [ ] **Step 1: 加两路由分支**

在 `web_server.py` 的 `_handle_post_api_request` 里,`if path == "/api/action":`(`:173`)分支**之后**插入:

```python
        if path == "/api/auto":
            enabled = bool(payload.get("enabled", False))
            return HTTPStatus.OK, self.server.session.set_auto_mode(enabled)
        if path == "/api/auto/step":
            raw_beats = payload.get("max_beats", 4)
            try:
                max_beats = int(raw_beats)
            except (TypeError, ValueError):
                raise RuntimeError("`max_beats` 必须是整数。") from None
            max_beats = max(1, min(8, max_beats))
            return HTTPStatus.OK, self.server.session.auto_step(max_beats=max_beats)
```

- [ ] **Step 2: 冒烟验证 — import 与路由方法可加载**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -c "import web_server; print('ok')"`
Expected: 输出 `ok`,无 SyntaxError/ImportError

- [ ] **Step 3: 冒烟验证 — 全量测试仍绿(确认没破坏 import 链)**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest -q`
Expected: 全绿(299 基线 + 本轮新增 = 312 全过)

- [ ] **Step 4: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add web_server.py
git commit -m "$(cat <<'EOF'
feat(web-server): /api/auto 开关与 /api/auto/step 逐拍推进路由

/api/auto {enabled} → set_auto_mode;/api/auto/step {max_beats} → auto_step,
max_beats 收窄 1~8 防滥用。沿用 do_POST 的 RuntimeError→400 错误处理。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 前端自动开关 + 轮询

**Files:**
- Modify: `frontend/app.js`(API 表 `:1-10` 附近;新增轮询逻辑;禁用态)
- Modify: `frontend/index.html`(动作输入区附近加开关)

**背景:** app.js 是 vanilla JS SPA。`API` 对象(`:1-10`)集中列 endpoint。已有 `isBusy` 禁用逻辑(`:610` 等)与 `render(state)` 渲染。手动动作走 `streamAction(API.action, ...)`(`:1612`)。本 Task 加一个开关 checkbox,开启后 `setInterval` 轮询 `/api/auto/step`,渲染返回 state;`scene_finished` 或关开关时停轮询。

> 注:前端无自动化测试(仓库现状)。本 Task 的"测试"是手动浏览器验证(Step 6),这是本计划唯一无法用 pytest 覆盖的部分,须显式手测。

- [ ] **Step 1: API 表加两条 endpoint**

在 `frontend/app.js` 顶部 `API` 对象里(`load: "/api/load",` 之后)加:

```javascript
  auto: "/api/auto",
  autoStep: "/api/auto/step",
```

- [ ] **Step 2: index.html 加自动开关 UI**

在 `frontend/index.html` 找到玩家动作输入区(含"背包"按钮 `toggleBackpackButton` 的容器,`grep -n toggleBackpackButton frontend/index.html` 定位)。在该容器内、输入框附近加一个开关 + 一个"继续下一章"按钮(默认隐藏):

```html
        <label class="auto-toggle" title="开启后玩家角色自动演绎，逐拍推进">
          <input type="checkbox" id="autoModeToggle" />
          <span>自动</span>
        </label>
        <button type="button" id="continueChapterButton" style="display: none;">继续下一章</button>
```

(样式复用现有类;若无合适类,`class="auto-toggle"` 可留待样式表补,不阻塞功能。)

- [ ] **Step 3: app.js 拿到开关元素并加状态变量**

在 app.js 顶部元素获取区(`toggleBackpackButton` 那类 `getElementById` 附近,`:26`)加:

```javascript
const autoModeToggle = document.getElementById("autoModeToggle");
const continueChapterButton = document.getElementById("continueChapterButton");
```

在模块级状态变量区(靠近 `let sidebarMode` 等声明处)加:

```javascript
let autoTimer = null;
let autoBusy = false;
let chapterPaused = false;
```

- [ ] **Step 4: 实现开关处理与轮询函数**

在 app.js 里(靠近其他事件绑定/函数定义处,如 `hintButtons.forEach` 绑定附近)加:

```javascript
function startAutoPolling() {
  if (autoTimer === null) {
    autoTimer = setInterval(pollAutoStep, 1500);
  }
}

function stopAutoPolling() {
  if (autoTimer !== null) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
}

async function pollAutoStep() {
  if (autoBusy || chapterPaused) return;
  if (latestState?.scene_finished) {
    stopAutoMode();
    return;
  }
  autoBusy = true;
  try {
    const response = await fetch(API.autoStep, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_beats: 4 }),
    });
    if (!response.ok) throw new Error(`auto step failed: ${response.status}`);
    const state = await response.json();
    render(state);
    if (state?.scene_finished) {
      stopAutoMode();
    } else if (state?.chapter_paused) {
      // 章节结束:停轮询但保持自动开关,等用户点"继续下一章"。
      chapterPaused = true;
      stopAutoPolling();
      continueChapterButton.style.display = "";
    }
  } catch (err) {
    console.error(err);
    stopAutoMode();
  } finally {
    autoBusy = false;
  }
}

async function startAutoMode() {
  const response = await fetch(API.auto, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: true }),
  });
  if (!response.ok) {
    autoModeToggle.checked = false;
    return;
  }
  render(await response.json());
  startAutoPolling();
}

async function stopAutoMode() {
  stopAutoPolling();
  chapterPaused = false;
  continueChapterButton.style.display = "none";
  if (autoModeToggle.checked) autoModeToggle.checked = false;
  try {
    const response = await fetch(API.auto, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
    });
    if (response.ok) render(await response.json());
  } catch (err) {
    console.error(err);
  }
}

autoModeToggle.addEventListener("change", () => {
  if (autoModeToggle.checked) {
    startAutoMode();
  } else {
    stopAutoMode();
  }
});

continueChapterButton.addEventListener("click", () => {
  // 用户确认续章:清暂停态、隐藏按钮、重启轮询(自动开关始终未动)。
  chapterPaused = false;
  continueChapterButton.style.display = "none";
  startAutoPolling();
});
```

> 若 app.js 的渲染函数名不是 `render`、当前 state 变量名不是 `latestState`,以文件实际为准(`grep -n "function render\|latestState\|function applyState\|renderState" frontend/app.js` 确认后替换)。

- [ ] **Step 5: 冒烟 — JS 语法检查**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && node --check frontend/app.js && echo "JS OK"`
Expected: 输出 `JS OK`,无语法错误。(若无 node,跳过并在浏览器控制台确认无报错。)

- [ ] **Step 6: 手动浏览器验证(必做,前端无自动化测试)**

1. 启动服务:`cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 web_demo.py`(或 `web_server.py` 的实际启动入口,`grep -n "__main__\|def main\|run_server\|HTTPServer" web_demo.py web_server.py` 确认)。
2. 浏览器打开本地页面,创建角色 → 初始化场景 → 到玩家回合。
3. 勾选"自动"开关。**预期**:输入框/提示按钮禁用;每 ~1.5s 历史新增角色回合(含玩家角色由 L1 演绎的发言);`handoff_reason` 显示"已自动推进 N 拍"或"自动模式已开启"。
4. 取消勾选。**预期**:轮询停止;`handoff_reason` 显示"自动模式已关闭";下一个玩家回合恢复等待输入,可手动提交动作。
5. 重新开启并让其跑到**章节结束**。**预期**:章节切换时自动停轮询,但"自动"开关**保持勾选**;"继续下一章"按钮出现;`handoff_reason` 显示"本章已结束"。
6. 点"继续下一章"。**预期**:按钮隐藏、轮询重启,直接进入下一章自动演绎,无需重开开关。
7. 让其跑到场景/整局结束。**预期**:`scene_finished` 时自动停轮询、开关复位。

若任一步不符,记录现象并回到对应 Task 修复。

- [ ] **Step 7: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add frontend/app.js frontend/index.html
git commit -m "$(cat <<'EOF'
feat(frontend): 自动模式开关 + 逐拍轮询

勾选"自动"→ POST /api/auto 开启 → setInterval 每 1.5s 轮询 /api/auto/step 推 4 拍并渲染;
scene_finished 或取消勾选 → 停轮询 + POST /api/auto 关闭。单飞防重入,失败自动停。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 全量回归

**Files:** 无改动,仅验证。

- [ ] **Step 1: 全量测试**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python3 -m pytest -q`
Expected: 全绿。基线 299 + Task1(4)+ Task2(4)+ Task3(5)= 312 全过。

- [ ] **Step 2: 确认无未提交改动**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && git status --short`
Expected: 干净(所有改动已在前 5 个 Task 提交)。

---

## 自检结果

**1. Spec 覆盖:**
- §3.1 advance max_beats → Task 1 ✅
- §3.2 set_auto_mode / _enable/_disable → Task 2 ✅;auto_step → Task 3 ✅
- §3.3 web_server 两路由 → Task 4 ✅
- §3.4 前端开关 + 轮询 → Task 5 ✅
- §6 测试策略 → controller max_beats + 章节停止(Task1 4条)+ set_auto_mode(Task2 4条)+ auto_step + 章节暂停(Task3 5条)✅
- 章节边界停止(用户 2026-08-17 追加需求)→ advance `stop_on_chapter_end`(Task1)+ auto_step 传参 + `chapter_paused`(Task3)+ 前端"继续下一章"(Task5)✅
- §5 存档半自动态 → 按 spec 本轮策略"靠约定 + _disable 还原",不改存档链路,无独立 Task(符合 spec)✅

**2. 占位符扫描:** 无 TBD/TODO;每个改代码的 Step 都给了完整代码块。前端 Task 5 对 `render`/`latestState` 变量名给了"以实际为准"的确认命令(因未逐行读 app.js 1794 行),非占位符而是执行期核实指令。

**3. 类型一致性:** `advance` 签名 `max_beats: int | None = None` 在 Task1 定义、Task3 调用一致;`set_auto_mode(enabled: bool)`、`auto_step(max_beats: int = 4)`、`update_field(actor_id, field, value)`(已核实源码)、`never_stop`/`stop_at_player_turn`(已存在)全部一致。
