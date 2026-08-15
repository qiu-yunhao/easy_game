import unittest

from CharacterProfile import ensure_character_profile
from GameState import create_initial_game_state
from Memory.default_provider import DefaultActorMemoryProvider
from Memory.provider import ActorMemoryProvider
from session_bootstrap import build_runtime_dependencies


def _state_with_history(history):
    # 项目里没有零参 empty_game_state,改用 create_initial_game_state 构造合法 state;
    # plot 传空 dict 走各字段默认,scene/characters/history 随后覆写为本用例所需。
    state = create_initial_game_state(
        plot={},  # type: ignore[typeddict-item]
        scene={"location_id": "room", "on_stage": []},
        characters={},
    )
    state["history"] = history
    state["scene"] = {"location_id": "room", "on_stage": []}
    state["characters"] = {}
    return state


class ProviderPersonaFallbackTest(unittest.TestCase):
    def test_persona_falls_back_to_legal_shell(self):
        provider = DefaultActorMemoryProvider(character_profiles={})
        ctx = provider.build("ghost", _state_with_history([]))
        expected = ensure_character_profile(None)
        # 未命中角色时 persona 是合法空壳(含全部必填键),而非空 dict。
        self.assertEqual(set(ctx.persona.keys()), set(expected.keys()))
        self.assertEqual(ctx.persona.get("agent_type"), expected.get("agent_type"))


class BootstrapProviderTest(unittest.TestCase):
    def test_runtime_deps_has_provider(self):
        # 生产入口默认应构建并注入 provider，保证生产链路恒有 provider（强制注入，不做静默降级）。
        deps = build_runtime_dependencies(
            mode="heuristic",
            interactive=False,
            character_profiles={},
            scene_config=None,
            default_scene_config_builder=lambda: {
                "scene_id": "s1",
                "default_location_id": "room",
                "default_on_stage": [],
            },
        )
        self.assertIsInstance(deps.actor_memory_provider, ActorMemoryProvider)


class PresenceFilterIntegrationTest(unittest.TestCase):
    def test_recent_history_excludes_offstage_turns(self):
        # 角色 npc_a 在 turn 0 在场、turn 1 下场、turn 2 再上场。
        history = [
            {"turn": 0, "actor": "player", "mode": "say", "content": "hi",
             "on_stage": ["player", "npc_a"], "location_id": "room"},
            {"turn": 1, "actor": "npc_b", "mode": "say", "content": "secret while a is gone",
             "on_stage": ["player", "npc_b"], "location_id": "room"},
            {"turn": 2, "actor": "player", "mode": "say", "content": "welcome back",
             "on_stage": ["player", "npc_a"], "location_id": "room"},
        ]
        state = _state_with_history(history)
        state["scene"] = {"location_id": "room", "on_stage": ["player", "npc_a"]}
        provider = DefaultActorMemoryProvider(character_profiles={}, recent_rounds=5, granularity="on_stage")
        ctx = provider.build("npc_a", state)
        contents = [item.get("content") for item in ctx.short_term]
        # npc_a 下场期间(turn 1)的对话不可见。
        self.assertNotIn("secret while a is gone", contents)
        self.assertIn("hi", contents)
        self.assertIn("welcome back", contents)


if __name__ == "__main__":
    unittest.main()
