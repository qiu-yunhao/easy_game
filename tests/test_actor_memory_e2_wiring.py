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


if __name__ == "__main__":
    unittest.main()
