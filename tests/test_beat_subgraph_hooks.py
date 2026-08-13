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

from Graph.beat_subgraph import build_beat_execution_subgraph
from Graph.hookable_node import HookableNode
from Graph.hooks import HookRegistry


class _RecordingNode(HookableNode):
    """测试用节点:每次 run 时把 name 写入 state['trace']"""

    def __init__(self, registry, name):
        super().__init__(registry)
        self._custom_name = name

    @property
    def name(self):
        return self._custom_name

    def run(self, state):
        return {**state, "trace": [*state.get("trace", []), self._custom_name]}


class BuildBeatSubgraphSignatureTests(unittest.TestCase):
    def test_accepts_hookable_nodes_and_runs_in_order(self):
        registry = HookRegistry()
        subgraph = build_beat_execution_subgraph(
            director_lead_in=_RecordingNode(registry, "director_lead_in"),
            actor=_RecordingNode(registry, "actor"),
            narration=_RecordingNode(registry, "narration"),
            cultivation_progress=_RecordingNode(registry, "cultivation_progress"),
            scene_end=_RecordingNode(registry, "scene_end"),
        )
        result = subgraph({"trace": []})
        self.assertEqual(
            result["trace"],
            [
                "director_lead_in",
                "actor",
                "narration",
                "cultivation_progress",
                "scene_end",
            ],
        )

    def test_before_and_after_hooks_wrap_each_node(self):
        registry = HookRegistry()
        for name in ("director_lead_in", "actor", "narration", "cultivation_progress", "scene_end"):
            registry.register(
                f"{name}.before",
                lambda s, n=name: {**s, "trace": [*s.get("trace", []), f"{n}.before"]},
            )
            registry.register(
                f"{name}.after",
                lambda s, n=name: {**s, "trace": [*s.get("trace", []), f"{n}.after"]},
            )
        subgraph = build_beat_execution_subgraph(
            director_lead_in=_RecordingNode(registry, "director_lead_in"),
            actor=_RecordingNode(registry, "actor"),
            narration=_RecordingNode(registry, "narration"),
            cultivation_progress=_RecordingNode(registry, "cultivation_progress"),
            scene_end=_RecordingNode(registry, "scene_end"),
        )
        result = subgraph({"trace": []})
        expected = []
        for name in ("director_lead_in", "actor", "narration", "cultivation_progress", "scene_end"):
            expected.extend([f"{name}.before", name, f"{name}.after"])
        self.assertEqual(result["trace"], expected)


_FAKE_SCENE_CONFIG = {
    "scene_id": "scene-1",
    "default_location_id": "room",
    "default_on_stage": [],
}


class DefaultHookRegistrationTests(unittest.TestCase):
    def test_register_default_hooks_populates_expected_points(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies
        from History.HistoryManager import HistoryManager

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
            history_manager=HistoryManager(compression_trigger_size=1),
        )
        register_default_hooks(deps)
        self.assertIn("actor.after", deps.hook_registry.registered_points())
        self.assertIn("narration.after", deps.hook_registry.registered_points())

    def test_actor_after_has_two_hooks_history_commit_then_progression(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        register_default_hooks(deps)
        actor_after_hooks = deps.hook_registry._hooks.get("actor.after", [])
        self.assertEqual(len(actor_after_hooks), 2)

    def test_narration_after_has_refresh_history_hook(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        register_default_hooks(deps)
        narration_after = deps.hook_registry._hooks.get("narration.after", [])
        self.assertEqual(len(narration_after), 1)


class HookDowngradeRegressionTests(unittest.TestCase):
    """Verify downgraded hooks only touch actor.after / narration.after."""

    def test_default_hooks_only_touch_expected_points(self):
        from session_bootstrap import register_default_hooks
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        register_default_hooks(deps)
        self.assertEqual(
            sorted(deps.hook_registry.registered_points()),
            ["actor.after", "narration.after"],
        )

    def test_fresh_deps_have_empty_registry_before_registration(self):
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        self.assertEqual(deps.hook_registry.registered_points(), [])


class BeatSubgraphE2ETests(unittest.TestCase):
    """E2E: nodes built from deps.hook_registry emit at each hook point."""

    def test_subgraph_emits_all_ten_hook_points_via_deps_registry(self):
        from Graph.nodes import GraphDependencies

        deps = GraphDependencies(
            scene_config=_FAKE_SCENE_CONFIG,
            character_profiles={},
        )
        # Fresh registry — no default hooks — so we can observe emission cleanly.
        trace: list[str] = []
        for name in (
            "director_lead_in",
            "actor",
            "narration",
            "cultivation_progress",
            "scene_end",
        ):
            for phase in ("before", "after"):
                point = f"{name}.{phase}"
                deps.hook_registry.register(
                    point,
                    lambda s, p=point: (trace.append(p), s)[1],
                )

        subgraph = build_beat_execution_subgraph(
            director_lead_in=_RecordingNode(deps.hook_registry, "director_lead_in"),
            actor=_RecordingNode(deps.hook_registry, "actor"),
            narration=_RecordingNode(deps.hook_registry, "narration"),
            cultivation_progress=_RecordingNode(deps.hook_registry, "cultivation_progress"),
            scene_end=_RecordingNode(deps.hook_registry, "scene_end"),
        )
        subgraph({"trace": []})

        self.assertEqual(
            trace,
            [
                "director_lead_in.before", "director_lead_in.after",
                "actor.before", "actor.after",
                "narration.before", "narration.after",
                "cultivation_progress.before", "cultivation_progress.after",
                "scene_end.before", "scene_end.after",
            ],
        )


if __name__ == "__main__":
    unittest.main()
