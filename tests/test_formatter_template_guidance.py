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

from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter
from session_bootstrap import build_default_character_profiles, build_default_scene_config, build_default_state

GUIDANCE = "参考骨架：\n- 初入江湖：主角离乡遭遇第一场冲突"


class FormatterTemplateGuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = PlaywrightFormatter()
        self.profiles = build_default_character_profiles(
            {"name": "沈云烟", "background": "带着未解的旧缘来到山门前。"}
        )
        self.state = build_default_state(
            player_character="player",
            character_profiles=self.profiles,
        )
        self.scene_config = build_default_scene_config("xianxia_default")

    def _chapter(self, **kwargs) -> str:
        return self.formatter.build_chapter_expansion_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
            **kwargs,
        )

    def _scene(self, **kwargs) -> str:
        return self.formatter.build_scene_candidates_instruction(
            game_state=self.state,
            scene_config=self.scene_config,
            character_profiles=self.profiles,
            **kwargs,
        )

    def test_chapter_非空guidance拼reference_skeleton(self) -> None:
        instruction = self._chapter(template_guidance=GUIDANCE)
        self.assertIn("reference_skeleton", instruction)
        self.assertIn("初入江湖", instruction)

    def test_chapter_默认空guidance不加key(self) -> None:
        instruction = self._chapter()
        self.assertNotIn("reference_skeleton", instruction)

    def test_scene_非空guidance拼reference_beats(self) -> None:
        instruction = self._scene(template_guidance=GUIDANCE)
        self.assertIn("reference_beats", instruction)
        self.assertIn("初入江湖", instruction)

    def test_scene_默认空guidance不加key(self) -> None:
        instruction = self._scene()
        self.assertNotIn("reference_beats", instruction)


if __name__ == "__main__":
    unittest.main()
