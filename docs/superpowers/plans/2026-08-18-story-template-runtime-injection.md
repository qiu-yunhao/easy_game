# 情节模板运行时注入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「读选定情节模板 → 检索 → 注入 chapter 展开 + scene 候选两层规划」的运行时链路，让玩家选中的 StoryTemplate 作软指导参考素材影响剧情走向；模板可选，缺失/故障时静默降级为现有纯 LLM 规划。

**Architecture:** state 存单一 `selected_template_id`，`apply_selected_template` 供上层设定；`GraphDependencies.story_template_service` 组装期注入，编排层（`_ensure_chapter_expansion`/`_ensure_scene_candidates`）把 service 作方法入参下传 agent；agent 无状态、检索并格式化 guidance（try/except 降级）后传 formatter；formatter 非空 guidance 才拼进 payload。全链路新参数默认 None/""/0，不选模板/不挂服务时逐字节退化为现状。

**Tech Stack:** Python 3.12；解释器 `/Users/qiuyunhao.1/miniconda3/bin/python3`，命令前缀 `HF_ENDPOINT=https://hf-mirror.com`；TDD 用 fake（免真 LLM/DB）。既有 `StoryTemplateService`（`StoryTemplate/StoryTemplateService.py`）、`PlotSkeletonNode`/`PlotBeat`（`StoryTemplate/TemplateSchema.py`，均 TypedDict）、`AgentMessage`（`{speaker, content}`）、`StoryStateUtils.current_outline_entry`。

---

## Context

**为什么做：** `StoryTemplate` 解析侧已完成入库 + `StoryTemplateService` 4 检索接口，但消费侧完全未接线——剧情四层规划全是纯 LLM/启发式，不看模板。本次打通 chapter 展开 + scene 候选两层的软指导注入。

**探查已确认的关键事实（含精确签名/行号）：**
1. `PlotState`（`GameState.py:50`）是 TypedDict，字段全程 `.get(...)` 访问；`session_bootstrap.py:240` 直接字面量构造 plot dict（未强制全字段）。
2. `apply_*` 不可变更新（`Graph/story_planning_state.py:180` `_apply_chapter_expansion`）：返回 `{**state, "plot": {**state["plot"], ...}}`。
3. `GraphDependencies`（`Graph/dependencies.py:31`）`@dataclass(slots=True)`，agent 字段默认 None；文件顶部有 `if TYPE_CHECKING:` 块（:24-28）。
4. agent 两方法（`PlayerWriter/PlayerWriterAgent.py`）：`expand_current_chapter`（:258）、`generate_scene_candidates`（:299），关键字入参 `game_state/scene_config/character_profiles/history=None`；内部调 `self.formatter.build_*_instruction(...)`。
5. formatter 两方法（`PlayerWriter/PlayerWriterFormatter.py`）：`build_chapter_expansion_instruction`（:436）、`build_scene_candidates_instruction`（:538），内部构造 `payload` dict 后 `render_json_instruction(header, payload)`。
6. 编排层（`Graph/story_planning.py`）：`_ensure_chapter_expansion`（:272，:288 调 agent）、`_ensure_scene_candidates`（:327，:338 调 agent）；两处调用当前**不传** `history`。`_ensure_chapter_expansion` 也从 `Graph/nodes` 再导出（测试 import 自 `Graph.nodes`）。
7. service 签名：`next_skeleton_nodes(template_id, *, chapter_hint)` → `list[PlotSkeletonNode]`；`suggest_plot_beats(template_id, *, query, top_k=5)` → `list[PlotBeat]`。
8. `PlotSkeletonNode`：`node_id/order_index/title/event_summary/preconditions/maps_to_chapter_hint`。`PlotBeat`：`beat_id/label/tags/summary/dramatic_function/reusable_conflict`。
9. `StoryStateUtils.current_outline_entry(game_state)`（:163）：按 `chapter_id` 匹配 outline，退化到 `current_chapter_index`，再退化首条，无则 `{}`。formatter 已复用它（别名 `_resolve_current_outline_chapter`）。
10. 测试风格（`tests/test_story_planning_fallbacks.py`）：顶部 stub `openai` 模块后再 import；有 `build_default_state`/`build_graph_dependencies` 等 helper。

---

## File Structure

- **Modify** `GameState.py` — `PlotState` TypedDict 加 `selected_template_id: int` 字段声明。
- **Modify** `Graph/story_planning_state.py` — 加 `apply_selected_template(state, template_id) -> GameState`（不可变更新；`template_id<=0` 清 0）。
- **Modify** `Graph/dependencies.py` — `GraphDependencies` 加 `story_template_service` 字段（TYPE_CHECKING import）。
- **Create** `PlayerWriter/StoryTemplateGuidance.py` — 3 个纯函数：`build_template_query` / `format_skeleton_guidance` / `format_beat_guidance`。
- **Modify** `PlayerWriter/PlayerWriterAgent.py` — 两方法加 `template_service=None`，检索+格式化+降级，把 guidance 传 formatter。
- **Modify** `PlayerWriter/PlayerWriterFormatter.py` — 两 build 方法加 `template_guidance: str = ""`，非空作 payload 字段。
- **Modify** `Graph/story_planning.py` — 两编排函数调 agent 时传 `template_service=deps.story_template_service`。
- **Test** `tests/test_story_template_guidance.py`（新建，Task 1/2）、扩充 `tests/test_story_planning_fallbacks.py` 或新建 `tests/test_story_template_injection.py`（Task 4/5/6）。

生产逻辑改动均以默认参数保持向后兼容。

---

## Task 1: 纯函数 build_template_query（TDD）

**Files:**
- Create: `PlayerWriter/StoryTemplateGuidance.py`
- Test: `tests/test_story_template_guidance.py`

`build_template_query(state, history)` 拼「章节目标（`chapter_goal` + `current_outline_entry` 的 `title`/`main_goal`）+ 最近剧情」；`history` 为空只用章节目标。`history` 是 `list[AgentMessage]`（`{speaker, content}`），取最近 3 条的 content 拼接。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_story_template_guidance.py`：

```python
from __future__ import annotations

import unittest

from PlayerWriter.StoryTemplateGuidance import (
    build_template_query,
    format_beat_guidance,
    format_skeleton_guidance,
)


def _state(chapter_goal="", outline=None, chapter_id="ch-1"):
    return {
        "plot": {
            "chapter_id": chapter_id,
            "chapter_goal": chapter_goal,
            "current_chapter_index": 0,
            "story_outline": outline or [],
        }
    }


class BuildTemplateQueryTests(unittest.TestCase):
    def test_有history时拼章节目标与最近剧情(self):
        state = _state(
            chapter_goal="夺回赤霞令",
            outline=[{"chapter_id": "ch-1", "title": "客栈风云", "main_goal": "查明黑衣人来历"}],
        )
        history = [
            {"speaker": "玩家", "content": "我推门走进客栈。"},
            {"speaker": "黑衣人", "content": "交出赤霞令！"},
        ]
        query = build_template_query(state, history)
        self.assertIn("夺回赤霞令", query)
        self.assertIn("客栈风云", query)
        self.assertIn("查明黑衣人来历", query)
        self.assertIn("交出赤霞令", query)

    def test_history为空时只用章节目标(self):
        state = _state(
            chapter_goal="夺回赤霞令",
            outline=[{"chapter_id": "ch-1", "title": "客栈风云", "main_goal": "查明黑衣人来历"}],
        )
        query = build_template_query(state, None)
        self.assertIn("夺回赤霞令", query)
        self.assertIn("客栈风云", query)
        self.assertNotIn("交出赤霞令", query)

    def test_无outline时仅章节目标不报错(self):
        state = _state(chapter_goal="夺回赤霞令", outline=[])
        query = build_template_query(state, [])
        self.assertIn("夺回赤霞令", query)

    def test_只取最近三条history(self):
        state = _state(chapter_goal="目标")
        history = [{"speaker": "x", "content": f"句子{i}"} for i in range(5)]
        query = build_template_query(state, history)
        self.assertIn("句子4", query)
        self.assertIn("句子2", query)
        self.assertNotIn("句子1", query)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance.BuildTemplateQueryTests -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'PlayerWriter.StoryTemplateGuidance'`）

- [ ] **Step 3: 实现 build_template_query（+ 两个 format 占位）**

创建 `PlayerWriter/StoryTemplateGuidance.py`：

```python
"""情节模板软指导：把检索到的骨架/桥段格式化成提示词参考素材。

纯函数，无副作用、不依赖 LLM/DB。build_template_query 拼检索线索；
format_* 把检索结果转成软指导文本，空输入返回 ""（formatter 据此判断是否注入）。
"""

from __future__ import annotations

from typing import Any

from StoryStateUtils import current_outline_entry

_RECENT_HISTORY_LIMIT = 3


def build_template_query(state: dict[str, Any], history: list[dict] | None) -> str:
    plot = state.get("plot", {})
    parts: list[str] = []
    chapter_goal = str(plot.get("chapter_goal", "") or "").strip()
    if chapter_goal:
        parts.append(chapter_goal)
    outline = current_outline_entry(state)
    title = str(outline.get("title", "") or "").strip()
    main_goal = str(outline.get("main_goal", "") or "").strip()
    if title:
        parts.append(title)
    if main_goal:
        parts.append(main_goal)
    if history:
        recent = history[-_RECENT_HISTORY_LIMIT:]
        for message in recent:
            content = str(message.get("content", "") or "").strip()
            if content:
                parts.append(content)
    return " ".join(parts)


def format_skeleton_guidance(nodes: list[dict]) -> str:
    return ""  # 见 Task 2


def format_beat_guidance(beats: list[dict]) -> str:
    return ""  # 见 Task 2
```

- [ ] **Step 4: 跑测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance.BuildTemplateQueryTests -v`
Expected: PASS（4 tests）

- [ ] **Step 5: 提交**

```bash
git add PlayerWriter/StoryTemplateGuidance.py tests/test_story_template_guidance.py
git commit -m "feat(story-template): build_template_query 拼检索线索(章节目标+最近剧情)"
```

---

## Task 2: format_skeleton_guidance / format_beat_guidance（TDD）

**Files:**
- Modify: `PlayerWriter/StoryTemplateGuidance.py`
- Test: `tests/test_story_template_guidance.py`（追加两组）

骨架节点 → 软指导文本（措辞：可参考骨架走向，不必严格遵循）；桥段 → 软指导文本（措辞：桥段作场景候选灵感参考，不必照搬）。空列表返回 `""`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_story_template_guidance.py` 追加：

```python
class FormatSkeletonGuidanceTests(unittest.TestCase):
    def test_多节点转软指导文本(self):
        nodes = [
            {"node_id": "n1", "order_index": 0, "title": "初入江湖",
             "event_summary": "主角离乡遭遇第一场冲突", "preconditions": [], "maps_to_chapter_hint": ""},
            {"node_id": "n2", "order_index": 1, "title": "结义",
             "event_summary": "与关键盟友结拜", "preconditions": ["初入江湖"], "maps_to_chapter_hint": ""},
        ]
        text = format_skeleton_guidance(nodes)
        self.assertIn("初入江湖", text)
        self.assertIn("主角离乡遭遇第一场冲突", text)
        self.assertIn("结义", text)
        self.assertIn("参考", text)  # 软指导措辞

    def test_空列表返回空串(self):
        self.assertEqual(format_skeleton_guidance([]), "")


class FormatBeatGuidanceTests(unittest.TestCase):
    def test_多桥段转软指导文本(self):
        beats = [
            {"beat_id": "b1", "label": "伏击", "tags": ["冲突"],
             "summary": "在必经之路设伏", "dramatic_function": "制造危机", "reusable_conflict": "以少胜多"},
            {"beat_id": "b2", "label": "反转", "tags": ["悬念"],
             "summary": "盟友暴露真实身份", "dramatic_function": "情感冲击", "reusable_conflict": "信任背叛"},
        ]
        text = format_beat_guidance(beats)
        self.assertIn("伏击", text)
        self.assertIn("在必经之路设伏", text)
        self.assertIn("反转", text)
        self.assertIn("参考", text)  # 软指导措辞

    def test_空列表返回空串(self):
        self.assertEqual(format_beat_guidance([]), "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance.FormatSkeletonGuidanceTests tests.test_story_template_guidance.FormatBeatGuidanceTests -v`
Expected: FAIL（当前 format_* 返回 ""，多节点/多桥段用例断言不到内容）

- [ ] **Step 3: 实现两个 format 函数**

替换 `PlayerWriter/StoryTemplateGuidance.py` 中两个占位实现：

```python
def format_skeleton_guidance(nodes: list[dict]) -> str:
    if not nodes:
        return ""
    lines = ["以下是可参考的情节骨架走向（软指导，可借鉴亦可偏离，不必严格遵循）："]
    for node in nodes:
        title = str(node.get("title", "") or "").strip()
        summary = str(node.get("event_summary", "") or "").strip()
        if not title and not summary:
            continue
        lines.append(f"- {title}：{summary}" if title else f"- {summary}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def format_beat_guidance(beats: list[dict]) -> str:
    if not beats:
        return ""
    lines = ["以下是可参考的桥段素材（作场景候选灵感参考，可借鉴亦可偏离，不必照搬）："]
    for beat in beats:
        label = str(beat.get("label", "") or "").strip()
        summary = str(beat.get("summary", "") or "").strip()
        function = str(beat.get("dramatic_function", "") or "").strip()
        if not label and not summary:
            continue
        segment = f"- {label}：{summary}" if label else f"- {summary}"
        if function:
            segment += f"（戏剧功能：{function}）"
        lines.append(segment)
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
```

- [ ] **Step 4: 跑全文件测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance -v`
Expected: PASS（4 + 4 = 8 tests）

- [ ] **Step 5: 提交**

```bash
git add PlayerWriter/StoryTemplateGuidance.py tests/test_story_template_guidance.py
git commit -m "feat(story-template): format_skeleton_guidance/format_beat_guidance 软指导文本"
```

---

## Task 3: PlotState 字段 + apply_selected_template（TDD）

**Files:**
- Modify: `GameState.py:50`（PlotState 加字段声明）
- Modify: `Graph/story_planning_state.py`（加 apply_selected_template）
- Modify: `session_bootstrap.py:240`（plot 字面量补 `selected_template_id: 0`）
- Test: `tests/test_story_template_guidance.py`（追加 `ApplySelectedTemplateTests`）

`apply_selected_template(state, template_id)`：不可变更新 `state["plot"]["selected_template_id"]`；`template_id<=0` 或非法 → 存 0（清空）；返回新 state，不改原 state。

- [ ] **Step 1: 写失败测试**

在 `tests/test_story_template_guidance.py` 追加（顶部 import 处补 `from Graph.story_planning_state import apply_selected_template`）：

```python
from Graph.story_planning_state import apply_selected_template


class ApplySelectedTemplateTests(unittest.TestCase):
    def _full_state(self):
        return {"plot": {"chapter_id": "ch-1", "selected_template_id": 0}, "history": []}

    def test_设正值写入(self):
        state = self._full_state()
        out = apply_selected_template(state, 42)
        self.assertEqual(out["plot"]["selected_template_id"], 42)

    def test_非正值清零(self):
        state = {"plot": {"chapter_id": "ch-1", "selected_template_id": 42}}
        out = apply_selected_template(state, 0)
        self.assertEqual(out["plot"]["selected_template_id"], 0)
        out2 = apply_selected_template(state, -5)
        self.assertEqual(out2["plot"]["selected_template_id"], 0)

    def test_返回新state不改原state(self):
        state = self._full_state()
        out = apply_selected_template(state, 7)
        self.assertEqual(state["plot"]["selected_template_id"], 0)  # 原 state 未变
        self.assertIsNot(out, state)
        self.assertIsNot(out["plot"], state["plot"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance.ApplySelectedTemplateTests -v`
Expected: FAIL（`ImportError: cannot import name 'apply_selected_template'`）

- [ ] **Step 3: 加 PlotState 字段声明**

`GameState.py`，`PlotState`（:50）末尾字段后加一行（放 `current_chapter_index: int` 附近即可，TypedDict 字段顺序无关紧要）：

```python
    selected_template_id: int
```

- [ ] **Step 4: 实现 apply_selected_template**

`Graph/story_planning_state.py` 文件末尾追加（沿用本文件不可变风格）：

```python
def apply_selected_template(state: GameState, template_id: int) -> GameState:
    """设定当前情节模板 id（供上层建游戏/大章开始调用）。

    template_id<=0 或非整数 → 清为 0（无模板）。不可变更新，返回新 state。
    """
    try:
        resolved = int(template_id)
    except (TypeError, ValueError):
        resolved = 0
    if resolved < 0:
        resolved = 0
    return {
        **state,
        "plot": {
            **state["plot"],
            "selected_template_id": resolved,
        },
    }
```

- [ ] **Step 5: session_bootstrap 补默认值**

`session_bootstrap.py`，在 :240 起的 plot 字面量里补一行（放 `"current_chapter_index": 0,` 附近）：

```python
            "selected_template_id": 0,
```

- [ ] **Step 6: 跑测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance.ApplySelectedTemplateTests -v`
Expected: PASS（3 tests）

- [ ] **Step 7: 提交**

```bash
git add GameState.py Graph/story_planning_state.py session_bootstrap.py tests/test_story_template_guidance.py
git commit -m "feat(story-template): PlotState.selected_template_id 字段 + apply_selected_template 接口"
```

---

## Task 4: formatter 两 build 方法加 template_guidance（TDD）

**Files:**
- Modify: `PlayerWriter/PlayerWriterFormatter.py`（`build_chapter_expansion_instruction` :436、`build_scene_candidates_instruction` :538）
- Test: `tests/test_story_template_injection.py`（新建）

两方法各加 `template_guidance: str = ""` 关键字参数；非空时给 payload 加字段（chapter→`reference_skeleton`，scene→`reference_beats`）；空时 payload 结构与现状逐字节一致。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_story_template_injection.py`：

```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from session_bootstrap import (
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
)
from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter


class FormatterTemplateGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.formatter = PlaywrightFormatter()
        self.state = build_default_state()
        self.scene_config = build_default_scene_config()
        self.profiles = build_default_character_profiles()

    def test_chapter_空guidance时不含reference_skeleton(self):
        instr = self.formatter.build_chapter_expansion_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
        )
        self.assertNotIn("reference_skeleton", instr)

    def test_chapter_非空guidance拼进instruction(self):
        instr = self.formatter.build_chapter_expansion_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
            template_guidance="可参考骨架：初入江湖",
        )
        self.assertIn("reference_skeleton", instr)
        self.assertIn("初入江湖", instr)

    def test_scene_空guidance时不含reference_beats(self):
        instr = self.formatter.build_scene_candidates_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
        )
        self.assertNotIn("reference_beats", instr)

    def test_scene_非空guidance拼进instruction(self):
        instr = self.formatter.build_scene_candidates_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
            template_guidance="可参考桥段：伏击",
        )
        self.assertIn("reference_beats", instr)
        self.assertIn("伏击", instr)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.FormatterTemplateGuidanceTests -v`
Expected: FAIL（非空 guidance 两例：`TypeError: unexpected keyword argument 'template_guidance'`）

- [ ] **Step 3: 改 build_chapter_expansion_instruction**

`PlayerWriter/PlayerWriterFormatter.py`，`build_chapter_expansion_instruction`（:436）签名末尾加参数：

```python
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
        template_guidance: str = "",
    ) -> str:
```

在 `payload = { ... }` 构造完、`return render_json_instruction(...)`（:513）之前插入：

```python
        if template_guidance:
            payload["reference_skeleton"] = template_guidance
```

- [ ] **Step 4: 改 build_scene_candidates_instruction**

同文件 `build_scene_candidates_instruction`（:538）签名末尾加 `template_guidance: str = "",`；在其 `payload` 构造完、`return render_json_instruction(...)` 之前插入：

```python
        if template_guidance:
            payload["reference_beats"] = template_guidance
```

（注：scene 方法的 payload 变量名与 return 需先 Read :538-620 确认，与 chapter 层同构——payload dict + render_json_instruction。）

- [ ] **Step 5: 跑测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.FormatterTemplateGuidanceTests -v`
Expected: PASS（4 tests）

- [ ] **Step 6: 提交**

```bash
git add PlayerWriter/PlayerWriterFormatter.py tests/test_story_template_injection.py
git commit -m "feat(story-template): formatter 两层 build 加 template_guidance 可选字段"
```

---

## Task 5: agent 两方法注入 + 降级（TDD）

**Files:**
- Modify: `PlayerWriter/PlayerWriterAgent.py`（`expand_current_chapter` :258、`generate_scene_candidates` :299）
- Test: `tests/test_story_template_injection.py`（追加 `AgentTemplateInjectionTests`）

两方法各加 `template_service=None`；`tid = game_state["plot"].get("selected_template_id", 0)`，`template_service` 且 `tid>0` 才注入；检索 + 格式化用 try/except 包住，异常 → `guidance=""` 继续；guidance 传对应 formatter build 方法。

**测试策略：** 用 fake formatter 捕获收到的 `template_guidance`，用 fake service 返回骨架/桥段或抛异常，用 fake `_execute_with_retry`（monkeypatch 或子类）短路真 LLM。为避免碰 `_execute_with_retry` 内部，测试构造一个最小 agent：直接实例化后替换 `self.formatter` 为 fake、替换 `self._execute_with_retry` 为返回定值的 lambda。

- [ ] **Step 1: 写失败测试**

在 `tests/test_story_template_injection.py` 追加：

```python
from PlayerWriter.PlayerWriterAgent import PlaywrightAgent


class _FakeFormatter:
    def __init__(self):
        self.chapter_guidance = None
        self.scene_guidance = None

    def build_chapter_expansion_instruction(self, *, template_guidance="", **kwargs):
        self.chapter_guidance = template_guidance
        return "CHAPTER_INSTRUCTION"

    def build_scene_candidates_instruction(self, *, template_guidance="", **kwargs):
        self.scene_guidance = template_guidance
        return "SCENE_INSTRUCTION"

    # normalize_* 不会被触达（_execute_with_retry 被替换），留空占位
    def normalize_chapter_expansion(self, *a, **k):
        return {}

    def normalize_scene_candidates(self, *a, **k):
        return []


class _FakeService:
    def __init__(self, *, skeleton=None, beats=None, raises=False):
        self._skeleton = skeleton or []
        self._beats = beats or []
        self._raises = raises

    def next_skeleton_nodes(self, template_id, *, chapter_hint):
        if self._raises:
            raise RuntimeError("db down")
        return self._skeleton

    def suggest_plot_beats(self, template_id, *, query, top_k=5):
        if self._raises:
            raise RuntimeError("db down")
        return self._beats


def _make_agent(formatter):
    agent = PlaywrightAgent.__new__(PlaywrightAgent)  # 跳过 __init__（免真 LLM 依赖）
    agent.formatter = formatter
    agent.character_roster_tool_runtime = None
    agent._execute_with_retry = lambda **kwargs: kwargs.get("_stub_return")
    return agent


def _state_with_tid(tid):
    return {
        "plot": {"chapter_id": "ch-1", "chapter_goal": "夺令", "current_chapter_index": 0,
                 "story_outline": [], "selected_template_id": tid},
        "scene": {"on_stage": [], "location_id": "loc"},
        "history": [],
    }


class AgentTemplateInjectionTests(unittest.TestCase):
    def test_chapter_注入生效(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(skeleton=[
            {"node_id": "n1", "order_index": 0, "title": "初入江湖",
             "event_summary": "离乡遇险", "preconditions": [], "maps_to_chapter_hint": ""}])
        agent.expand_current_chapter(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertIn("初入江湖", fmt.chapter_guidance)

    def test_chapter_tid为0跳过(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(skeleton=[{"node_id": "n1", "order_index": 0, "title": "x",
                                      "event_summary": "y", "preconditions": [], "maps_to_chapter_hint": ""}])
        agent.expand_current_chapter(
            game_state=_state_with_tid(0), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertEqual(fmt.chapter_guidance, "")

    def test_chapter_service为None跳过(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        agent.expand_current_chapter(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=None)
        self.assertEqual(fmt.chapter_guidance, "")

    def test_chapter_检索异常降级(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(raises=True)
        agent.expand_current_chapter(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertEqual(fmt.chapter_guidance, "")  # 异常 → 空 guidance，不阻断

    def test_scene_注入生效(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(beats=[
            {"beat_id": "b1", "label": "伏击", "tags": [], "summary": "设伏",
             "dramatic_function": "危机", "reusable_conflict": ""}])
        agent.generate_scene_candidates(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertIn("伏击", fmt.scene_guidance)

    def test_scene_tid为0跳过(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(beats=[{"beat_id": "b1", "label": "x", "tags": [], "summary": "y",
                                   "dramatic_function": "", "reusable_conflict": ""}])
        agent.generate_scene_candidates(
            game_state=_state_with_tid(0), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertEqual(fmt.scene_guidance, "")

    def test_scene_service为None跳过(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        agent.generate_scene_candidates(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=None)
        self.assertEqual(fmt.scene_guidance, "")

    def test_scene_检索异常降级(self):
        fmt = _FakeFormatter()
        agent = _make_agent(fmt)
        svc = _FakeService(raises=True)
        agent.generate_scene_candidates(
            game_state=_state_with_tid(5), scene_config={}, character_profiles={},
            template_service=svc)
        self.assertEqual(fmt.scene_guidance, "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.AgentTemplateInjectionTests -v`
Expected: FAIL（`template_service` 参数不存在 → TypeError）

- [ ] **Step 3: agent 顶部 import guidance 函数**

`PlayerWriter/PlayerWriterAgent.py` import 区加：

```python
from PlayerWriter.StoryTemplateGuidance import (
    build_template_query,
    format_beat_guidance,
    format_skeleton_guidance,
)
```

- [ ] **Step 4: 加一个私有辅助（DRY 两层门槛+降级）**

在 `PlaywrightAgent` 类内加：

```python
    def _resolve_template_guidance(
        self,
        game_state: GameState,
        history: "list[AgentMessage] | None",
        template_service,
        *,
        layer: str,
    ) -> str:
        """两层共用：门槛检查 + 检索 + 格式化 + 静默降级。layer ∈ {"chapter","scene"}。"""
        if template_service is None:
            return ""
        tid = int(game_state["plot"].get("selected_template_id", 0) or 0)
        if tid <= 0:
            return ""
        try:
            query = build_template_query(game_state, history)
            if layer == "chapter":
                nodes = template_service.next_skeleton_nodes(tid, chapter_hint=query)
                return format_skeleton_guidance(nodes)
            beats = template_service.suggest_plot_beats(tid, query=query, top_k=5)
            return format_beat_guidance(beats)
        except Exception:  # 模板故障绝不阻断游戏
            return ""
```

- [ ] **Step 5: 改 expand_current_chapter**

签名（:258）加 `template_service=None`：

```python
    def expand_current_chapter(
        self,
        game_state: GameState,
        scene_config: SceneConfig,
        character_profiles: dict[str, CharacterProfile],
        history: list[AgentMessage] | None = None,
        template_service=None,
    ) -> dict[str, Any]:
```

在构造 `instruction = self.formatter.build_chapter_expansion_instruction(...)`（:274）前加：

```python
        template_guidance = self._resolve_template_guidance(
            game_state, history, template_service, layer="chapter")
```

并把该调用补 `template_guidance=template_guidance`：

```python
        instruction = self.formatter.build_chapter_expansion_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            template_guidance=template_guidance,
        )
```

- [ ] **Step 6: 改 generate_scene_candidates**

签名（:299）加 `template_service=None`；构造 instruction（:306）前加：

```python
        template_guidance = self._resolve_template_guidance(
            game_state, history, template_service, layer="scene")
```

调用补 `template_guidance=template_guidance`：

```python
        instruction = self.formatter.build_scene_candidates_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            template_guidance=template_guidance,
        )
```

- [ ] **Step 7: 跑测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.AgentTemplateInjectionTests -v`
Expected: PASS（8 tests）

- [ ] **Step 8: 提交**

```bash
git add PlayerWriter/PlayerWriterAgent.py tests/test_story_template_injection.py
git commit -m "feat(story-template): agent 两方法检索注入 guidance + 静默降级"
```

---

## Task 6: deps 字段 + 编排层下传（TDD）

**Files:**
- Modify: `Graph/dependencies.py:31`（GraphDependencies 加 story_template_service）
- Modify: `Graph/story_planning.py`（:288、:338 调 agent 时传 `template_service=deps.story_template_service`）
- Test: `tests/test_story_template_injection.py`（追加 `OrchestrationWiringTests`）

编排层从 `deps.story_template_service` 取出，作方法入参下传 agent。

- [ ] **Step 1: 写失败测试**

在 `tests/test_story_template_injection.py` 追加：

```python
from Graph.story_planning import _ensure_chapter_expansion, _ensure_scene_candidates


class _RecordingAgent:
    """捕获 agent 方法收到的 template_service。formatter 属性供编排层降级分支取用。"""
    def __init__(self):
        self.chapter_service = "UNSET"
        self.scene_service = "UNSET"
        self.formatter = _FakeFormatter()

    def expand_current_chapter(self, *, game_state, scene_config, character_profiles,
                               template_service=None, **kwargs):
        self.chapter_service = template_service
        return {"chapter_title": "T", "chapter_goal": "G", "chapter_overview": "O",
                "exploration_hooks": ["h"], "key_locations": ["l"]}

    def generate_scene_candidates(self, *, game_state, scene_config, character_profiles,
                                  template_service=None, **kwargs):
        self.scene_service = template_service
        return [{"candidate_id": "c1", "label": "L", "location_id": "loc", "beat": "b",
                 "scene_goal": "g", "must_happen": [], "must_not_happen": [],
                 "dramatic_curve": [], "character_objectives": {}, "exit_condition": "e", "notes": []}]


class OrchestrationWiringTests(unittest.TestCase):
    def test_chapter_编排层下传service(self):
        from session_bootstrap import build_graph_dependencies
        agent = _RecordingAgent()
        deps = build_graph_dependencies()
        deps.story_template_service = "SVC_SENTINEL"
        state = build_default_state()
        try:
            _ensure_chapter_expansion(state, deps, agent)
        except Exception:
            pass  # 只关心 service 是否被下传，不关心后续校验
        self.assertEqual(agent.chapter_service, "SVC_SENTINEL")

    def test_scene_编排层下传service(self):
        from session_bootstrap import build_graph_dependencies
        agent = _RecordingAgent()
        deps = build_graph_dependencies()
        deps.story_template_service = "SVC_SENTINEL"
        state = build_default_state()
        try:
            _ensure_scene_candidates(state, deps, agent)
        except Exception:
            pass
        self.assertEqual(agent.scene_service, "SVC_SENTINEL")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.OrchestrationWiringTests -v`
Expected: FAIL（`deps.story_template_service` 不存在 → AttributeError；且 agent 未收到 service，仍为 "UNSET"）

- [ ] **Step 3: GraphDependencies 加字段**

`Graph/dependencies.py`，`if TYPE_CHECKING:` 块（:24-28）加：

```python
    from StoryTemplate.StoryTemplateService import StoryTemplateService
```

`GraphDependencies` 字段区（在 `hook_registry` 之前，`actor_memory_provider` 之后即可）加：

```python
    story_template_service: "StoryTemplateService | None" = None
```

- [ ] **Step 4: 编排层下传（chapter）**

`Graph/story_planning.py`，`_ensure_chapter_expansion` 的 agent 调用（:288）补 `template_service`：

```python
            chapter_expansion = playwright_agent.expand_current_chapter(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                template_service=deps.story_template_service,
            )
```

- [ ] **Step 5: 编排层下传（scene）**

同文件 `_ensure_scene_candidates` 的 agent 调用（:338）补：

```python
            candidates = playwright_agent.generate_scene_candidates(
                game_state=state,
                scene_config=deps.scene_config,
                character_profiles=deps.character_profiles,
                template_service=deps.story_template_service,
            )
```

- [ ] **Step 6: 跑测试确认通过**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_injection.OrchestrationWiringTests -v`
Expected: PASS（2 tests）

- [ ] **Step 7: 提交**

```bash
git add Graph/dependencies.py Graph/story_planning.py tests/test_story_template_injection.py
git commit -m "feat(story-template): deps.story_template_service + 编排层下传两层 agent"
```

---

## Task 7: 全量回归（不选模板逐字节退化验证）

**Files:** 无改动，仅跑测试。

- [ ] **Step 1: 跑本特性全部新测试**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance tests.test_story_template_injection -v`
Expected: PASS（全绿）

- [ ] **Step 2: 跑既有剧情规划回归**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_planning_fallbacks -v`
Expected: PASS（既有降级测试不受影响——不挂 service / 不传 template_service 时行为不变）

- [ ] **Step 3: 全套单测冒烟**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -20`
Expected: 无本次改动引入的新失败（若有既存无关失败，逐条确认与本特性无关）。

---

## 复用的现有能力（不改）

- `StoryTemplateService` 4 检索接口（`StoryTemplate/StoryTemplateService.py`）——仅调 `next_skeleton_nodes`/`suggest_plot_beats`。
- `StoryStateUtils.current_outline_entry`——`build_template_query` 复用，与 formatter 同口径。
- formatter 现有 payload 结构——只加可选字段（`reference_skeleton`/`reference_beats`），不改既有键。
- `_execute_with_retry` / normalize / heuristic 降级链——不改，注入只在构造 instruction 前发生。

## 验证

```bash
HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_template_guidance tests.test_story_template_injection -v
HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_story_planning_fallbacks -v
```

## 边界

- **向后兼容第一：** `selected_template_id` 默认 0、`story_template_service` 默认 None、agent/formatter 新参数默认 None/""——不选模板/不挂服务时全链路逐字节退化为现有行为。
- **软指导，不强制：** 注入的是参考素材提示词，LLM 可偏离；不做骨架对齐校验。
- **只动两层：** 不注入 premise/outline，不改检索算法、不改模板解析侧、不改摘要粒度。
- **不做写字段的 UI：** `apply_selected_template` 供上层调用；何时触发留给调用方。
- **history 现状：** 编排层 setup 阶段调 agent 时不传 history（现状即 None），故 `build_template_query` 退化为只用章节目标——符合「大章刚开始」语义，无需额外改动。
- TDD 红→绿→中文 commit，**不 push**。
