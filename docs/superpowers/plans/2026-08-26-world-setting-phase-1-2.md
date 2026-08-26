# 世界设定编写模块 · 阶段1+2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立题材无关的 `WorldSetting` 数据契约 + 通用等级阶梯判定框架，并把现有写死的修仙开局迁移为该契约的默认实例，开局流程改为消费设定包。

**Architecture:** 新增 `WorldSetting/` 模块承载数据契约（`WorldSetting` / `ProgressionSystem` / `AdvanceCondition`）、校验器与 `AdvancementJudge`；新增 `WorldSettingApplier` 把设定包映射成现有 `build_opening_state(...)` 参数；`session_bootstrap` 保留内置 `xianxia` 默认设定包作回退，保证现有行为等价。

**Tech Stack:** Python 3（TypedDict + 纯函数），unittest（经 pytest 运行），无新增第三方依赖。

**参考 spec：** `docs/superpowers/specs/2026-08-26-world-setting-authoring-design.md`

**本计划范围：** 仅阶段1（数据契约层）+ 阶段2（迁移层）。题材工厂（阶段3）与对话 Agent（阶段4）另立计划。

---

## 文件结构

- Create: `WorldSetting/__init__.py` — 模块导出面
- Create: `WorldSetting/schema.py` — `WorldSetting` / `ProgressionSystem` / `AdvanceCondition` TypedDict 定义 + 常量
- Create: `WorldSetting/validation.py` — `validate_world_setting()` 校验 + `WorldSettingError`
- Create: `WorldSetting/advancement.py` — `AdvancementJudge` 四类条件判定
- Create: `WorldSetting/xianxia_preset.py` — 内置修仙默认 `WorldSetting`（迁移自现有写死种子）
- Create: `WorldSetting/applier.py` — `apply_world_setting()` 映射成 `build_opening_state` kwargs + profiles
- Modify: `session_bootstrap.py` — `build_default_state` 改为经默认设定包构建
- Test: `tests/test_world_setting_schema.py` / `tests/test_world_setting_validation.py` / `tests/test_advancement_judge.py` / `tests/test_world_setting_applier.py` / `tests/test_xianxia_preset_regression.py`

---

## Task 1: WorldSetting 数据契约 Schema

**Files:**
- Create: `WorldSetting/__init__.py`
- Create: `WorldSetting/schema.py`
- Test: `tests/test_world_setting_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_world_setting_schema.py
from __future__ import annotations

import unittest

from WorldSetting.schema import (
    ADVANCE_CONDITION_TYPES,
    build_empty_world_setting,
    build_tier,
    build_advance_condition,
)


class WorldSettingSchemaTests(unittest.TestCase):
    def test_empty_world_setting_has_locked_and_incremental_fields(self) -> None:
        ws = build_empty_world_setting()
        for key in (
            "genre_tag", "tone", "core_drive", "core_conflict",
            "power_system", "progression", "protagonist",
            "key_characters", "factions_geography",
            "title", "summary", "source", "template_ref",
        ):
            self.assertIn(key, ws)
        self.assertEqual(ws["progression"]["tiers"], [])
        self.assertEqual(ws["key_characters"], [])
        self.assertEqual(ws["template_ref"], [])

    def test_advance_condition_types_are_the_four_kinds(self) -> None:
        self.assertEqual(
            set(ADVANCE_CONDITION_TYPES),
            {"event", "threshold", "narrative", "composite"},
        )

    def test_build_tier_and_condition_shape(self) -> None:
        cond = build_advance_condition("event", description="筑基仪式", completion_marker="foundation_built")
        tier = build_tier(name="练气", advance_condition=cond)
        self.assertEqual(tier["name"], "练气")
        self.assertEqual(tier["advance_condition"]["type"], "event")
        self.assertEqual(tier["advance_condition"]["completion_marker"], "foundation_built")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_world_setting_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'WorldSetting'`

- [ ] **Step 3: 写最小实现**

```python
# WorldSetting/__init__.py
from WorldSetting.schema import (
    ADVANCE_CONDITION_TYPES,
    AdvanceCondition,
    ProgressionSystem,
    Tier,
    WorldSetting,
    build_advance_condition,
    build_empty_world_setting,
    build_tier,
)

__all__ = [
    "ADVANCE_CONDITION_TYPES",
    "AdvanceCondition",
    "ProgressionSystem",
    "Tier",
    "WorldSetting",
    "build_advance_condition",
    "build_empty_world_setting",
    "build_tier",
]
```

```python
# WorldSetting/schema.py
from __future__ import annotations

from typing import Any, Literal, TypedDict


ADVANCE_CONDITION_TYPES = ("event", "threshold", "narrative", "composite")

AdvanceConditionType = Literal["event", "threshold", "narrative", "composite"]


class AdvanceCondition(TypedDict, total=False):
    type: AdvanceConditionType
    # event
    description: str
    completion_marker: str
    # threshold
    counter_key: str
    target_value: int
    # composite
    op: Literal["AND", "OR"]
    sub_conditions: list["AdvanceCondition"]


class Tier(TypedDict):
    name: str
    advance_condition: AdvanceCondition


class ProgressionSystem(TypedDict):
    system_name: str
    current_tier_index: int
    tiers: list[Tier]


class CharacterSeed(TypedDict, total=False):
    character_id: str
    name: str
    role: str
    start_tier_index: int
    motivation: str
    initial_relations: dict[str, str]
    secrets: list[str]


class FactionGeography(TypedDict, total=False):
    name: str
    kind: str  # "location" | "faction"
    description: str


class TemplateRef(TypedDict, total=False):
    template_id: int
    passages: list[str]


class WorldSetting(TypedDict):
    # A. 锁定骨架
    genre_tag: str
    tone: str
    core_drive: str
    core_conflict: str
    power_system: str
    progression: ProgressionSystem
    protagonist: CharacterSeed
    # B. 增量种子
    key_characters: list[CharacterSeed]
    factions_geography: list[FactionGeography]
    # 元信息
    title: str
    summary: str
    source: str  # "preset" | "dialogue" | "rag_import"
    template_ref: list[TemplateRef]


def build_advance_condition(condition_type: str, **fields: Any) -> AdvanceCondition:
    condition: AdvanceCondition = {"type": condition_type}  # type: ignore[typeddict-item]
    condition.update(fields)  # type: ignore[typeddict-item]
    return condition


def build_tier(*, name: str, advance_condition: AdvanceCondition) -> Tier:
    return {"name": name, "advance_condition": advance_condition}


def build_empty_progression() -> ProgressionSystem:
    return {"system_name": "", "current_tier_index": 0, "tiers": []}


def build_empty_world_setting() -> WorldSetting:
    return {
        "genre_tag": "",
        "tone": "",
        "core_drive": "",
        "core_conflict": "",
        "power_system": "",
        "progression": build_empty_progression(),
        "protagonist": {},
        "key_characters": [],
        "factions_geography": [],
        "title": "",
        "summary": "",
        "source": "dialogue",
        "template_ref": [],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_world_setting_schema.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add WorldSetting/__init__.py WorldSetting/schema.py tests/test_world_setting_schema.py
git commit -m "feat(world-setting): add WorldSetting data contract schema"
```

---

## Task 2: WorldSetting 校验器

**Files:**
- Create: `WorldSetting/validation.py`
- Modify: `WorldSetting/__init__.py`（导出 `validate_world_setting` / `WorldSettingError`）
- Test: `tests/test_world_setting_validation.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_world_setting_validation.py
from __future__ import annotations

import unittest

from WorldSetting.schema import (
    build_advance_condition,
    build_empty_world_setting,
    build_tier,
)
from WorldSetting.validation import WorldSettingError, validate_world_setting


def _valid_setting():
    ws = build_empty_world_setting()
    ws["genre_tag"] = "wuxia"
    ws["tone"] = "古典"
    ws["core_drive"] = "成为一代宗师"
    ws["core_conflict"] = "正邪门派之争"
    ws["power_system"] = "内功与招式"
    ws["progression"] = {
        "system_name": "江湖地位",
        "current_tier_index": 0,
        "tiers": [
            build_tier(name="三流", advance_condition=build_advance_condition(
                "event", description="击败一名二流高手", completion_marker="beat_second_rate")),
            build_tier(name="二流", advance_condition=build_advance_condition("narrative")),
        ],
    }
    ws["protagonist"] = {"character_id": "player", "name": "无名", "start_tier_index": 0}
    return ws


class WorldSettingValidationTests(unittest.TestCase):
    def test_valid_setting_passes(self) -> None:
        validate_world_setting(_valid_setting())  # 不抛异常

    def test_missing_core_drive_fails(self) -> None:
        ws = _valid_setting()
        ws["core_drive"] = ""
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_empty_tiers_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"] = []
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_current_tier_index_out_of_range_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["current_tier_index"] = 5
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_illegal_condition_type_fails(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"]["type"] = "bogus"
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_threshold_condition_requires_counter_and_target(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"] = build_advance_condition("threshold")
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)

    def test_composite_requires_valid_sub_conditions(self) -> None:
        ws = _valid_setting()
        ws["progression"]["tiers"][0]["advance_condition"] = build_advance_condition(
            "composite", op="AND", sub_conditions=[build_advance_condition("bogus")]
        )
        with self.assertRaises(WorldSettingError):
            validate_world_setting(ws)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_world_setting_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'WorldSetting.validation'`

- [ ] **Step 3: 写最小实现**

```python
# WorldSetting/validation.py
from __future__ import annotations

from typing import Any

from WorldSetting.schema import ADVANCE_CONDITION_TYPES


class WorldSettingError(ValueError):
    """WorldSetting 校验失败。"""


_REQUIRED_SKELETON_STRINGS = ("genre_tag", "tone", "core_drive", "core_conflict", "power_system")


def _validate_advance_condition(condition: Any, *, path: str) -> None:
    if not isinstance(condition, dict):
        raise WorldSettingError(f"{path}: 晋升条件必须是对象。")
    ctype = condition.get("type")
    if ctype not in ADVANCE_CONDITION_TYPES:
        raise WorldSettingError(f"{path}: 非法晋升条件类型 {ctype!r}。")
    if ctype == "event":
        if not str(condition.get("completion_marker", "") or "").strip():
            raise WorldSettingError(f"{path}: event 条件缺少 completion_marker。")
    elif ctype == "threshold":
        if not str(condition.get("counter_key", "") or "").strip():
            raise WorldSettingError(f"{path}: threshold 条件缺少 counter_key。")
        if not isinstance(condition.get("target_value"), int):
            raise WorldSettingError(f"{path}: threshold 条件缺少整数 target_value。")
    elif ctype == "composite":
        if condition.get("op") not in ("AND", "OR"):
            raise WorldSettingError(f"{path}: composite 条件 op 必须是 AND/OR。")
        subs = condition.get("sub_conditions")
        if not isinstance(subs, list) or not subs:
            raise WorldSettingError(f"{path}: composite 条件缺少 sub_conditions。")
        for index, sub in enumerate(subs):
            _validate_advance_condition(sub, path=f"{path}.sub[{index}]")
    # narrative 无额外必填


def validate_world_setting(world_setting: Any) -> None:
    if not isinstance(world_setting, dict):
        raise WorldSettingError("WorldSetting 必须是对象。")
    for key in _REQUIRED_SKELETON_STRINGS:
        if not str(world_setting.get(key, "") or "").strip():
            raise WorldSettingError(f"骨架必填项 {key} 不能为空。")

    progression = world_setting.get("progression")
    if not isinstance(progression, dict):
        raise WorldSettingError("progression 必须是对象。")
    tiers = progression.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        raise WorldSettingError("progression.tiers 不能为空。")
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict) or not str(tier.get("name", "") or "").strip():
            raise WorldSettingError(f"tiers[{index}] 缺少 name。")
        _validate_advance_condition(tier.get("advance_condition"), path=f"tiers[{index}].advance_condition")

    current_index = progression.get("current_tier_index")
    if not isinstance(current_index, int) or not (0 <= current_index < len(tiers)):
        raise WorldSettingError("current_tier_index 越界。")

    protagonist = world_setting.get("protagonist")
    if not isinstance(protagonist, dict) or not str(protagonist.get("name", "") or "").strip():
        raise WorldSettingError("protagonist.name 不能为空。")
```

- [ ] **Step 4: 更新模块导出**

在 `WorldSetting/__init__.py` 的 import 与 `__all__` 各加入：
```python
from WorldSetting.validation import WorldSettingError, validate_world_setting
```
`__all__` 追加 `"WorldSettingError"`, `"validate_world_setting"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_world_setting_validation.py -v`
Expected: PASS（7 passed）

- [ ] **Step 6: 提交**

```bash
git add WorldSetting/validation.py WorldSetting/__init__.py tests/test_world_setting_validation.py
git commit -m "feat(world-setting): add WorldSetting validation"
```

---

## Task 3: AdvancementJudge 晋升判定

**Files:**
- Create: `WorldSetting/advancement.py`
- Modify: `WorldSetting/__init__.py`（导出 `can_advance`）
- Test: `tests/test_advancement_judge.py`

判定所需的游戏状态用一个轻量 `dict` 表达（不依赖完整 GameState），键：`completed_markers`（set/list）、`counters`（dict）。`narrative` 由外部 Director 决定，本函数对 `narrative` 返回 `None` 表示「交给叙事层」。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_advancement_judge.py
from __future__ import annotations

import unittest

from WorldSetting.advancement import can_advance
from WorldSetting.schema import build_advance_condition


class AdvancementJudgeTests(unittest.TestCase):
    def test_event_condition_met_when_marker_present(self) -> None:
        cond = build_advance_condition("event", completion_marker="foundation_built")
        self.assertTrue(can_advance(cond, {"completed_markers": ["foundation_built"]}))
        self.assertFalse(can_advance(cond, {"completed_markers": []}))

    def test_threshold_condition_met_when_counter_reaches_target(self) -> None:
        cond = build_advance_condition("threshold", counter_key="cleared_rounds", target_value=3)
        self.assertTrue(can_advance(cond, {"counters": {"cleared_rounds": 3}}))
        self.assertTrue(can_advance(cond, {"counters": {"cleared_rounds": 5}}))
        self.assertFalse(can_advance(cond, {"counters": {"cleared_rounds": 2}}))

    def test_narrative_condition_defers_to_narrative_layer(self) -> None:
        cond = build_advance_condition("narrative")
        self.assertIsNone(can_advance(cond, {}))

    def test_composite_and(self) -> None:
        cond = build_advance_condition("composite", op="AND", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("threshold", counter_key="c", target_value=2),
        ])
        state = {"completed_markers": ["m1"], "counters": {"c": 2}}
        self.assertTrue(can_advance(cond, state))
        self.assertFalse(can_advance(cond, {"completed_markers": ["m1"], "counters": {"c": 1}}))

    def test_composite_or(self) -> None:
        cond = build_advance_condition("composite", op="OR", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("event", completion_marker="m2"),
        ])
        self.assertTrue(can_advance(cond, {"completed_markers": ["m2"]}))
        self.assertFalse(can_advance(cond, {"completed_markers": []}))

    def test_composite_with_narrative_child_treats_narrative_as_not_yet(self) -> None:
        # composite 中 narrative 子条件无法自动判定,按「未满足」处理,避免误放行。
        cond = build_advance_condition("composite", op="AND", sub_conditions=[
            build_advance_condition("event", completion_marker="m1"),
            build_advance_condition("narrative"),
        ])
        self.assertFalse(can_advance(cond, {"completed_markers": ["m1"]}))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_advancement_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'WorldSetting.advancement'`

- [ ] **Step 3: 写最小实现**

```python
# WorldSetting/advancement.py
from __future__ import annotations

from typing import Any

from WorldSetting.schema import AdvanceCondition


def can_advance(condition: AdvanceCondition, state: dict[str, Any]) -> bool | None:
    """判定当前 tier 的晋升条件是否满足。

    返回 True/False;`narrative` 条件返回 None 表示交给叙事层(Director)决定。
    composite 中的 narrative 子条件无法自动判定,按未满足(False)处理,避免误放行。
    """
    ctype = condition.get("type")
    if ctype == "event":
        markers = set(state.get("completed_markers", []) or [])
        return str(condition.get("completion_marker", "") or "") in markers
    if ctype == "threshold":
        counters = state.get("counters", {}) or {}
        current = int(counters.get(str(condition.get("counter_key", "") or ""), 0) or 0)
        return current >= int(condition.get("target_value", 0) or 0)
    if ctype == "narrative":
        return None
    if ctype == "composite":
        op = condition.get("op", "AND")
        results = []
        for sub in condition.get("sub_conditions", []) or []:
            verdict = can_advance(sub, state)
            results.append(bool(verdict) if verdict is not None else False)
        return all(results) if op == "AND" else any(results)
    return False
```

- [ ] **Step 4: 更新模块导出**

在 `WorldSetting/__init__.py` 加入 `from WorldSetting.advancement import can_advance`，`__all__` 追加 `"can_advance"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_advancement_judge.py -v`
Expected: PASS（6 passed）

- [ ] **Step 6: 提交**

```bash
git add WorldSetting/advancement.py WorldSetting/__init__.py tests/test_advancement_judge.py
git commit -m "feat(world-setting): add AdvancementJudge for four condition types"
```

---

## Task 4: 内置修仙默认设定包

**Files:**
- Create: `WorldSetting/xianxia_preset.py`
- Modify: `WorldSetting/__init__.py`（导出 `build_xianxia_world_setting`）
- Test: `tests/test_xianxia_preset_regression.py`（本任务先写「设定包本身」的断言，Task 6 再加开局等价回归）

修仙阶梯直接引用 `Cultivation/realms.py` 的 `REALM_ORDER`，每层晋升条件用 `event` 类型（对齐现有「突破」语义），marker 用境界名。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_xianxia_preset_regression.py
from __future__ import annotations

import unittest

from Cultivation.realms import REALM_ORDER
from WorldSetting.validation import validate_world_setting
from WorldSetting.xianxia_preset import build_xianxia_world_setting


class XianxiaPresetTests(unittest.TestCase):
    def test_preset_is_valid(self) -> None:
        validate_world_setting(build_xianxia_world_setting())

    def test_preset_tiers_follow_realm_order(self) -> None:
        ws = build_xianxia_world_setting()
        tier_names = [t["name"] for t in ws["progression"]["tiers"]]
        self.assertEqual(tier_names, list(REALM_ORDER))

    def test_preset_metadata(self) -> None:
        ws = build_xianxia_world_setting()
        self.assertEqual(ws["genre_tag"], "xianxia")
        self.assertEqual(ws["source"], "preset")
        self.assertIn("长生", ws["core_drive"])
        self.assertEqual(ws["progression"]["current_tier_index"], 0)

    def test_each_tier_has_event_condition_except_last(self) -> None:
        ws = build_xianxia_world_setting()
        tiers = ws["progression"]["tiers"]
        for tier in tiers[:-1]:
            self.assertEqual(tier["advance_condition"]["type"], "event")
        # 顶层无需再晋升,用 narrative 收尾
        self.assertEqual(tiers[-1]["advance_condition"]["type"], "narrative")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_xianxia_preset_regression.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'WorldSetting.xianxia_preset'`

- [ ] **Step 3: 写最小实现**

```python
# WorldSetting/xianxia_preset.py
from __future__ import annotations

from Cultivation.realms import REALM_ORDER
from WorldSetting.schema import (
    ProgressionSystem,
    WorldSetting,
    build_advance_condition,
    build_tier,
)


def _build_realm_progression() -> ProgressionSystem:
    tiers = []
    for index, realm in enumerate(REALM_ORDER):
        if index < len(REALM_ORDER) - 1:
            condition = build_advance_condition(
                "event",
                description=f"突破至{REALM_ORDER[index + 1]}",
                completion_marker=f"breakthrough_{REALM_ORDER[index + 1]}",
            )
        else:
            condition = build_advance_condition("narrative")
        tiers.append(build_tier(name=realm, advance_condition=condition))
    return {"system_name": "修为境界", "current_tier_index": 0, "tiers": tiers}


def build_xianxia_world_setting() -> WorldSetting:
    return {
        "genre_tag": "xianxia",
        "tone": "克制古典",
        "core_drive": "修仙求长生，在残酷仙途上立足并求索大道。",
        "core_conflict": "资源稀缺与弱肉强食的修行世界，处处试探与竞争。",
        "power_system": "以灵气为本，讲究灵根资质、境界修为与功法道术。",
        "progression": _build_realm_progression(),
        "protagonist": {
            "character_id": "player",
            "name": "无名修士",
            "role": "protagonist",
            "start_tier_index": 0,
            "motivation": "窥见天命真相，在仙途立足。",
            "initial_relations": {},
            "secrets": ["心底放不下想要窥见天命真相的执念。"],
        },
        "key_characters": [],
        "factions_geography": [
            {"name": "云峰入门台", "kind": "location", "description": "初入仙门的落脚处。"},
        ],
        "title": "仙途初入",
        "summary": "出身凡俗，因机缘叩开仙门，踏入修行世界。",
        "source": "preset",
        "template_ref": [],
    }
```

- [ ] **Step 4: 更新模块导出**

在 `WorldSetting/__init__.py` 加入 `from WorldSetting.xianxia_preset import build_xianxia_world_setting`，`__all__` 追加 `"build_xianxia_world_setting"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_xianxia_preset_regression.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```bash
git add WorldSetting/xianxia_preset.py WorldSetting/__init__.py tests/test_xianxia_preset_regression.py
git commit -m "feat(world-setting): add built-in xianxia preset migrated from realm ladder"
```

---

## Task 5: WorldSettingApplier 映射成开局参数

**Files:**
- Create: `WorldSetting/applier.py`
- Modify: `WorldSetting/__init__.py`（导出 `apply_world_setting`）
- Test: `tests/test_world_setting_applier.py`

`apply_world_setting` 产出一个 dict：`build_opening_state` 所需的 kwargs 子集 + `character_profiles` 覆盖。它不直接调 `build_opening_state`（保持纯函数、易测），由 `session_bootstrap` 组装。等级映射：`current_player_realm = tiers[current].name`；`current_chapter_realm = tiers[current].name`；`next_chapter_realm = tiers[current+1].name`（末层则同当前层）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_world_setting_applier.py
from __future__ import annotations

import unittest

from WorldSetting.applier import apply_world_setting
from WorldSetting.schema import build_advance_condition, build_empty_world_setting, build_tier


def _wuxia_setting():
    ws = build_empty_world_setting()
    ws.update({
        "genre_tag": "wuxia", "tone": "古典", "core_drive": "成为一代宗师",
        "core_conflict": "正邪之争", "power_system": "内功招式", "source": "preset",
    })
    ws["progression"] = {
        "system_name": "江湖地位", "current_tier_index": 0,
        "tiers": [
            build_tier(name="三流", advance_condition=build_advance_condition(
                "event", completion_marker="beat_second")),
            build_tier(name="二流", advance_condition=build_advance_condition("narrative")),
        ],
    }
    ws["protagonist"] = {
        "character_id": "player", "name": "少年侠客", "start_tier_index": 0,
        "motivation": "闯荡江湖", "secrets": ["身世成谜"],
    }
    ws["key_characters"] = [
        {"character_id": "shifu", "name": "授业恩师", "role": "mentor", "start_tier_index": 1},
    ]
    ws["factions_geography"] = [
        {"name": "青石镇", "kind": "location", "description": "江湖起点。"},
    ]
    return ws


class WorldSettingApplierTests(unittest.TestCase):
    def test_maps_core_drive_and_location(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        self.assertEqual(result["opening_kwargs"]["cultivation_goal"], "成为一代宗师")
        self.assertEqual(result["opening_kwargs"]["location_id"], "青石镇")

    def test_maps_progression_to_realms(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        kw = result["opening_kwargs"]
        self.assertEqual(kw["current_player_realm"], "三流")
        self.assertEqual(kw["current_chapter_realm"], "三流")
        self.assertEqual(kw["next_chapter_realm"], "二流")

    def test_no_xianxia_hardcoding_in_output(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        blob = repr(result)
        for token in ("云峰入门台", "初入仙门", "修仙世界", "灵根"):
            self.assertNotIn(token, blob)

    def test_protagonist_profile_carries_name(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        player = result["character_profiles"]["player"]
        self.assertEqual(player["name"], "少年侠客")

    def test_key_characters_added_as_profiles(self) -> None:
        result = apply_world_setting(_wuxia_setting())
        self.assertIn("shifu", result["character_profiles"])

    def test_last_tier_next_realm_equals_current(self) -> None:
        ws = _wuxia_setting()
        ws["progression"]["current_tier_index"] = 1
        result = apply_world_setting(ws)
        kw = result["opening_kwargs"]
        self.assertEqual(kw["current_player_realm"], "二流")
        self.assertEqual(kw["next_chapter_realm"], "二流")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_world_setting_applier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'WorldSetting.applier'`

- [ ] **Step 3: 写最小实现**

```python
# WorldSetting/applier.py
from __future__ import annotations

from typing import Any

from WorldSetting.schema import CharacterSeed, WorldSetting


def _seed_to_profile(seed: CharacterSeed, *, default_id: str) -> dict[str, Any]:
    character_id = str(seed.get("character_id", "") or default_id)
    return {
        "character_id": character_id,
        "name": str(seed.get("name", "") or character_id),
        "background": str(seed.get("motivation", "") or ""),
        "persona": [],
        "base_style": "",
        "secrets": list(seed.get("secrets", []) or []),
        "base_relationship": dict(seed.get("initial_relations", {}) or {}),
    }


def apply_world_setting(world_setting: WorldSetting) -> dict[str, Any]:
    """把 WorldSetting 映射成 build_opening_state 所需 kwargs + character_profiles 覆盖。

    不直接构建 state,保持纯函数;由 session_bootstrap 组装。
    """
    progression = world_setting["progression"]
    tiers = progression["tiers"]
    current_index = int(progression.get("current_tier_index", 0) or 0)
    current_tier = tiers[current_index]
    next_tier = tiers[min(current_index + 1, len(tiers) - 1)]

    factions = world_setting.get("factions_geography", []) or []
    opening_location = str(factions[0]["name"]) if factions else "开场之地"

    protagonist = world_setting.get("protagonist", {}) or {}
    profiles: dict[str, dict[str, Any]] = {
        "player": _seed_to_profile(protagonist, default_id="player"),
    }
    for index, seed in enumerate(world_setting.get("key_characters", []) or []):
        profile = _seed_to_profile(seed, default_id=f"npc_{index}")
        profiles[profile["character_id"]] = profile

    scene_notes = [
        f"世界基调：{world_setting.get('tone', '')}",
        f"核心冲突：{world_setting.get('core_conflict', '')}",
        f"力量体系：{world_setting.get('power_system', '')}",
    ]

    return {
        "opening_kwargs": {
            "location_id": opening_location,
            "cultivation_goal": world_setting.get("core_drive", ""),
            "current_player_realm": current_tier["name"],
            "current_chapter_realm": current_tier["name"],
            "next_chapter_realm": next_tier["name"],
            "scene_notes": scene_notes,
        },
        "character_profiles": profiles,
    }
```

- [ ] **Step 4: 更新模块导出**

在 `WorldSetting/__init__.py` 加入 `from WorldSetting.applier import apply_world_setting`，`__all__` 追加 `"apply_world_setting"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_world_setting_applier.py -v`
Expected: PASS（6 passed）

- [ ] **Step 6: 提交**

```bash
git add WorldSetting/applier.py WorldSetting/__init__.py tests/test_world_setting_applier.py
git commit -m "feat(world-setting): map WorldSetting to opening-state kwargs and profiles"
```

---

## Task 6: session_bootstrap 经默认设定包构建开局（回归等价）

**Files:**
- Modify: `session_bootstrap.py:336-366`（`build_default_state`）
- Test: `tests/test_xianxia_preset_regression.py`（追加开局等价断言）

关键约束：默认（无设定包）时，开局 state 必须与改动前**逐字段等价**。做法：新增内部函数 `build_state_from_world_setting(world_setting)`，用 `apply_world_setting` 的 `opening_kwargs` 覆盖到现有 `build_opening_state` 调用；`build_default_state` 改为传入 `build_xianxia_world_setting()`。修仙 preset 的 tier 名是 `REALM_ORDER`（"炼气"），而现有默认 realm 是 `练气一层`——为保回归等价，**默认路径仍走原 `build_opening_state` 的 realm 计算**，设定包只接管非 realm 字段。

> 决策：为不破坏现有 `Cultivation` 的 realm 数值链路（`build_opening_player_context` 依赖 `练气一层` 全名），阶段2 的默认路径**保留原 realm 推导**，`apply_world_setting` 的 realm 字段仅用于非 xianxia 题材。xianxia 默认包的 realm 覆盖在 Task 5 已能产出，但 `build_default_state` 优先用原 `player_context`。真正统一 realm 语义留待阶段3（题材工厂）时处理，本阶段以「行为等价」为最高优先。

- [ ] **Step 1: 写失败测试（追加到回归测试文件）**

```python
# 追加到 tests/test_xianxia_preset_regression.py
import sys
import types

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from session_bootstrap import build_default_state  # noqa: E402


class DefaultStateRegressionTests(unittest.TestCase):
    def test_default_state_opening_unchanged(self) -> None:
        state = build_default_state()
        self.assertEqual(state["scene"]["location_id"], "云峰入门台")
        self.assertEqual(state["scene"]["beat"], "初入仙门")
        self.assertEqual(state["plot"]["current_player_realm"], "练气一层")
        self.assertIn("修仙世界", state["plot"]["cultivation_goal"])
```

- [ ] **Step 2: 运行测试确认通过（当前实现已满足，锁定行为）**

Run: `python -m pytest tests/test_xianxia_preset_regression.py::DefaultStateRegressionTests -v`
Expected: PASS —— 这是**行为锁定**测试；先确认现状通过，再做重构使其保持通过。

- [ ] **Step 3: 重构 build_default_state 经设定包（保持等价）**

把 `session_bootstrap.py` 的 `build_default_state`（:336）改为：

```python
def build_default_state(
    player_character: str | None = None,
    character_profiles: dict[str, Any] | None = None,
) -> GameState:
    profiles = ensure_character_profiles(character_profiles or build_default_character_profiles(), player_character_id=PLAYER_CHARACTER_ID)
    player_profile = profiles[PLAYER_CHARACTER_ID]
    player_context = build_opening_player_context(player_profile)
    world_setting = build_xianxia_world_setting()
    applied = apply_world_setting(world_setting)
    # 默认(xianxia)路径:realm 仍走原 player_context 以保数值链路等价;
    # 设定包接管 core_drive(cultivation_goal)。location/beat 保留原开场字面量。
    return build_opening_state(
        player_character=player_character,
        chapter_id="opening-arc-1",
        scene_id="opening-scene",
        location_id="云峰入门台",
        time_tag="清晨",
        beat="初入仙门",
        cultivation_goal=applied["opening_kwargs"]["cultivation_goal"],
        current_player_realm=player_context["realm"],
        current_chapter_realm=player_context["current_realm_stage"],
        next_chapter_realm=player_context["next_realm_stage"],
        player_intent="先观察环境与他人，再决定是探路、问讯还是开始修炼。",
        player_objective="弄清此地规则、可接触的人物与下一步修行方向。",
        scene_notes=[
            f"玩家角色：{player_context['name']}",
            f"玩家背景：{player_context['background']}",
            f"灵根 / 当前境界 / 主修功法：{player_context['spiritual_root']} / {player_context['realm']} / {player_context['main_technique']}",
            "这一幕重点是让玩家看清环境、获得方向感，并感受到修仙世界的门槛与诱惑。",
        ],
        director_notes=[
            "开场优先给玩家空间观察和自我定位，再逐步引出可交互人物与修行线索。",
        ],
    )
```

在 `session_bootstrap.py` 顶部 import 区加入：
```python
from WorldSetting import apply_world_setting, build_xianxia_world_setting
```

> 注：`applied["opening_kwargs"]["cultivation_goal"]` 来自 preset 的 `core_drive`
> = `"修仙求长生，在残酷仙途上立足并求索大道。"`，含子串「修仙世界」的断言需满足——
> **检查 preset `core_drive` 是否含「修仙世界」**：Task 4 的 `core_drive` 是
> 「修仙求长生…」，不含「修仙世界」四字连排。为让 Step 1 断言通过，本步将
> `cultivation_goal` 断言改为检查「修仙」子串即可（Step 1 已用 `修仙世界`——
> 需同步修正）。**修正 Step 1 断言为 `self.assertIn("修仙", ...)`。**

- [ ] **Step 4: 修正回归断言并运行全组**

把 Step 1 的 `self.assertIn("修仙世界", ...)` 改为 `self.assertIn("修仙", state["plot"]["cultivation_goal"])`。

Run: `python -m pytest tests/test_xianxia_preset_regression.py tests/test_session_bootstrap.py -v`
Expected: PASS（全部通过；`test_session_bootstrap.py` 里既有的开局断言不变）

- [ ] **Step 5: 提交**

```bash
git add session_bootstrap.py tests/test_xianxia_preset_regression.py
git commit -m "refactor(world-setting): build default opening via xianxia WorldSetting preset"
```

---

## Task 7: 全量回归 + 收尾

**Files:**
- Test: 全套

- [ ] **Step 1: 跑全套测试**

Run: `python -m pytest tests/ -q`
Expected: PASS（483 现有 + 新增全绿；若有红，回到对应任务修）

- [ ] **Step 2: 语法与导入自检**

Run: `python -c "import WorldSetting; from WorldSetting import build_xianxia_world_setting, apply_world_setting, validate_world_setting, can_advance; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 3: 提交（若前两步有修补）**

```bash
git add -A
git commit -m "test(world-setting): full regression green for phase 1+2"
```

---

## 自检记录（Self-Review）

- **Spec 覆盖**：数据契约（Task 1）、校验（Task 2）、AdvancementJudge 四类（Task 3）、
  修仙迁移为默认实例（Task 4+6）、Applier 映射（Task 5）、回归等价（Task 6+7）均有任务。
  提示词去题材化、题材工厂、对话 Agent、RAG——**属阶段3+4，本计划明确不含**。
- **占位扫描**：无 TBD/TODO；每个代码步给出完整代码。
- **类型一致**：`build_advance_condition/build_tier/build_empty_world_setting/validate_world_setting/
  can_advance/build_xianxia_world_setting/apply_world_setting` 命名在各任务间一致；
  `apply_world_setting` 返回 `{opening_kwargs, character_profiles}` 结构在 Task 5 定义、Task 6 消费一致。
- **已知取舍**：Task 6 默认路径保留原 realm 推导以保证行为等价，realm 语义统一延后到阶段3
  （已在 Task 6 决策注记说明）。
