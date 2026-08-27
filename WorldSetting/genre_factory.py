from __future__ import annotations

from copy import deepcopy

from WorldSetting.schema import WorldSetting
from WorldSetting.validation import WorldSettingError, validate_world_setting
from WorldSetting.xianxia_preset import build_xianxia_world_setting
from WorldSetting.wuxia_preset import build_wuxia_world_setting
from WorldSetting.infinite_flow_preset import build_infinite_flow_world_setting


_BUILDERS = {"xianxia": build_xianxia_world_setting, "wuxia": build_wuxia_world_setting, "infinite_flow": build_infinite_flow_world_setting}


def list_genres() -> list[dict[str, str]]:
    return [{"genre_tag": tag, "title": str(builder()["title"]), "summary": str(builder()["summary"])} for tag, builder in _BUILDERS.items()]


def get_template(genre_tag: str) -> WorldSetting:
    builder = _BUILDERS.get(str(genre_tag or "").strip())
    if builder is None:
        raise WorldSettingError(f"未知题材：{genre_tag!r}。")
    setting = deepcopy(builder())
    validate_world_setting(setting)
    return setting
