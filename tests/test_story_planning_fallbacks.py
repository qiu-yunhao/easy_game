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

from Graph.nodes import (
    _ensure_chapter_expansion,
    _ensure_story_cast,
    _ensure_story_outline_brief,
    _ensure_story_premise,
)
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
    build_graph_dependencies,
)


class _FailingPlaywright:
    def plan_story_premise(self, **kwargs):
        del kwargs
        raise RuntimeError(
            "PlaywrightAgent returned an incomplete story premise. Missing or empty fields: story_premise, exploration_drive."
        )

    def plan_story_outline_brief(self, **kwargs):
        del kwargs
        raise RuntimeError(
            "PlaywrightAgent returned an incomplete story outline brief. Missing or empty fields: story_outline[0].title."
        )

    def expand_current_chapter(self, **kwargs):
        del kwargs
        raise RuntimeError(
            "PlaywrightAgent returned an incomplete chapter expansion. Missing or empty fields: chapter_title."
        )


class _FailingActorCreateAgent:
    def sync_supporting_cast(self, **kwargs):
        del kwargs
        raise ValueError(
            'Expected valid JSON, but the model returned malformed or truncated content: {"characters": ['
        )


class StoryPlanningFallbackTests(unittest.TestCase):
    def _build_agent_first_deps(self):
        profiles = build_default_character_profiles()
        scene_config = build_default_scene_config()
        deps = build_graph_dependencies(
            "heuristic",
            character_profiles=profiles,
            scene_config=scene_config,
        )
        deps.agent_first = True
        return profiles, deps

    def test_story_premise_falls_back_when_playwright_returns_incomplete(self) -> None:
        profiles, deps = self._build_agent_first_deps()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )

        next_state = _ensure_story_premise(state, deps, _FailingPlaywright())

        self.assertTrue(next_state["plot"]["story_premise"])
        self.assertTrue(next_state["plot"]["exploration_drive"])
        self.assertEqual(next_state["plot"]["story_premise_source"], "heuristic")

    def test_story_outline_falls_back_when_playwright_returns_incomplete(self) -> None:
        profiles, deps = self._build_agent_first_deps()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        state = _ensure_story_premise(state, deps, _FailingPlaywright())

        next_state = _ensure_story_outline_brief(state, deps, _FailingPlaywright())

        self.assertTrue(next_state["plot"]["story_outline"])
        self.assertEqual(next_state["plot"]["story_outline_source"], "heuristic")

    def test_chapter_expansion_falls_back_when_playwright_returns_incomplete(self) -> None:
        profiles, deps = self._build_agent_first_deps()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        state = _ensure_story_premise(state, deps, _FailingPlaywright())
        state = _ensure_story_outline_brief(state, deps, _FailingPlaywright())

        next_state = _ensure_chapter_expansion(state, deps, _FailingPlaywright())

        self.assertTrue(next_state["plot"]["current_chapter_title"])
        self.assertTrue(next_state["plot"]["chapter_goal"])
        self.assertTrue(next_state["plot"]["current_chapter_overview"])
        self.assertEqual(next_state["plot"]["chapter_expansion_source"], "heuristic")

    def test_story_cast_soft_fails_when_actor_create_returns_malformed_json(self) -> None:
        profiles, deps = self._build_agent_first_deps()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        state = _ensure_story_premise(state, deps, _FailingPlaywright())

        next_state = _ensure_story_cast(state, deps, _FailingActorCreateAgent())

        self.assertEqual(next_state, state)
        self.assertEqual(list(deps.character_profiles.keys()), [PLAYER_CHARACTER_ID])
        self.assertTrue(deps.actor_create_signature)


if __name__ == "__main__":
    unittest.main()
