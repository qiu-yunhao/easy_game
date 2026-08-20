from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_state,
    build_graph_dependencies,
)


class MemoryConsolidationSmokeTests(unittest.TestCase):
    """End-to-end smoke for the slimmed two-tier memory model.

    Proves a full actor-context build works on the non-LLM (heuristic) path
    with no KeyErrors on removed fields: ActorMemoryContext.long_term is gone,
    and per-character legacy memory queues are no longer in state.
    """

    def test_actor_context_build_has_no_removed_fields(self) -> None:
        # 1. Graph deps on the non-agent / non-LLM path (mode != agent-first/live).
        deps = build_graph_dependencies("heuristic")
        # 2. Default initial game state.
        state = build_default_state()
        # 3. Actor memory provider off deps.
        provider = deps.actor_memory_provider
        self.assertIsNotNone(provider)

        # 4. Build the context for an actor that actually exists in the state.
        #    The default state carries exactly one character: the player.
        actor_id = PLAYER_CHARACTER_ID
        self.assertIn(actor_id, state["characters"])
        ctx = provider.build(actor_id, state)

        # 5. Slimmed two-tier context: short_term survives, long_term is gone.
        self.assertIsNotNone(ctx.short_term)
        self.assertFalse(hasattr(ctx, "long_term"))

        # 6. No legacy per-character memory queues remain in state.
        for character in state["characters"].values():
            memory = character.get("memory")
            if isinstance(memory, dict):
                self.assertNotIn("long_term_memory", memory)
                self.assertNotIn("short_term_memory", memory)
                self.assertNotIn("consolidated_memory", memory)


if __name__ == "__main__":
    unittest.main()
