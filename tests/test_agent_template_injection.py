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

from PlayerWriter.PlayerWriterAgent import PlaywrightAgent
from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
)


class _FakeService:
    def __init__(self, nodes=None, beats=None, raise_on=None):
        self._nodes = nodes or []
        self._beats = beats or []
        self._raise_on = raise_on
        self.skeleton_calls = 0
        self.beat_calls = 0

    def next_skeleton_nodes(self, tid, *, chapter_hint):
        self.skeleton_calls += 1
        if self._raise_on == "chapter":
            raise RuntimeError("boom")
        return self._nodes

    def suggest_plot_beats(self, tid, *, query, top_k=5):
        self.beat_calls += 1
        if self._raise_on == "scene":
            raise RuntimeError("boom")
        return self._beats


_CHAPTER_PAYLOAD = {
    "chapter_title": "T",
    "chapter_goal": "G",
    "chapter_overview": "O",
    "exploration_hooks": ["h1"],
    "key_locations": ["l1"],
}

_SCENE_PAYLOAD = {
    "candidates": [
        {
            "candidate_id": "c1",
            "label": "L",
            "location_id": "loc",
            "beat": "b",
            "scene_goal": "g",
            "must_happen": [],
            "must_not_happen": [],
            "dramatic_curve": "rise",
            "character_objectives": {},
            "exit_condition": "done",
            "notes": "",
        }
    ]
}

_SKELETON_NODES = [{"title": "少年下山", "event_summary": "踏上寻仙之路"}]
_BEATS = [{"label": "偶遇高人", "summary": "获得传承", "dramatic_function": "转折"}]


class _AgentHarness:
    """Build a real PlaywrightAgent and capture the instruction reaching the LLM."""

    def __init__(self, payload):
        self.agent = PlaywrightAgent(formatter=PlaywrightFormatter())
        self.captured = {}

        def _fake_command(*, instruction, history, response_format):
            del history, response_format
            self.captured["instruction"] = instruction
            return payload

        self.agent.command = _fake_command


class ChapterInjectionTests(unittest.TestCase):
    def _state(self, template_id):
        profiles = build_default_character_profiles()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        state["plot"]["selected_template_id"] = template_id
        state["plot"]["chapter_goal"] = "筑基"
        return state, profiles

    def _run(self, template_id, service):
        harness = _AgentHarness(_CHAPTER_PAYLOAD)
        state, profiles = self._state(template_id)
        harness.agent.expand_current_chapter(
            state,
            build_default_scene_config(),
            profiles,
            history=None,
            template_service=service,
        )
        return harness.captured["instruction"], service

    def test_injection_active(self):
        service = _FakeService(nodes=_SKELETON_NODES)
        instruction, service = self._run(7, service)
        self.assertIn("reference_skeleton", instruction)
        self.assertIn("少年下山", instruction)
        self.assertEqual(service.skeleton_calls, 1)

    def test_tid_zero_skips(self):
        service = _FakeService(nodes=_SKELETON_NODES)
        instruction, service = self._run(0, service)
        self.assertNotIn("reference_skeleton", instruction)
        self.assertEqual(service.skeleton_calls, 0)

    def test_service_none_skips(self):
        harness = _AgentHarness(_CHAPTER_PAYLOAD)
        state, profiles = self._state(7)
        harness.agent.expand_current_chapter(
            state, build_default_scene_config(), profiles, history=None
        )
        self.assertNotIn("reference_skeleton", harness.captured["instruction"])

    def test_retrieval_raises_degrades(self):
        service = _FakeService(nodes=_SKELETON_NODES, raise_on="chapter")
        instruction, service = self._run(7, service)
        self.assertNotIn("reference_skeleton", instruction)
        self.assertEqual(service.skeleton_calls, 1)

    def test_empty_retrieval_degrades(self):
        service = _FakeService()
        instruction, service = self._run(7, service)
        self.assertEqual(service.skeleton_calls, 1)
        self.assertNotIn("reference_skeleton", instruction)

    def test_malformed_tid_degrades(self):
        service = _FakeService(nodes=_SKELETON_NODES)
        instruction, service = self._run("not-a-number", service)
        self.assertNotIn("reference_skeleton", instruction)
        self.assertEqual(service.skeleton_calls, 0)


class SceneInjectionTests(unittest.TestCase):
    def _state(self, template_id):
        profiles = build_default_character_profiles()
        state = build_default_state(
            character_profiles=profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        state["plot"]["selected_template_id"] = template_id
        state["plot"]["chapter_goal"] = "筑基"
        return state, profiles

    def _run(self, template_id, service):
        harness = _AgentHarness(_SCENE_PAYLOAD)
        state, profiles = self._state(template_id)
        harness.agent.generate_scene_candidates(
            state,
            build_default_scene_config(),
            profiles,
            history=None,
            template_service=service,
        )
        return harness.captured["instruction"], service

    def test_injection_active(self):
        service = _FakeService(beats=_BEATS)
        instruction, service = self._run(7, service)
        self.assertIn("reference_beats", instruction)
        self.assertIn("偶遇高人", instruction)
        self.assertEqual(service.beat_calls, 1)

    def test_tid_zero_skips(self):
        service = _FakeService(beats=_BEATS)
        instruction, service = self._run(0, service)
        self.assertNotIn("reference_beats", instruction)
        self.assertEqual(service.beat_calls, 0)

    def test_service_none_skips(self):
        harness = _AgentHarness(_SCENE_PAYLOAD)
        state, profiles = self._state(7)
        harness.agent.generate_scene_candidates(
            state, build_default_scene_config(), profiles, history=None
        )
        self.assertNotIn("reference_beats", harness.captured["instruction"])

    def test_retrieval_raises_degrades(self):
        service = _FakeService(beats=_BEATS, raise_on="scene")
        instruction, service = self._run(7, service)
        self.assertNotIn("reference_beats", instruction)
        self.assertEqual(service.beat_calls, 1)

    def test_empty_retrieval_degrades(self):
        service = _FakeService()
        instruction, service = self._run(7, service)
        self.assertEqual(service.beat_calls, 1)
        self.assertNotIn("reference_beats", instruction)


if __name__ == "__main__":
    unittest.main()
