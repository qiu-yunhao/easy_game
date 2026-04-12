from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import patch

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from CharacterProfile import (
    DEFAULT_CURRENT_REALM,
    DEFAULT_MAIN_TECHNIQUE,
    DEFAULT_SPIRITUAL_ROOT,
)
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_graph_dependencies,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
)
from web_session import SessionConfig, WebGameSession


class SessionBootstrapTests(unittest.TestCase):
    def test_default_scene_config_is_generic(self) -> None:
        scene_config = build_default_scene_config()

        self.assertEqual(scene_config["scene_id"], "opening-scene")
        self.assertEqual(scene_config["default_location_id"], "云峰入门台")
        self.assertEqual(scene_config["default_on_stage"], [PLAYER_CHARACTER_ID])

    def test_default_character_profiles_include_cultivation_fields_and_backpack(self) -> None:
        profiles = build_default_character_profiles()
        player_profile = profiles[PLAYER_CHARACTER_ID]

        self.assertEqual(player_profile["spiritual_root"], DEFAULT_SPIRITUAL_ROOT)
        self.assertEqual(player_profile["realm"], DEFAULT_CURRENT_REALM)
        self.assertEqual(player_profile["main_technique"], DEFAULT_MAIN_TECHNIQUE)
        self.assertEqual(player_profile["backpack"], [])

    def test_default_state_uses_generic_opening_ids(self) -> None:
        state = build_default_state(
            character_profiles=build_default_character_profiles(),
            player_character=PLAYER_CHARACTER_ID,
        )

        self.assertEqual(state["plot"]["chapter_id"], "opening-arc-1")
        self.assertEqual(state["plot"]["scene_id"], "opening-scene")
        self.assertEqual(state["scene"]["location_id"], "云峰入门台")
        self.assertEqual(state["scene"]["beat"], "初入仙门")

    def test_web_session_state_exposes_prompt_templates(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))

        state = session.get_state()

        self.assertEqual(len(state["prompt_templates"]), 3)
        self.assertTrue(state["prompt_templates"][0]["label"])
        self.assertIn("fill", state["prompt_templates"][0])

    def test_web_session_state_exposes_player_profile_cultivation_fields_and_backpack(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))

        state = session.get_state()
        profile = state["player_profile"]

        self.assertEqual(profile["spiritual_root"], DEFAULT_SPIRITUAL_ROOT)
        self.assertEqual(profile["realm"], DEFAULT_CURRENT_REALM)
        self.assertEqual(profile["main_technique"], DEFAULT_MAIN_TECHNIQUE)
        self.assertEqual(profile["backpack"], [])

    def test_web_session_serialize_state_reflects_runtime_backpack_updates(self) -> None:
        session = WebGameSession(SessionConfig(mode="heuristic"))
        session.deps.character_profiles[PLAYER_CHARACTER_ID]["backpack"] = [
            {
                "id": "镇宗功法",
                "name": "镇宗功法",
                "quantity": 1,
            }
        ]

        state = session.get_state()

        self.assertEqual(
            state["player_profile"]["backpack"],
            [{"id": "镇宗功法", "name": "镇宗功法", "quantity": 1}],
        )

    def test_build_graph_dependencies_parallelizes_agent_creation_and_warms_clients(self) -> None:
        class _WarmableAgent:
            def __init__(self, name: str) -> None:
                self.name = name

            def _build_client(self):
                _TrackingComponentFactory.warmed_agents.append(self.name)
                return object()

        class _TrackingComponentFactory:
            build_overlaps: list[str] = []
            warmed_agents: list[str] = []
            playwright_started = threading.Event()
            director_started = threading.Event()

            def _build_named_agent(self, name: str) -> _WarmableAgent:
                return _WarmableAgent(name)

            def build_playwright_agent(self, **kwargs):
                del kwargs
                self.playwright_started.set()
                if self.director_started.wait(timeout=0.3):
                    self.build_overlaps.append("playwright_agent")
                return self._build_named_agent("playwright_agent")

            def build_actor_create_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("actor_create_agent")

            def build_director_agent(self, **kwargs):
                del kwargs
                self.director_started.set()
                if self.playwright_started.wait(timeout=0.3):
                    self.build_overlaps.append("director_agent")
                return self._build_named_agent("director_agent")

            def build_actor_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("actor_agent")

            def build_l2_actor_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("l2_actor_agent")

            def build_l1_actor_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("l1_actor_agent")

            def build_narrator_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("narrator_agent")

            def build_history_summarizer_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("history_summarizer_agent")

            def build_semantic_parser_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("semantic_parser_agent")

            def build_player_intent_planner_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("player_intent_planner_agent")

            def build_stylistic_polish_agent(self, **kwargs):
                del kwargs
                return self._build_named_agent("stylistic_polish_agent")

        with patch("session_bootstrap.ComponentFactory", _TrackingComponentFactory):
            deps = build_graph_dependencies("agent-first")

        self.assertIsNotNone(deps.playwright_agent)
        self.assertIsNotNone(deps.director_agent)
        self.assertIsNotNone(deps.player_intent_planner_agent)
        self.assertIsNotNone(deps.semantic_parser_agent)
        self.assertIsNotNone(deps.history_summarizer_agent)
        self.assertIs(deps.history_manager.summarizer_agent, deps.history_summarizer_agent)
        self.assertCountEqual(
            _TrackingComponentFactory.build_overlaps,
            ["playwright_agent", "director_agent"],
        )
        self.assertCountEqual(
            _TrackingComponentFactory.warmed_agents,
            [
                "playwright_agent",
                "actor_create_agent",
                "director_agent",
                "actor_agent",
                "l2_actor_agent",
                "l1_actor_agent",
                "narrator_agent",
                "history_summarizer_agent",
                "player_intent_planner_agent",
                "semantic_parser_agent",
                "stylistic_polish_agent",
            ],
        )


if __name__ == "__main__":
    unittest.main()
