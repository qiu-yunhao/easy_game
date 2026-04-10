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

from demo_run import build_dependencies, build_demo_scene_config
from Narrator.NarrationPresets import DEFAULT_NARRATION_STYLE_PRESET
from web_session import SessionConfig, WebGameSession


class NarrationStyleConfigTests(unittest.TestCase):
    def test_build_demo_scene_config_carries_requested_preset(self) -> None:
        scene_config = build_demo_scene_config("epic")

        self.assertEqual(scene_config["narration_style_preset"], "epic")

    def test_build_dependencies_normalizes_unknown_preset(self) -> None:
        deps = build_dependencies(
            "heuristic",
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["player"],
                "entry_conditions": [],
                "exit_conditions": [],
                "narration_style_preset": "unknown-style",
            },
        )

        self.assertEqual(
            deps.gameplay_tuning.narration.style_preset,
            DEFAULT_NARRATION_STYLE_PRESET,
        )
        self.assertEqual(
            deps.scene_config["narration_style_preset"],
            DEFAULT_NARRATION_STYLE_PRESET,
        )

    def test_web_game_session_serializes_selected_preset(self) -> None:
        session = WebGameSession(
            SessionConfig(
                mode="heuristic",
                narration_style_preset="light_novel",
            )
        )

        state = session.get_state()

        self.assertEqual(state["narration_style_preset"], "light_novel")
        self.assertTrue(
            any(
                option["value"] == "light_novel"
                for option in state["available_narration_styles"]
            )
        )

    def test_web_game_session_reset_updates_preset(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))

        state = session.reset(
            narration_style_preset="epic",
            player_profile={},
        )

        self.assertEqual(state["narration_style_preset"], "epic")
        self.assertEqual(session.config.narration_style_preset, "epic")
        self.assertEqual(session.scene_config["narration_style_preset"], "epic")
        self.assertEqual(session.deps.gameplay_tuning.narration.style_preset, "epic")


if __name__ == "__main__":
    unittest.main()
