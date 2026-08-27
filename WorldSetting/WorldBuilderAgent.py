from __future__ import annotations

from typing import Any

from BaseAgent import BaseAgent


WORLD_BUILDER_SYSTEM_PROMPT = """You guide a user through one WorldSetting field at a time.
Return strict JSON with a field_patch for the requested field, a next_question, options, and an optional reference_query.
Never change fields the user did not ask to change."""


class WorldBuilderAgent(BaseAgent):
    """Thin advisor. WorldBuilderWorkflow validates and owns all draft changes."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(system_prompt=WORLD_BUILDER_SYSTEM_PROMPT, temperature=kwargs.pop("temperature", 0.4), max_tokens=kwargs.pop("max_tokens", 800), **kwargs)
