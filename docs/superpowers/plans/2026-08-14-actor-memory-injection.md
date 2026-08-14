# 角色三层记忆注入系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建只读的 `Memory/` 包,提供一个「记忆工厂」(`ActorMemoryProvider`),把角色三层记忆(短期=在场过滤 / 长期=复用压缩产物 / 检索=占位)组装成收窄的只读 DTO(`ActorMemoryContext`)。

**Architecture:** 工厂只读,不落任何存储。短期层从 `state["history"]` 按「角色当时是否在场」过滤最近 3 轮;为支持逐条在场判定,给 `HistoryItem` 增补 `on_stage`/`location_id` 逐条快照(在三处写 history 的地方补记)。长期层直接读 `state["characters"][actor_id]["memory"]` 里已由现有压缩机制维护的字段。检索层只定接口、恒返回空列表。**本轮不接入 actor 回合**(决策 E 待定),仅建包 + 补记快照 + 全量单测。

**Tech Stack:** Python 3.12(TypedDict / frozen dataclass / typing.Protocol),unittest + pytest。测试以 `python -m pytest` 运行,基线 153 个用例全绿。

**已锁定决策:**
- **A**:写 history 时给每条 `HistoryItem` 补记 `on_stage`/`location_id` 快照;不做旧数据回填(当前环境无历史数据)。
- **D**:短期在场过滤默认严格 `on_stage`;`location` 作为可配置放宽项(过滤函数 `granularity` 参数,默认 `"on_stage"`)。
- **B/C/E** 待定:长期节奏 N 本轮采纯复用(不做 N 轮兜底);检索 query 本轮不涉及(占位返回空);推广范围本轮只建包,不接入任何 agent 路径。

---

## 文件结构

- 新建 `Memory/__init__.py` — 包出口,re-export DTO / Provider / 默认实现 / 过滤器。
- 新建 `Memory/context.py` — `ActorMemoryContext` frozen dataclass(只读投影 DTO)+ `LongTermView`。
- 新建 `Memory/scene_filter.py` — `filter_history_by_presence(...)`,在场过滤纯函数(决策 D 的 `granularity`)。
- 新建 `Memory/provider.py` — `ActorMemoryProvider` 协议(`typing.Protocol`)。
- 新建 `Memory/default_provider.py` — `DefaultActorMemoryProvider`,读 + 过滤 + 组装 + 检索占位。
- 修改 `History/GameMemory.py:6-19` — `HistoryItem` 增补 `on_stage` / `location_id` 两个 `NotRequired` 字段。
- 修改 `Actor/ActorRuntime.py:615-622` — 构造 `history_item` 时写入当前 `scene` 的 `on_stage`/`location_id`。
- 修改 `Graph/narration_nodes.py:104-111` — 旁白事件条目补记快照。
- 修改 `Graph/beat_group.py:169-177` — 并行组失败系统事件条目补记快照。
- 新建 `tests/test_memory_scene_filter.py` — 在场过滤单测。
- 新建 `tests/test_memory_provider.py` — 工厂组装 + 检索占位单测。
- 新建 `tests/test_history_scene_snapshot.py` — 三处写 history 补记快照的单测。

---

## Task 1: HistoryItem 增补在场快照字段

**Files:**
- Modify: `History/GameMemory.py:6-19`

- [ ] **Step 1: 给 HistoryItem 增补两个 NotRequired 字段**

编辑 `History/GameMemory.py`,把 `HistoryItem` 改为(在 `tool_name` 后追加两行):

```python
class HistoryItem(TypedDict):
    turn: int
    actor: Optional[str]
    mode: str
    content: str
    spoken_text: NotRequired[str]
    nonverbal_action: NotRequired[str]
    raw_content: NotRequired[str]
    raw_spoken_text: NotRequired[str]
    raw_nonverbal_action: NotRequired[str]
    narration_source: NotRequired[str]
    narration_style_preset: NotRequired[str]
    message_kind: NotRequired[str]
    tool_name: NotRequired[str]
    on_stage: NotRequired[list[str]]      # 该条目所属回合当时在台上的角色(逐条快照)
    location_id: NotRequired[str]         # 该条目发生的地点(逐条快照)
```

- [ ] **Step 2: 运行现有回归,确认新增可选字段不破坏任何用例**

Run: `python -m pytest -q`
Expected: PASS,153 passed(新增 `NotRequired` 字段对现有代码透明)。

- [ ] **Step 3: 提交**

```bash
git add History/GameMemory.py
git commit -m "feat(memory): HistoryItem 增补逐条 on_stage/location_id 在场快照字段"
```

---

## Task 2: 在场过滤纯函数 scene_filter

**Files:**
- Create: `Memory/scene_filter.py`
- Test: `tests/test_memory_scene_filter.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_memory_scene_filter.py`:

```python
from __future__ import annotations

import unittest

from Memory.scene_filter import filter_history_by_presence


def _item(turn, actor, *, on_stage, location_id):
    return {
        "turn": turn,
        "actor": actor,
        "mode": "speak",
        "content": f"line-{turn}",
        "on_stage": on_stage,
        "location_id": location_id,
    }


class SceneFilterTests(unittest.TestCase):
    def test_on_stage_granularity_keeps_only_present_rounds(self):
        # 角色 A 在场→下场→再上场;严格 on_stage 只保留其在场回合
        history = [
            _item(1, "A", on_stage=["A", "B"], location_id="hall"),
            _item(2, "B", on_stage=["B"], location_id="hall"),          # A 下场
            _item(3, "B", on_stage=["B", "A"], location_id="hall"),     # A 再上场
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="on_stage",
        )
        self.assertEqual([it["turn"] for it in kept], [1, 3])

    def test_recent_rounds_limit_applies_after_filter(self):
        history = [
            _item(t, "A", on_stage=["A"], location_id="hall") for t in range(1, 6)
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=3, granularity="on_stage",
        )
        self.assertEqual([it["turn"] for it in kept], [3, 4, 5])

    def test_location_granularity_keeps_same_location_rounds(self):
        history = [
            _item(1, "B", on_stage=["B"], location_id="hall"),   # A 不在台上但同地点
            _item(2, "B", on_stage=["B"], location_id="cave"),   # 不同地点
        ]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="location",
        )
        self.assertEqual([it["turn"] for it in kept], [1])

    def test_missing_snapshot_is_invisible_under_on_stage(self):
        # 缺 on_stage 字段的条目,严格粒度下视为不可见(决策 A:缺省即不可见)
        history = [{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}]
        kept = filter_history_by_presence(
            history, actor_id="A", current_location_id="hall",
            recent_rounds=10, granularity="on_stage",
        )
        self.assertEqual(kept, [])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_memory_scene_filter.py -q`
Expected: FAIL,`ModuleNotFoundError: No module named 'Memory'`。

- [ ] **Step 3: 写最小实现**

创建 `Memory/scene_filter.py`:

```python
from __future__ import annotations

from typing import Literal

from History.GameMemory import HistoryItem

# 在场判定粒度:严格在台上 vs 同地点即可见。
PresenceGranularity = Literal["on_stage", "location"]


def _is_present(
    item: HistoryItem,
    *,
    actor_id: str,
    current_location_id: str,
    granularity: PresenceGranularity,
) -> bool:
    if granularity == "location":
        # 地点粒度:条目发生地点 == 角色当前所在地点。缺快照则不可见。
        return item.get("location_id", "") == current_location_id
    # 严格 on_stage 粒度(默认):角色当时在台上。缺快照则不可见。
    return actor_id in item.get("on_stage", [])


def filter_history_by_presence(
    history: list[HistoryItem],
    *,
    actor_id: str,
    current_location_id: str,
    recent_rounds: int = 3,
    granularity: PresenceGranularity = "on_stage",
) -> list[HistoryItem]:
    """按「角色当时是否在场」过滤 history,再取最近 recent_rounds 条。

    决策 D:默认严格 on_stage;granularity="location" 时改为同地点可见。
    决策 A:逐条依赖 item 自带的 on_stage/location_id 快照;缺快照即不可见。
    工厂只读,不修改入参。
    """
    kept = [
        item
        for item in history
        if _is_present(
            item,
            actor_id=actor_id,
            current_location_id=current_location_id,
            granularity=granularity,
        )
    ]
    if recent_rounds <= 0:
        return kept
    return kept[-recent_rounds:]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_memory_scene_filter.py -q`
Expected: PASS,4 passed。

- [ ] **Step 5: 提交**

```bash
git add Memory/scene_filter.py tests/test_memory_scene_filter.py
git commit -m "feat(memory): 新增在场过滤纯函数 filter_history_by_presence(on_stage/location 双粒度)"
```

---

## Task 3: 只读投影 DTO(context.py)

**Files:**
- Create: `Memory/context.py`
- Test: `tests/test_memory_provider.py`(先建文件,测 DTO 只读)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_memory_provider.py`:

```python
from __future__ import annotations

import dataclasses
import unittest

from Memory.context import ActorMemoryContext, LongTermView


class ActorMemoryContextTests(unittest.TestCase):
    def _ctx(self):
        return ActorMemoryContext(
            actor_id="A",
            persona={"character_id": "A", "name": "甲"},
            short_term=[{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}],
            long_term=LongTermView(
                consolidated=[], long_term=[], pinned=[],
            ),
            retrieved=[],
        )

    def test_context_is_frozen(self):
        ctx = self._ctx()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.actor_id = "B"  # type: ignore[misc]

    def test_long_term_view_is_frozen(self):
        view = LongTermView(consolidated=[], long_term=[], pinned=[])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            view.consolidated = [1]  # type: ignore[misc]

    def test_context_holds_references_not_deep_copies(self):
        short = [{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}]
        ctx = ActorMemoryContext(
            actor_id="A", persona={}, short_term=short,
            long_term=LongTermView(consolidated=[], long_term=[], pinned=[]),
            retrieved=[],
        )
        # 只读投影:持有引用而非深拷贝(引用一致)
        self.assertIs(ctx.short_term, short)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_memory_provider.py -q`
Expected: FAIL,`ModuleNotFoundError: No module named 'Memory.context'`。

- [ ] **Step 3: 写最小实现**

创建 `Memory/context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from CharacterMemory import (
    ConsolidatedMemoryBlock,
    LongTermMemoryEvent,
)
from CharacterProfile import CharacterProfile
from History.GameMemory import HistoryItem


@dataclass(frozen=True)
class LongTermView:
    """角色长期记忆的只读概览:直接引用 state 里已压缩的字段。"""
    consolidated: list[ConsolidatedMemoryBlock]
    long_term: list[LongTermMemoryEvent]
    pinned: list[LongTermMemoryEvent]


@dataclass(frozen=True)
class ActorMemoryContext:
    """喂给 agent 的收窄只读视图,取代直接传整个 GameState。

    构建时按需抽取引用(不深拷贝大对象)。
    - persona:沿用现有 CharacterProfile(人设 + memory_profile 配置)。
    - short_term:在场过滤后的最近数轮 history 明细。
    - long_term:角色自我状态概览(读现有压缩字段)。
    - retrieved:检索命中(本轮恒为空,Recall 检索层做好后填实)。
    """
    actor_id: str
    persona: CharacterProfile
    short_term: list[HistoryItem]
    long_term: LongTermView
    retrieved: list[Any]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_memory_provider.py -q`
Expected: PASS,3 passed。

- [ ] **Step 5: 提交**

```bash
git add Memory/context.py tests/test_memory_provider.py
git commit -m "feat(memory): 新增只读投影 DTO ActorMemoryContext + LongTermView(frozen,持引用不深拷贝)"
```

---

## Task 4: Provider 协议(provider.py)

**Files:**
- Create: `Memory/provider.py`

- [ ] **Step 1: 写最小实现(协议无行为,不需先写失败测试)**

创建 `Memory/provider.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from GameState import GameState
from Memory.context import ActorMemoryContext


@runtime_checkable
class ActorMemoryProvider(Protocol):
    """记忆工厂协议:把三层记忆组装成 ActorMemoryContext。

    可注入、可替换、可 mock(像 history_manager 一样挂到 GraphDependencies)。
    实现必须只读:不得修改 state,不落任何存储。
    """

    def build(self, actor_id: str, state: GameState) -> ActorMemoryContext:
        ...
```

- [ ] **Step 2: 运行导入冒烟 + 现有回归**

Run: `python -c "from Memory.provider import ActorMemoryProvider" && python -m pytest -q`
Expected: 导入无报错;PASS,157 passed(153 基线 + Task2 的 4 + Task3 的 3;此处 157=153+4;Task3 的 3 与 153 基线合计随收集变化,以实际输出为准,只要全绿)。

> 注:回归总数随新测递增,判定标准是「全绿、无 FAIL/ERROR」,不是固定数字。

- [ ] **Step 3: 提交**

```bash
git add Memory/provider.py
git commit -m "feat(memory): 新增 ActorMemoryProvider 协议(可注入的记忆工厂接口)"
```

---

## Task 5: 默认工厂实现(default_provider.py)

**Files:**
- Create: `Memory/default_provider.py`
- Test: `tests/test_memory_provider.py`(追加工厂用例)

- [ ] **Step 1: 追加失败测试**

在 `tests/test_memory_provider.py` 末尾追加:

```python
from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state
from Memory.default_provider import DefaultActorMemoryProvider


def _build_state_with_history():
    profiles = {
        "A": ensure_character_profile({
            "character_id": "A", "name": "甲", "persona": [],
            "base_style": "", "base_relationship": {}, "secrets": [],
            "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
            "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
        }),
    }
    # 工厂只读 history/scene/characters 三个键,直接构造最小 dict 即可,
    # 无需完整 GameState(create_initial_game_state 需大段 plot/scene 字面量)。
    state = {
        "scene": {"location_id": "hall", "on_stage": ["A"]},
        "characters": {"A": create_character_runtime_state()},
        "history": [
            {"turn": 1, "actor": "A", "mode": "speak", "content": "在场",
             "on_stage": ["A"], "location_id": "hall"},
            {"turn": 2, "actor": "B", "mode": "speak", "content": "不在场",
             "on_stage": ["B"], "location_id": "hall"},
        ],
    }
    return state, profiles


class DefaultActorMemoryProviderTests(unittest.TestCase):
    def test_build_short_term_applies_presence_filter(self):
        state, profiles = _build_state_with_history()
        provider = DefaultActorMemoryProvider(
            character_profiles=profiles, recent_rounds=3,
        )
        ctx = provider.build("A", state)
        # 只保留 A 在场的回合(turn 1),排除 turn 2
        self.assertEqual([it["turn"] for it in ctx.short_term], [1])
        self.assertEqual(ctx.actor_id, "A")
        self.assertEqual(ctx.persona["name"], "甲")

    def test_build_long_term_reads_character_memory(self):
        state, profiles = _build_state_with_history()
        state["characters"]["A"]["memory"]["pinned_long_term_memory"] = [
            {"turn_recorded": 1, "event_summary": "钉住", "subjective_interpretation": "",
             "belief_formed": "", "priority": "high", "tags": [],
             "pin_candidate": True, "pin_reason": "", "linked_characters": []},
        ]
        provider = DefaultActorMemoryProvider(character_profiles=profiles)
        ctx = provider.build("A", state)
        self.assertEqual(len(ctx.long_term.pinned), 1)
        self.assertEqual(ctx.long_term.pinned[0]["event_summary"], "钉住")

    def test_build_retrieved_is_empty_placeholder(self):
        state, profiles = _build_state_with_history()
        provider = DefaultActorMemoryProvider(character_profiles=profiles)
        ctx = provider.build("A", state)
        self.assertEqual(ctx.retrieved, [])

    def test_build_does_not_mutate_state(self):
        state, profiles = _build_state_with_history()
        history_before = list(state["history"])
        provider = DefaultActorMemoryProvider(character_profiles=profiles)
        provider.build("A", state)
        self.assertEqual(state["history"], history_before)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_memory_provider.py -q`
Expected: FAIL,`ModuleNotFoundError: No module named 'Memory.default_provider'`。

- [ ] **Step 3: 写最小实现**

创建 `Memory/default_provider.py`:

```python
from __future__ import annotations

from typing import Any, Mapping

from CharacterProfile import CharacterProfile
from GameState import GameState
from Memory.context import ActorMemoryContext, LongTermView
from Memory.scene_filter import PresenceGranularity, filter_history_by_presence


class DefaultActorMemoryProvider:
    """默认记忆工厂:读 state + 在场过滤 + 组装三层 DTO。只读,不写 state。"""

    def __init__(
        self,
        *,
        character_profiles: Mapping[str, CharacterProfile],
        recent_rounds: int = 3,
        granularity: PresenceGranularity = "on_stage",
    ) -> None:
        self._character_profiles = character_profiles
        self._recent_rounds = recent_rounds
        self._granularity = granularity

    def build(self, actor_id: str, state: GameState) -> ActorMemoryContext:
        persona: CharacterProfile = self._character_profiles.get(actor_id, {})  # type: ignore[assignment]

        short_term = filter_history_by_presence(
            state["history"],
            actor_id=actor_id,
            current_location_id=state["scene"].get("location_id", ""),
            recent_rounds=self._recent_rounds,
            granularity=self._granularity,
        )

        memory = state["characters"].get(actor_id, {}).get("memory", {})
        long_term = LongTermView(
            consolidated=list(memory.get("consolidated_memory", [])),
            long_term=list(memory.get("long_term_memory", [])),
            pinned=list(memory.get("pinned_long_term_memory", [])),
        )

        return ActorMemoryContext(
            actor_id=actor_id,
            persona=persona,
            short_term=short_term,
            long_term=long_term,
            retrieved=self.retrieve(actor_id, "", user_id="", player_id=""),
        )

    def retrieve(
        self,
        actor_id: str,
        query: str,
        *,
        user_id: str,
        player_id: str,
        top_k: int = 5,
    ) -> list[Any]:
        # 本轮占位:Recall 检索层做好后填实(带 u{user}:p{player}: 租户前缀,失败降级为空)。
        return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_memory_provider.py -q`
Expected: PASS(Task3 的 3 个 + Task5 的 4 个,共 7 passed)。

- [ ] **Step 5: 校验协议一致性**

Run: `python -c "from Memory.provider import ActorMemoryProvider; from Memory.default_provider import DefaultActorMemoryProvider; p = DefaultActorMemoryProvider(character_profiles={}); print(isinstance(p, ActorMemoryProvider))"`
Expected: 打印 `True`(默认实现满足协议)。

- [ ] **Step 6: 提交**

```bash
git add Memory/default_provider.py tests/test_memory_provider.py
git commit -m "feat(memory): 新增 DefaultActorMemoryProvider(在场过滤短期+复用长期+检索占位)"
```

---

## Task 6: 包出口(__init__.py)

**Files:**
- Create: `Memory/__init__.py`

- [ ] **Step 1: 写最小实现**

创建 `Memory/__init__.py`:

```python
"""角色三层记忆注入包(与 Recall/ 平级)。

只读记忆工厂:把角色三层记忆(短期=在场过滤 / 长期=复用压缩产物 / 检索=占位)
组装成收窄的只读 DTO ActorMemoryContext,取代直接向 agent 传整个 GameState。
工厂只读,不落任何存储。
"""

from __future__ import annotations

from Memory.context import ActorMemoryContext, LongTermView
from Memory.default_provider import DefaultActorMemoryProvider
from Memory.provider import ActorMemoryProvider
from Memory.scene_filter import (
    PresenceGranularity,
    filter_history_by_presence,
)

__all__ = [
    "ActorMemoryContext",
    "LongTermView",
    "ActorMemoryProvider",
    "DefaultActorMemoryProvider",
    "PresenceGranularity",
    "filter_history_by_presence",
]
```

- [ ] **Step 2: 验证包出口导入 + 全量回归**

Run: `python -c "from Memory import ActorMemoryContext, ActorMemoryProvider, DefaultActorMemoryProvider, filter_history_by_presence" && python -m pytest -q`
Expected: 导入无报错;全绿,无 FAIL/ERROR。

- [ ] **Step 3: 提交**

```bash
git add Memory/__init__.py
git commit -m "feat(memory): Memory 包出口 re-export(DTO/Provider/默认实现/过滤器)"
```

---

## Task 7: 三处写 history 补记在场快照

> 决策 A 的存侧落地。三处写 history 的地方(actor 提交、旁白事件、并行组失败事件)都补记当前 `scene` 的 `on_stage`/`location_id`,让后续逐条在场过滤精确可用。

**Files:**
- Modify: `Actor/ActorRuntime.py:615-622`
- Modify: `Graph/narration_nodes.py:104-111`
- Modify: `Graph/beat_group.py:169-177`
- Test: `tests/test_history_scene_snapshot.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_history_scene_snapshot.py`:

```python
from __future__ import annotations

import unittest

from Actor.ActorRuntime import apply_resolved_act
from CharacterProfile import ensure_character_profile
from GameState import (
    create_character_runtime_state,
    create_initial_game_state,
    create_player_state,
)
from ResolvedActUtils import build_resolved_act_payload


def _minimal_plot():
    # apply_resolved_act 会读 state["plot"];给足必填键的最小合法 plot。
    return {
        "chapter_id": "chapter-1", "scene_id": "scene-1", "current_scene_index": 0,
        "chapter_goal": "", "current_chapter_hooks": [], "plot_flags": {},
        "story_premise": "", "exploration_drive": "", "story_outline": [],
        "current_chapter_title": "", "current_chapter_overview": "",
        "active_outline_chapter_id": "", "story_premise_source": "",
        "story_outline_source": "", "chapter_expansion_source": "",
        "story_foundation_source": "", "chapter_focus_source": "",
        "scene_candidates_source": "", "current_chapter_index": 0,
        "cultivation_goal": "", "current_player_realm": "",
        "current_chapter_realm": "", "next_chapter_realm": "",
        "chapter_transition_requirement": "", "completed_chapters": [],
    }


class HistorySceneSnapshotTests(unittest.TestCase):
    def test_apply_resolved_act_records_on_stage_and_location(self):
        profiles = {
            "A": ensure_character_profile({
                "character_id": "A", "name": "甲", "persona": [],
                "base_style": "", "base_relationship": {}, "secrets": [],
                "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
                "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
            }),
        }
        state = create_initial_game_state(
            plot=_minimal_plot(),
            scene={
                "location_id": "hall", "time_tag": "morning", "beat": "",
                "tension": 0.0, "focus_character": "A",
                "on_stage": ["A", "B"], "allow_interrupt": True, "suppressed": [],
            },
            characters={"A": create_character_runtime_state()},
            player=create_player_state(controlled_character="player"),
        )
        resolved = build_resolved_act_payload(
            actor="A", mode="speak", target=None, content="你好",
        )
        state["runtime"]["resolved_act"] = resolved

        next_state = apply_resolved_act(state, character_profiles=profiles)

        last = next_state["history"][-1]
        self.assertEqual(last["on_stage"], ["A", "B"])
        self.assertEqual(last["location_id"], "hall")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_history_scene_snapshot.py -q`
Expected: FAIL,`KeyError: 'on_stage'`(history_item 尚未写入快照)。

- [ ] **Step 3: 改 apply_resolved_act 补记快照**

编辑 `Actor/ActorRuntime.py`,把 `history_item` 构造(615-622)改为在末尾追加两行:

```python
    history_item: HistoryItem = {
        "turn": next_turn,
        "actor": actor_id,
        "mode": resolved_act["mode"],
        "content": resolved_act["content"],
        "spoken_text": resolved_act.get("spoken_text", ""),
        "nonverbal_action": resolved_act.get("nonverbal_action", ""),
        "on_stage": list(state["scene"].get("on_stage", [])),
        "location_id": state["scene"].get("location_id", ""),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_history_scene_snapshot.py -q`
Expected: PASS,1 passed。

- [ ] **Step 5: 改旁白事件补记快照**

编辑 `Graph/narration_nodes.py`,把 `_append_narration_event` 里追加的字典(104-111)改为:

```python
            {
                "turn": next_turn,
                "actor": None,
                "mode": "event",
                "content": normalized_content,
                "narration_source": source,
                "narration_style_preset": style_preset,
                "on_stage": list(state["scene"].get("on_stage", [])),
                "location_id": state["scene"].get("location_id", ""),
            },
```

- [ ] **Step 6: 改并行组失败事件补记快照**

编辑 `Graph/beat_group.py`,把失败系统事件字典(169-177)改为:

```python
                {
                    "turn": next_turn,
                    "actor": None,
                    "mode": "event",
                    "content": f"（系统）以下角色本轮生成失败，已跳过：{failed_ids}。",
                    "spoken_text": "",
                    "nonverbal_action": "",
                    "message_kind": "system",
                    "on_stage": list(current["scene"].get("on_stage", [])),
                    "location_id": current["scene"].get("location_id", ""),
                },
```

> 注意:此处系统事件文本里的中文标点是**全角**(`（系统）`、`：`、`，`、`。`),改动时**只加两行**,不要动原文本标点。

- [ ] **Step 7: 全量回归**

Run: `python -m pytest -q`
Expected: 全绿,无 FAIL/ERROR(三处补记对现有断言透明,新增快照单测通过)。

- [ ] **Step 8: 提交**

```bash
git add Actor/ActorRuntime.py Graph/narration_nodes.py Graph/beat_group.py tests/test_history_scene_snapshot.py
git commit -m "feat(memory): 三处写 history 补记逐条 on_stage/location_id 在场快照(决策 A)"
```

---

## 自检记录(写计划后已做)

- **Spec 覆盖**:短期在场过滤(Task2)、长期复用(Task5)、检索占位(Task5.retrieve)、DTO 只读(Task3)、A 补记快照(Task1+Task7)、D granularity(Task2)——设计文档各节均有对应任务。B(N 轮兜底)本轮按纯复用不实现、C(检索 query)占位、E(接入)不做,均为已确认的本轮范围外,故无任务,符合决策。
- **占位符扫描**:每个代码步骤均给出完整代码;`retrieve` 的 `return []` 是设计明确的占位并已注释,非计划占位符。
- **类型一致性**:`ActorMemoryContext` / `LongTermView` / `filter_history_by_presence(granularity=...)` / `DefaultActorMemoryProvider(character_profiles=..., recent_rounds=..., granularity=...)` / `.build(actor_id, state)` / `.retrieve(...)` 在 Task2/3/4/5/6 间签名一致。`HistoryItem.on_stage`/`location_id` 字段(Task1)与 Task2 过滤、Task7 写入、Task5 组装用法一致。

## 接入点(本轮不做,E 待定后另起计划)

未来把工厂接入 actor 回合时,`Graph/actor_paths.py:resolve_npc_turn_state` 的 `actor_agent.perform_turn(state=state, character_profiles=...)` 会改为先 `ctx = deps.actor_memory_provider.build(actor_id, state)` 再传 `ctx`;同时 `Graph/dependencies.py` 挂 `actor_memory_provider` 字段、`session_bootstrap.py:378` 的 `GraphDependencies(...)` 默认构建 `DefaultActorMemoryProvider`。这些属决策 E 范围,待你定后单独成计划。
