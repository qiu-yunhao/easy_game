from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.hooks import HookRegistry
from Graph.hookable_node import HookableNode


class _EchoNode(HookableNode):
    name = "echo"

    def __init__(self, registry, tag):
        super().__init__(registry)
        self._tag = tag

    def run(self, state):
        return {**state, "trace": [*state.get("trace", []), f"run:{self._tag}"]}


class HookableNodeTests(unittest.TestCase):
    def test_name_composes_hook_points(self):
        registry = HookRegistry()
        node = _EchoNode(registry, "x")
        self.assertEqual(node.hook_point_before, "echo.before")
        self.assertEqual(node.hook_point_after, "echo.after")

    def test_as_step_runs_before_run_after_in_order(self):
        registry = HookRegistry()
        registry.register("echo.before", lambda s: {**s, "trace": [*s.get("trace", []), "before"]})
        registry.register("echo.after", lambda s: {**s, "trace": [*s.get("trace", []), "after"]})
        node = _EchoNode(registry, "x")
        result = node.as_step()({})
        self.assertEqual(result["trace"], ["before", "run:x", "after"])

    def test_as_step_without_hooks_still_runs(self):
        registry = HookRegistry()
        node = _EchoNode(registry, "x")
        result = node.as_step()({})
        self.assertEqual(result["trace"], ["run:x"])

    def test_run_exception_prevents_after_hook(self):
        registry = HookRegistry()
        after_called = []
        registry.register("echo.after", lambda s: (after_called.append(True), s)[1])

        class _Boom(HookableNode):
            name = "echo"

            def run(self, state):
                raise RuntimeError("boom")

        node = _Boom(registry)
        with self.assertRaises(RuntimeError):
            node.as_step()({})
        self.assertEqual(after_called, [])

    def test_multiple_before_hooks_thread_state(self):
        registry = HookRegistry()
        registry.register("echo.before", lambda s: {**s, "n": s.get("n", 0) + 1})
        registry.register("echo.before", lambda s: {**s, "n": s["n"] * 10})
        node = _EchoNode(registry, "x")
        result = node.as_step()({"n": 0})
        self.assertEqual(result["n"], 10)


_FAKE_SCENE_CONFIG = {
    "scene_id": "scene-1",
    "default_location_id": "room",
    "default_on_stage": [],
}


class BeatNodesTests(unittest.TestCase):
    def _make_deps(self, registry):
        from Graph.nodes import GraphDependencies

        return GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
            hook_registry=registry,
        )

    def test_all_beat_nodes_have_expected_names(self):
        from Graph.beat_nodes import (
            ActorNode,
            CultivationProgressNode,
            DirectorLeadInNode,
            DirectorWrapUpNode,
            NarrationNode,
            SceneEndNode,
        )

        registry = HookRegistry()
        deps = self._make_deps(registry)
        self.assertEqual(DirectorLeadInNode(deps, registry).name, "director_lead_in")
        self.assertEqual(ActorNode(deps, registry).name, "actor")
        self.assertEqual(NarrationNode(deps, registry).name, "narration")
        self.assertEqual(CultivationProgressNode(deps, registry).name, "cultivation_progress")
        self.assertEqual(SceneEndNode(deps, registry).name, "scene_end")
        self.assertEqual(DirectorWrapUpNode(deps, registry).name, "director_wrap_up")

    def test_narration_node_passes_force_flush_flag(self):
        from Graph.beat_nodes import NarrationNode

        registry = HookRegistry()
        deps = self._make_deps(registry)
        node = NarrationNode(deps, registry, force_flush=True)
        self.assertTrue(node._force_flush)

        default_node = NarrationNode(deps, registry)
        self.assertFalse(default_node._force_flush)

    def test_beat_node_run_delegates_to_legacy_function(self):
        """ActorNode.run 应等价于旧函数 actor_node(state, deps)"""
        from Graph.beat_nodes import ActorNode
        from Graph.nodes import actor_node

        registry = HookRegistry()
        deps = self._make_deps(registry)
        # runtime.next_act 为 None → 两条路径都返回 state 不变
        state = {"runtime": {"next_act": None}, "player": {}}
        legacy_result = actor_node(state, deps)
        node_result = ActorNode(deps, registry).run(state)
        self.assertEqual(legacy_result, node_result)


if __name__ == "__main__":
    unittest.main()
