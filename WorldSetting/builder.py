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

_PRESET_GENRES = ("xianxia", "wuxia", "infinite_flow")


class WorldBuilderWorkflow:
    """A deterministic draft owner; an LLM may suggest answers but never owns state."""

    def __init__(self, *, genre_tag: str | None = None) -> None:
        self.draft: dict[str, Any] = get_template(genre_tag) if genre_tag else build_empty_world_setting()
        self.confirmed: set[str] = set()
        if genre_tag:
            self.confirmed.add("genre_tag")
        self.index = self._next_unconfirmed_index()

    def _next_unconfirmed_index(self) -> int:
        return next(
            (idx for idx, field in enumerate(FIELDS) if field not in self.confirmed),
            len(FIELDS),
        )

    @property
    def complete(self) -> bool:
        return self.index >= len(FIELDS)

    def view(self) -> dict[str, Any]:
        if self.complete:
            return {"status": "complete", "draft": deepcopy(self.draft), "next_field": "", "question": "设定已完成。", "options": [], "unconfirmed_fields": []}
        field = FIELDS[self.index]
        options = list(_PRESET_GENRES) if field == "genre_tag" else []
        unconfirmed = [f for f in FIELDS if f not in self.confirmed]
        return {"status": "in_progress", "draft": deepcopy(self.draft), "next_field": field, "question": _QUESTIONS[field], "options": options, "unconfirmed_fields": unconfirmed}

    def _validate_field(self, field: str, value: Any) -> None:
        if field in {"progression", "protagonist"} and not isinstance(value, dict):
            raise WorldSettingError(f"{field} 必须是一个对象。")
        if field in {"key_characters", "factions_geography"} and not isinstance(value, list):
            raise WorldSettingError(f"{field} 必须是一个数组。")
        if field not in {"progression", "protagonist", "key_characters", "factions_geography"}:
            if not str(value or "").strip():
                raise WorldSettingError(f"{field} 不能为空。")

    def _set_field(self, field: str, value: Any) -> None:
        if field == "genre_tag" and isinstance(value, str) and value in _PRESET_GENRES and "genre_tag" not in self.confirmed:
            self.draft = get_template(value)
            self.confirmed.add("genre_tag")
            return
        self._validate_field(field, value)
        if field not in {"progression", "protagonist", "key_characters", "factions_geography"}:
            value = str(value or "").strip()
        self.draft[field] = deepcopy(value)
        self.confirmed.add(field)

    def _advance(self) -> dict[str, Any]:
        self.index = self._next_unconfirmed_index()
        if self.complete:
            validate_world_setting(self.draft)
        return self.view()

    def answer(self, value: Any) -> dict[str, Any]:
        if self.complete:
            raise WorldSettingError("设定已经完成；请先应用或重新开始。")
        self._set_field(FIELDS[self.index], value)
        return self._advance()

    def apply_patch(self, field_patch: dict[str, Any]) -> dict[str, Any]:
        if self.complete:
            raise WorldSettingError("设定已经完成；请先应用或重新开始。")
        if not isinstance(field_patch, dict) or not field_patch:
            raise WorldSettingError("field_patch 不能为空。")
        for field in field_patch:
            if field not in FIELDS:
                raise WorldSettingError(f"未知字段 {field!r}。")
        for field, value in field_patch.items():
            self._validate_field(field, value)
        for field, value in field_patch.items():
            self._set_field(field, value)
        return self._advance()

    def add_template_reference(self, template_id: int, passages: list[str]) -> None:
        refs = self.draft.setdefault("template_ref", [])
        if not any(int(item.get("template_id", 0) or 0) == int(template_id) for item in refs if isinstance(item, dict)):
            refs.append({"template_id": int(template_id), "passages": list(passages)[:2]})

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "draft": deepcopy(self.draft),
            "confirmed": sorted(self.confirmed),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "WorldBuilderWorkflow":
        workflow = cls.__new__(cls)
        workflow.draft = deepcopy(snapshot.get("draft") or {})
        workflow.confirmed = {field for field in snapshot.get("confirmed", []) if field in FIELDS}
        workflow.index = next(
            (idx for idx, field in enumerate(FIELDS) if field not in workflow.confirmed),
            len(FIELDS),
        )
        return workflow

    def is_consistent(self) -> bool:
        """Return True when every confirmed field is present and usable.

        Confirmed fields are tracked in ``self.confirmed`` (not by linear
        ``index``), so this stays correct even if questions are answered out of
        order. Unconfirmed fields may still be empty and are not validated.
        """
        if not isinstance(self.draft, dict):
            return False
        for field in self.confirmed:
            if field not in self.draft:
                return False
            value = self.draft[field]
            if field in {"genre_tag", "tone", "core_drive", "core_conflict", "power_system", "title", "summary"}:
                if not str(value or "").strip():
                    return False
            elif field == "progression":
                tiers = value.get("tiers") if isinstance(value, dict) else None
                if not isinstance(tiers, list) or not tiers:
                    return False
            elif field == "protagonist":
                if not isinstance(value, dict) or not str(value.get("name") or "").strip():
                    return False
            elif field in {"key_characters", "factions_geography"}:
                if not isinstance(value, list):
                    return False
        return True
