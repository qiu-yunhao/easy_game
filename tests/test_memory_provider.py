from __future__ import annotations

import dataclasses
import unittest

from Memory.context import ActorMemoryContext


class ActorMemoryContextTests(unittest.TestCase):
    def _ctx(self):
        return ActorMemoryContext(
            actor_id="A",
            persona={"character_id": "A", "name": "甲"},
            short_term=[{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}],
            retrieved=[],
        )

    def test_context_is_frozen(self):
        ctx = self._ctx()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.actor_id = "B"  # type: ignore[misc]

    def test_context_holds_references_not_deep_copies(self):
        short = [{"turn": 1, "actor": "A", "mode": "speak", "content": "x"}]
        ctx = ActorMemoryContext(
            actor_id="A", persona={}, short_term=short,
            retrieved=[],
        )
        # 只读投影:持有引用而非深拷贝(引用一致)
        self.assertIs(ctx.short_term, short)


from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state
from Memory.default_provider import DefaultActorMemoryProvider


def _build_state_with_history():
    profiles = {
        "A": ensure_character_profile({
            "character_id": "A", "name": "甲", "persona": [],
            "base_style": "", "base_relationship": {}, "secrets": [],
            "spiritual_root": "", "realm": "炼气一层", "main_technique": "",
            "agent_type": "actor", "story_layer": "core", "storage_mode": "inline",
        }),
    }
    # 工厂只读 history/scene/characters 三个键,直接构造最小 dict 即可,
    # 无需完整 GameState(create_initial_game_state 需大段 plot/scene 字面量)。
    state = {
        "scene": {"location_id": "hall", "on_stage": ["A"]},
        "characters": {"A": create_character_runtime_state()},
        "history": [
            {"turn": 1, "actor": "A", "mode": "speak", "content": "在场",
             "on_stage": ["A"], "location_id": "hall"},
            {"turn": 2, "actor": "B", "mode": "speak", "content": "不在场",
             "on_stage": ["B"], "location_id": "hall"},
        ],
    }
    return state, profiles


class DefaultActorMemoryProviderTests(unittest.TestCase):
    def test_build_short_term_applies_presence_filter(self):
        state, profiles = _build_state_with_history()
        provider = DefaultActorMemoryProvider(
            character_profiles=profiles, recent_rounds=3,
        )
        ctx = provider.build("A", state)
        # 只保留 A 在场的回合(turn 1),排除 turn 2
        self.assertEqual([it["turn"] for it in ctx.short_term], [1])
        self.assertEqual(ctx.actor_id, "A")
        self.assertEqual(ctx.persona["name"], "甲")

    def test_build_retrieved_is_empty_placeholder(self):
        state, profiles = _build_state_with_history()
        provider = DefaultActorMemoryProvider(character_profiles=profiles)
        ctx = provider.build("A", state)
        self.assertEqual(ctx.retrieved, [])

    def test_build_does_not_mutate_state(self):
        state, profiles = _build_state_with_history()
        history_before = list(state["history"])
        provider = DefaultActorMemoryProvider(character_profiles=profiles)
        provider.build("A", state)
        self.assertEqual(state["history"], history_before)
