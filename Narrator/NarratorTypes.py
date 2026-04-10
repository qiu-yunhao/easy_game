from __future__ import annotations

from typing import Literal, Optional, TypedDict


NarrationStylePreset = Literal["xianxia_default", "light_novel", "epic"]


class NarrationQueueItem(TypedDict):
    history_turn: int
    actor: str
    target: Optional[str]
    mode: str
    raw_content: str
    raw_spoken_text: str
    raw_nonverbal_action: str


class NarratedSegment(TypedDict):
    history_turn: int
    actor: str
    narrated_text: str
