from __future__ import annotations

from typing import Literal, Optional, TypedDict


class SchedulerDecision(TypedDict):
    next_actor: Optional[str]
    mode: Literal["speak", "action", "silence", "interrupt", "event"]
    eligible_actors: list[str]
    reason: str
