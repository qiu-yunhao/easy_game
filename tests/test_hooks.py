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

from Graph.hooks import HookRegistry


class HookRegistryTests(unittest.TestCase):
    def test_empty_registry_emit_returns_state_unchanged(self):
        registry = HookRegistry()
        state = {"turn": 1}
        result = registry.emit("actor.after", state)
        self.assertIs(result, state)

    def test_register_and_emit_calls_hook(self):
        registry = HookRegistry()
        calls = []

        def hook(state):
            calls.append(state["turn"])
            return {**state, "turn": state["turn"] + 1}

        registry.register("actor.after", hook)
        result = registry.emit("actor.after", {"turn": 1})
        self.assertEqual(calls, [1])
        self.assertEqual(result, {"turn": 2})

    def test_hooks_execute_in_registration_order(self):
        registry = HookRegistry()
        order = []
        registry.register("p", lambda s: (order.append("a"), s)[1])
        registry.register("p", lambda s: (order.append("b"), s)[1])
        registry.register("p", lambda s: (order.append("c"), s)[1])
        registry.emit("p", {})
        self.assertEqual(order, ["a", "b", "c"])

    def test_state_threads_through_hooks(self):
        registry = HookRegistry()
        registry.register("p", lambda s: {**s, "v": s["v"] + 1})
        registry.register("p", lambda s: {**s, "v": s["v"] * 10})
        result = registry.emit("p", {"v": 1})
        self.assertEqual(result["v"], 20)

    def test_clear_specific_point(self):
        registry = HookRegistry()
        registry.register("a", lambda s: {**s, "hit_a": True})
        registry.register("b", lambda s: {**s, "hit_b": True})
        registry.clear("a")
        result = registry.emit("a", {})
        self.assertNotIn("hit_a", result)
        result_b = registry.emit("b", {})
        self.assertTrue(result_b["hit_b"])

    def test_clear_all(self):
        registry = HookRegistry()
        registry.register("a", lambda s: {**s, "hit": True})
        registry.register("b", lambda s: {**s, "hit": True})
        registry.clear()
        self.assertEqual(registry.registered_points(), [])

    def test_registered_points_sorted(self):
        registry = HookRegistry()
        registry.register("z", lambda s: s)
        registry.register("a", lambda s: s)
        registry.register("m", lambda s: s)
        self.assertEqual(registry.registered_points(), ["a", "m", "z"])


_FAKE_SCENE_CONFIG = {
    "scene_id": "scene-1",
    "default_location_id": "room",
    "default_on_stage": [],
}


class GraphDependenciesHookRegistryTests(unittest.TestCase):
    def test_graph_dependencies_default_hook_registry_is_empty(self):
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        self.assertIsInstance(deps.hook_registry, HookRegistry)
        self.assertEqual(deps.hook_registry.registered_points(), [])

    def test_graph_dependencies_accepts_custom_hook_registry(self):
        from Graph.nodes import GraphDependencies

        registry = HookRegistry()
        registry.register("actor.after", lambda s: s)
        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
            hook_registry=registry,
        )
        self.assertIs(deps.hook_registry, registry)


if __name__ == "__main__":
    unittest.main()
