from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

SNAPSHOT_VERSION = 1


def clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def clean_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def utc_now() -> datetime:
    return datetime.now(UTC)


def serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_numeric(value: Decimal | float | int | None) -> float:
    return 0.0 if value is None else float(value)


def dedupe_character_ids(character_ids: Iterable[Any]) -> list[str]:
    deduped: list[str] = []
    for raw in character_ids:
        character_id = clean_text(raw)
        if character_id and character_id not in deduped:
            deduped.append(character_id)
    return deduped
