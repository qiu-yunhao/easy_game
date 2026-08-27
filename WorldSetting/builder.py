from __future__ import annotations

from copy import deepcopy
from typing import Any

from WorldSetting.genre_factory import get_template
from WorldSetting.schema import build_empty_world_setting
from WorldSetting.validation import WorldSettingError, validate_world_setting


FIELDS = ("genre_tag", "tone", "core_drive", "core_conflict", "power_system", "progression", "protagonist", "key_characters", "factions_geography", "title", "summary")

_QUESTIONS = {
    "genre_tag": "想创作什么题材？可选预设或自由填写。",
    "tone": "这个世界整体的基调是什么？",
    "core_drive": "主角长期想达成什么？",
    "core_conflict": "这个世界最主要的张力或冲突是什么？",
    "power_system": "人物能凭什么获得力量、地位或生存空间？",
    "progression": "请确认等级体系与主角的起始层级。",
    "protagonist": "请确认主角的名字、动机与秘密。",
    "key_characters": "请确认 1–2 名开局关键配角。",
    "factions_geography": "请确认开场地点及初始势力种子。",
    "title": "这份世界设定叫什么？",
    "summary": "请用一两句话概述开局。",
}


class WorldBuilderWorkflow:
    """A deterministic draft owner; an LLM may suggest answers but never owns state."""

    def __init__(self, *, genre_tag: str | None = None) -> None:
        self.draft: dict[str, Any] = get_template(genre_tag) if genre_tag else build_empty_world_setting()
        self.index = 0
        if genre_tag:
            self.index = 1  # The selected preset has already confirmed its genre.
        self.confirmed: set[str] = set(FIELDS[:self.index])

    @property
    def complete(self) -> bool:
        return self.index >= len(FIELDS)

    def view(self) -> dict[str, Any]:
        if self.complete:
            return {"status": "complete", "draft": deepcopy(self.draft), "next_field": "", "question": "设定已完成。", "options": []}
        field = FIELDS[self.index]
        options = []
        if field == "genre_tag":
            options = ["xianxia", "wuxia", "infinite_flow"]
        return {"status": "in_progress", "draft": deepcopy(self.draft), "next_field": field, "question": _QUESTIONS[field], "options": options}

    def answer(self, value: Any) -> dict[str, Any]:
        if self.complete:
            raise WorldSettingError("设定已经完成；请先应用或重新开始。")
        field = FIELDS[self.index]
        if field == "genre_tag" and isinstance(value, str) and value in {"xianxia", "wuxia", "infinite_flow"}:
            preset = get_template(value)
            self.draft = preset
            self.confirmed.add(field)
            self.index = 1
            return self.view()
        if field in {"progression", "protagonist"} and not isinstance(value, dict):
            raise WorldSettingError(f"{field} 必须是一个对象。")
        if field in {"key_characters", "factions_geography"} and not isinstance(value, list):
            raise WorldSettingError(f"{field} 必须是一个数组。")
        if field not in {"progression", "protagonist", "key_characters", "factions_geography"}:
            value = str(value or "").strip()
            if not value:
                raise WorldSettingError(f"{field} 不能为空。")
        self.draft[field] = deepcopy(value)
        self.confirmed.add(field)
        self.index += 1
        if self.complete:
            validate_world_setting(self.draft)
        return self.view()

    def add_template_reference(self, template_id: int, passages: list[str]) -> None:
        refs = self.draft.setdefault("template_ref", [])
        if not any(int(item.get("template_id", 0) or 0) == int(template_id) for item in refs if isinstance(item, dict)):
            refs.append({"template_id": int(template_id), "passages": list(passages)[:2]})
