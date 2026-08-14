from __future__ import annotations

import dataclasses
import unittest

from Memory.context import ActorMemoryContext, LongTermView


class ActorMemoryContextTests(unittest.TestCase):
    def _ctx(self):
        return ActorMemoryContext(
            actor_id="A",
            persona={"character_id": "A", "name": "甲"},
            short_term=[{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}],
            long_term=LongTermView(
                consolidated=[], long_term=[], pinned=[],
            ),
            retrieved=[],
        )

    def test_context_is_frozen(self):
        ctx = self._ctx()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.actor_id = "B"  # type: ignore[misc]

    def test_long_term_view_is_frozen(self):
        view = LongTermView(consolidated=[], long_term=[], pinned=[])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            view.consolidated = [1]  # type: ignore[misc]

    def test_context_holds_references_not_deep_copies(self):
        short = [{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}]
        ctx = ActorMemoryContext(
            actor_id="A", persona={}, short_term=short,
            long_term=LongTermView(consolidated=[], long_term=[], pinned=[]),
            retrieved=[],
        )
        # 只读投影:持有引用而非深拷贝(引用一致)
        self.assertIs(ctx.short_term, short)
