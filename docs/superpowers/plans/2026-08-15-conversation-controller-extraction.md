# ConversationController 提取 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `web_session.py` 里的会话推进控制逻辑抽成 mode-agnostic 的 `Graph/conversation_controller.py`,`WebGameSession` 变薄,并为将来自动写小说入口预留 `never_stop` 复用接口。

**Architecture:** 无状态 `ConversationController`(持 deps 引用,state 传入传出),核心是 `advance(state, *, stop_when, max_hops, on_event) -> (state, reason)` 一份推进循环,靠停止条件谓词区分 Web(到玩家回合停)与自动(永不停,靠 scene_finished 自然终止)。工具路由留在 WebGameSession,但推进委托 controller。

**Tech Stack:** Python 3.12+(TypedDict GameState、`from __future__ import annotations`)、unittest、pytest。运行 `python -m pytest -q`。基线 172 全绿。

**关联 spec:** `docs/superpowers/specs/2026-08-15-conversation-controller-extraction-design.md`

---

## 背景速览(实施者必读)

`web_session.py` 现有三个私有方法承载推进控制,本轮搬进 controller:
- `_prime_opening_player_turn(state) -> state`(:598-640):纯 state→state,开场设 `next_act` 交给玩家;无 player_actor 时 `next_act=None`。
- `_ensure_prepared_turn()`(:642-644):`next_act is None` 时调 `prepare_chapter_turn` 补回合。
- `_advance_until_player_turn(max_hops=24, on_event=None) -> str`(:646-677):推进循环,停在玩家回合返回 handoff reason。

关键事实:
- `is_player_turn` 从 `Graph.beat_subgraph` 导入(web_session.py:17 已有此 import)。
- `resolve_story_turn`、`prepare_chapter_turn` 从 `Graph.builder` 导入(web_session.py:11-16 已有)。
- **无任何测试引用这三个私有方法**(已 grep 确认)。现有 web_session 测试经 `apply_player_action` 间接覆盖,行为等价即通过。
- **两种 mode 的 `_initialize_story` 行为不同**(:587-596):agent-first/live 只 prime 不 advance;heuristic 先 `initialize_story_session` 再 advance。收窄时必须逐一对应保留,不可统一。
- `self.deps` 在 `_reload_dependencies`(:530-585)首次赋值;controller 在该方法末尾构造,保证每次 deps 重建后 controller 指向新 deps。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `Graph/conversation_controller.py`(新建) | `StopCondition` 类型别名 + `stop_at_player_turn`/`never_stop` 谓词 + `ConversationController` 类(`prime_opening_turn` + `advance`) |
| `web_session.py`(修改) | 删 3 私有方法;`_reload_dependencies` 末尾构造 `self._controller`;`_initialize_story`/`apply_player_action`/`apply_player_action_streaming`/`_maybe_handle_player_intent_plan_unlocked` 改委托调用 |
| `tests/test_conversation_controller.py`(新建) | controller 单测(prime/advance/never_stop/max_hops/on_event 透传) |

---

## Task 1: 新建 ConversationController 模块 + 单测

**Files:**
- Create: `Graph/conversation_controller.py`
- Create: `tests/test_conversation_controller.py`

### 关于测试用的 fake

controller 的 `advance` 内部调 `prepare_chapter_turn(state, deps)` 和 `resolve_story_turn(state, deps, on_event)`(从 `Graph.builder` 导入的模块级函数),以及 `is_player_turn(state)`(从 `Graph.beat_subgraph`)。单测用 `unittest.mock.patch` 打桩这三个模块级函数,构造纯字典 state,不碰真实 deps/LLM。`deps` 传 `object()` 占位即可(controller 只把它透传给被 patch 掉的函数)。

`is_player_turn` 的桩:让它按 `state["runtime"]["next_act"]["actor"] == "player"` 判断(与真实语义一致但简化)。

- [ ] **Step 1: 写模块骨架(先让 import 可用)**

创建 `Graph/conversation_controller.py`:

```python
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from Graph.beat_subgraph import is_player_turn
from Graph.builder import prepare_chapter_turn, resolve_story_turn

if TYPE_CHECKING:
    from Graph.dependencies import GraphDependencies
    from GameState import GameState

# StopCondition:给定当前 state,判断是否该停下把控制权交出去。
StopCondition = Callable[[dict[str, Any]], bool]


def stop_at_player_turn(state: dict[str, Any]) -> bool:
    # Web 用:推进到玩家回合就停,把控制权交回给玩家。
    return is_player_turn(state)


def never_stop(state: dict[str, Any]) -> bool:
    # 自动写小说用:永不主动停,只靠 scene_finished 自然终止(见 advance 循环)。
    return False


class ConversationController:
    """mode-agnostic 会话推进控制器。

    无状态:持 deps 只读引用,state 每次传入、返回新的,
    让 Web 与将来的自动入口各自管理 state 生命周期。
    """

    def __init__(self, deps: "GraphDependencies") -> None:
        self._deps = deps

    def prime_opening_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        # 开场把首回合交给玩家;无 player_actor(自动模式)时 next_act=None,自然退化。
        player_actor = str(state["player"].get("controlled_character", "") or "").strip()
        suppressed = {
            str(actor_id).strip()
            for actor_id in state["scene"].get("suppressed", [])
            if str(actor_id).strip()
        }
        eligible_actors = [
            str(actor_id).strip()
            for actor_id in state["scene"].get("on_stage", [])
            if str(actor_id).strip() and str(actor_id).strip() not in suppressed
        ]
        if player_actor and player_actor not in eligible_actors:
            eligible_actors.insert(0, player_actor)
        target = str(state["scene"].get("focus_character", "") or "").strip()
        if target == player_actor:
            target = ""
        if not target:
            target = next((actor_id for actor_id in eligible_actors if actor_id != player_actor), "")
        next_act = (
            {
                "actor": player_actor,
                "mode": "speak",
                "target": target or None,
                "motivation": "开场先交给玩家，让玩家定义第一步，再进入导演调度。",
                "content": "",
            }
            if player_actor
            else None
        )
        return {
            **state,
            "runtime": {
                **state["runtime"],
                "eligible_actors": eligible_actors,
                "pending_beat_actors": [],
                "beat_fallback_turns_remaining": 0,
                "narration_queue": [],
                "next_act": next_act,
                "resolved_act": None,
                "scene_end_evaluation": None,
            },
        }

    def advance(
        self,
        state: dict[str, Any],
        *,
        stop_when: StopCondition,
        max_hops: int = 24,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> tuple[dict[str, Any], str]:
        # 唯一一份推进循环。stop_when 决定何时停下交接:
        # Web 传 stop_at_player_turn,自动模式传 never_stop。
        # 注意:never_stop 下 max_hops 是硬安全上限——若场景 NPC 回合可能超 max_hops,
        # 自动入口须传更大的 max_hops。
        hops = 0
        npc_acted = False
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
            state = resolve_story_turn(state, self._deps, on_event)
            npc_acted = True
        raise RuntimeError("自动推进超过安全跳数，仍未到达稳定交接点。")
```

> 注:`_ensure_prepared_turn` 原实现有 `self.story_initialized` 判定;controller 里去掉它——advance 只在已初始化后被调用(Web 侧入口已校验 `story_initialized`),且 `scene_finished` 判定已覆盖终止,无需再查 initialized。行为等价。

- [ ] **Step 2: 写单测**

创建 `tests/test_conversation_controller.py`:

```python
import unittest
from unittest.mock import patch

from Graph.conversation_controller import (
    ConversationController,
    never_stop,
    stop_at_player_turn,
)


def _fake_is_player_turn(state):
    next_act = state["runtime"].get("next_act") or {}
    return next_act.get("actor") == "player"


def _base_state(next_act):
    return {
        "player": {"controlled_character": "player"},
        "scene": {"on_stage": ["player", "npc_a"], "suppressed": [], "focus_character": ""},
        "runtime": {"next_act": next_act, "eligible_actors": ["player", "npc_a"], "scene_finished": False},
    }


class PrimeOpeningTurnTest(unittest.TestCase):
    def test_prime_sets_player_next_act(self):
        controller = ConversationController(deps=object())
        state = _base_state(None)
        primed = controller.prime_opening_turn(state)
        self.assertEqual(primed["runtime"]["next_act"]["actor"], "player")

    def test_prime_no_player_yields_none_next_act(self):
        controller = ConversationController(deps=object())
        state = _base_state(None)
        state["player"]["controlled_character"] = ""  # 自动模式:无玩家角色
        primed = controller.prime_opening_turn(state)
        self.assertIsNone(primed["runtime"]["next_act"])


class AdvanceStopAtPlayerTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_stops_when_already_player_turn(self):
        # 一开始就是玩家回合、且无 NPC 先行动 → 立即停,提示等待玩家。
        controller = ConversationController(deps=object())
        state = _base_state({"actor": "player"})
        result, reason = controller.advance(state, stop_when=stop_at_player_turn)
        self.assertEqual(result["runtime"]["next_act"]["actor"], "player")
        self.assertIn("等待玩家", reason)

    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_runs_npc_then_stops_at_player(self):
        # 先 NPC 回合 → resolve 后变玩家回合 → 停并提示已结算。
        calls = {"n": 0}

        def _fake_resolve(state, deps, on_event=None):
            calls["n"] += 1
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "player"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(state, stop_when=stop_at_player_turn)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result["runtime"]["next_act"]["actor"], "player")
        self.assertIn("已结算", reason)


class AdvanceNeverStopTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_never_stop_runs_until_scene_finished(self):
        # 自动模式:连跑 NPC 回合,即便中途是玩家回合也不停,直到 scene_finished。
        seq = iter([
            {"actor": "player"},   # 第1跳:玩家回合,但 never_stop 不停,继续 resolve
            {"actor": "npc_a"},    # 第2跳:NPC 回合
        ])

        def _fake_resolve(state, deps, on_event=None):
            try:
                nxt = next(seq)
                return {**state, "runtime": {**state["runtime"], "next_act": nxt}}
            except StopIteration:
                return {**state, "runtime": {**state["runtime"], "scene_finished": True,
                                             "scene_end_evaluation": {"reason": "剧终"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(state, stop_when=never_stop, max_hops=24)
        self.assertTrue(result["runtime"]["scene_finished"])
        self.assertEqual(reason, "剧终")


class AdvanceMaxHopsTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_raises_when_exceeds_max_hops(self):
        # 永不终止的 NPC 回合 → 超 max_hops 抛错。
        def _fake_resolve(state, deps, on_event=None):
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "npc_a"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            with self.assertRaises(RuntimeError):
                controller.advance(state, stop_when=never_stop, max_hops=3)


class AdvanceOnEventTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_on_event_passed_to_resolve(self):
        # 断言 advance 把 on_event 原样透传给 resolve_story_turn。
        seen = {}

        def _fake_resolve(state, deps, on_event=None):
            seen["cb"] = on_event
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "player"}}}

        cb = lambda entry: None
        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            controller.advance(state, stop_when=stop_at_player_turn, on_event=cb)
        self.assertIs(seen["cb"], cb)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 跑测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_conversation_controller.py -q`
Expected: PASS(8 个测试全绿)

> 若 `prime_opening_turn` 用例报 KeyError,核对 `_base_state` 是否含 `player`/`scene`/`runtime` 三键——上面构造已含。
> 若 `never_stop` 用例未到 scene_finished 就停,检查 advance 里 `stop_when(state)` 分支——`never_stop` 恒返回 False,不该进停止分支。

- [ ] **Step 4: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Graph/conversation_controller.py tests/test_conversation_controller.py
git commit -m "$(cat <<'EOF'
feat(controller): 新建 ConversationController + 停止条件谓词

无状态推进控制器:advance(state, stop_when) 一份循环,
Web 用 stop_at_player_turn、自动模式用 never_stop;附单测覆盖
prime/推进/never_stop 跑到终局/max_hops 抛错/on_event 透传。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: web_session 接线收窄 + 全量回归

**Files:**
- Modify: `web_session.py`(import、`_reload_dependencies` 末尾、`_initialize_story`、`apply_player_action`、`apply_player_action_streaming`、`_maybe_handle_player_intent_plan_unlocked`;删 `_prime_opening_player_turn`/`_ensure_prepared_turn`/`_advance_until_player_turn`)

- [ ] **Step 1: 加 import**

`web_session.py` 在 `from Graph.beat_subgraph import is_player_turn`(:17)之后加一行:

```python
from Graph.conversation_controller import (
    ConversationController,
    stop_at_player_turn,
)
```

- [ ] **Step 2: `_reload_dependencies` 末尾构造 controller**

`_reload_dependencies` 方法(:530-585)的最后一行(`warm_model_clients(...)` 那句)**之后**、方法结束前,加:

```python
        self._controller = ConversationController(self.deps)
```

> 缩进为方法体内(8 空格)。该方法每次重建 deps 都会跑,保证 controller 恒指向最新 deps。

- [ ] **Step 3: 收窄 `_initialize_story`**

把 `_initialize_story`(:587-596)整体替换为(保留两 mode 的行为差异):

```python
    def _initialize_story(self) -> None:
        if self.config.mode in {"agent-first", "live"}:
            self.state = prepare_story_setup(self.state, self.deps)
            self.state = self._controller.prime_opening_turn(self.state)
            self.story_initialized = True
            self.last_handoff_reason = "开场交接完成，等待玩家定义第一步行动。"
            return
        self.state = initialize_story_session(self.state, self.deps)
        self.story_initialized = True
        self.state, self.last_handoff_reason = self._controller.advance(
            self.state, stop_when=stop_at_player_turn
        )
```

- [ ] **Step 4: 收窄 `apply_player_action`**

把 `apply_player_action`(:368-383)方法体里的两处 `self._advance_until_player_turn()` 调用改为 controller 委托。整体替换为:

```python
    def apply_player_action(self, raw_input: str) -> dict[str, Any]:
        with self._lock:
            if not self.story_initialized:
                raise RuntimeError("请先初始化场景，再提交玩家动作。")
            if self.state["runtime"].get("scene_finished", False):
                raise RuntimeError("当前场景已经结束，请重置后继续。")
            self.state, _ = self._controller.advance(self.state, stop_when=stop_at_player_turn)
            if not is_player_turn(self.state):
                raise RuntimeError("当前还没有轮到玩家行动。")
            tool_response = self._maybe_handle_player_intent_plan_unlocked(raw_input)
            if tool_response is not None:
                return tool_response
            self._player_interface.push_action(raw_input)
            self.state = resolve_story_turn(self.state, self.deps)
            self.state, self.last_handoff_reason = self._controller.advance(
                self.state, stop_when=stop_at_player_turn
            )
            return self.serialize_state()
```

- [ ] **Step 5: 收窄 `apply_player_action_streaming`**

把 `apply_player_action_streaming`(:385-421)里的两处 `self._advance_until_player_turn(...)` 改为 controller 委托。定位方法末尾的:
```python
            self._player_interface.push_action(raw_input)
            self.state = resolve_story_turn(self.state, self.deps, _emit)
            self.last_handoff_reason = self._advance_until_player_turn(on_event=_emit)
            return self.serialize_state()
```
以及方法开头的 `self._advance_until_player_turn()`(:401)。分别替换:

方法开头(:401 那行)`self._advance_until_player_turn()` →
```python
            self.state, _ = self._controller.advance(self.state, stop_when=stop_at_player_turn)
```

方法末尾三行 →
```python
            self._player_interface.push_action(raw_input)
            self.state = resolve_story_turn(self.state, self.deps, _emit)
            self.state, self.last_handoff_reason = self._controller.advance(
                self.state, stop_when=stop_at_player_turn, on_event=_emit
            )
            return self.serialize_state()
```

- [ ] **Step 6: 收窄 `_maybe_handle_player_intent_plan_unlocked` 内的推进**

在 `_maybe_handle_player_intent_plan_unlocked`(:423-469)里,非工具步骤分支(:461-463)的三行:
```python
                self._player_interface.push_action(action_text)
                self.state = resolve_story_turn(self.state, self.deps)
                self.last_handoff_reason = self._advance_until_player_turn()
```
替换为:
```python
                self._player_interface.push_action(action_text)
                self.state = resolve_story_turn(self.state, self.deps)
                self.state, self.last_handoff_reason = self._controller.advance(
                    self.state, stop_when=stop_at_player_turn
                )
```

> 工具路由整体仍留在 WebGameSession(依赖 Web-only 的 player_command_tools),只是推进委托 controller。

- [ ] **Step 7: 删三个被搬迁的私有方法**

删除 `web_session.py` 中的 `_prime_opening_player_turn`(原 :598-640)、`_ensure_prepared_turn`(原 :642-644)、`_advance_until_player_turn`(原 :646-677)三个方法定义整体(它们的逻辑已在 controller)。

> 删除后确认全文件不再有 `_advance_until_player_turn`/`_prime_opening_player_turn`/`_ensure_prepared_turn` 的定义或调用:
> `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && grep -n "_advance_until_player_turn\|_prime_opening_player_turn\|_ensure_prepared_turn" web_session.py`
> Expected: 无输出。

- [ ] **Step 8: 全量回归**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest -q`
Expected: PASS(基线 172 + Task 1 新增 8 = 180 全绿)

> 若 web_session 相关测试报错,先核对 Step 3 的 mode 分支是否与原逻辑一致(agent-first 只 prime、heuristic 才 advance),以及 `self._controller` 是否在测试构造的 session 里已就绪(应在 `_reload_dependencies` 末尾)。

- [ ] **Step 9: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add web_session.py
git commit -m "$(cat <<'EOF'
refactor(web): 会话推进委托 ConversationController,删三私有方法

_initialize_story/apply_player_action[_streaming]/工具路由的推进改调
controller.advance(stop_when=stop_at_player_turn);删除搬迁进 controller 的
_prime_opening_player_turn/_ensure_prepared_turn/_advance_until_player_turn。
行为等价,全量回归全绿。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## 自审记录

- **Spec 覆盖**:§3.1 谓词→Task1 Step1;§3.2 controller→Task1 Step1;§3.3 web 收窄(init/apply/streaming/工具路由)→Task2 Step2-6;删 3 方法→Task2 Step7;§3.4 never_stop 接口→Task1 `never_stop` 测试;§5 测试 5 类→Task1 Step2(prime×2/stop_at_player×2/never_stop/max_hops/on_event);§4 错误处理→advance 的 max_hops 抛错 + scene_finished 正常返回。无遗漏。
- **占位符**:无 TBD/TODO;所有代码步含完整代码块。
- **类型/签名一致**:`advance(state, *, stop_when, max_hops=24, on_event=None) -> tuple` 在 Task1 定义、Task2 全部调用点签名一致;`prime_opening_turn(state) -> dict` 一致;`stop_at_player_turn`/`never_stop` 命名前后一致。
- **行为差异保留**:`_initialize_story` 两 mode 差异(agent-first 只 prime、heuristic advance)在 Task2 Step3 精确保留。
