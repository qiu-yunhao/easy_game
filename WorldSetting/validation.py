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
