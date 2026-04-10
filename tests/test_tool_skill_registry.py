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

from CharacterRosterTools import CHARACTER_ROSTER_TOOL_SCHEMA
from PlayerControl.PlayerCommandTools import (
    load_tool_skills_for_prompt,
    render_tool_schemas_for_prompt,
)
from ToolSkillRegistry import (
    DEFAULT_STORY_TOOL_SKILL_IDS,
    build_story_tool_prompt_payload,
    find_tool_definition,
    load_tool_skill_prompt_context_for_ids,
    render_tool_schemas_for_ids,
    select_story_tool_skill_ids,
    select_tool_skills,
)


class ToolSkillRegistryTests(unittest.TestCase):
    def test_inventory_request_loads_only_inventory_skill(self) -> None:
        skills = select_tool_skills("我想看看背包里有什么", audience="player")
        self.assertEqual([skill.skill_id for skill in skills], ["inventory_skill"])

        prompt_skills = load_tool_skills_for_prompt("我想看看背包里有什么")
        self.assertEqual([skill["skill_id"] for skill in prompt_skills], ["inventory_skill"])
        self.assertTrue(prompt_skills[0]["file_path"].endswith("skills\\inventory_skill.md") or prompt_skills[0]["file_path"].endswith("skills/inventory_skill.md"))
        self.assertIn("query_inventory", prompt_skills[0]["tool_names"])

        tool_schemas = render_tool_schemas_for_prompt("我想看看背包里有什么")
        self.assertEqual([schema["name"] for schema in tool_schemas], ["query_inventory"])

    def test_save_request_loads_only_save_load_skill(self) -> None:
        tool_schemas = render_tool_schemas_for_prompt("帮我存档",)
        self.assertEqual(
            [schema["name"] for schema in tool_schemas],
            ["save_checkpoint", "load_checkpoint"],
        )

    def test_character_roster_schema_comes_from_registry(self) -> None:
        registry_tool = find_tool_definition("query_character_roster", audience="story")
        self.assertIsNotNone(registry_tool)
        self.assertEqual(CHARACTER_ROSTER_TOOL_SCHEMA, registry_tool.schema())

    def test_story_agents_can_load_roster_skill_by_explicit_id(self) -> None:
        prompt_skills = load_tool_skill_prompt_context_for_ids(
            DEFAULT_STORY_TOOL_SKILL_IDS,
            audience="story",
        )
        self.assertEqual([skill["skill_id"] for skill in prompt_skills], ["character_roster_skill"])
        self.assertIn("query_character_roster", prompt_skills[0]["tool_names"])

        tool_schemas = render_tool_schemas_for_ids(
            DEFAULT_STORY_TOOL_SKILL_IDS,
            audience="story",
        )
        self.assertEqual([schema["name"] for schema in tool_schemas], ["query_character_roster"])

    def test_story_skill_selection_skips_roster_for_player_only_premise(self) -> None:
        self.assertEqual(
            select_story_tool_skill_ids(task="story_premise", cast_size=1, supporting_cast_count=0),
            (),
        )
        payload = build_story_tool_prompt_payload(
            task="story_premise",
            cast_size=1,
            supporting_cast_count=0,
        )
        self.assertEqual(payload["loaded_tool_skills"], [])
        self.assertEqual(payload["available_tools"], [])

    def test_story_skill_selection_enables_roster_for_director_handoff(self) -> None:
        self.assertEqual(
            select_story_tool_skill_ids(
                task="director_update",
                cast_size=4,
                on_stage_count=1,
                available_stage_candidate_count=2,
            ),
            ("scene_skill", "character_roster_skill"),
        )

    def test_story_skill_selection_enables_status_for_chapter_planning(self) -> None:
        self.assertEqual(
            select_story_tool_skill_ids(
                task="story_outline",
                cast_size=3,
                supporting_cast_count=2,
                current_chapter_cast_count=2,
                outline_exists=True,
            ),
            ("character_status_skill", "character_roster_skill"),
        )
        self.assertEqual(
            select_story_tool_skill_ids(
                task="chapter_expansion",
                cast_size=2,
                current_chapter_cast_count=1,
                history_count=3,
            ),
            ("character_status_skill", "memory_skill"),
        )

    def test_story_skill_selection_enables_scene_and_memory_for_live_scene(self) -> None:
        self.assertEqual(
            select_story_tool_skill_ids(
                task="scene_candidates",
                cast_size=3,
                supporting_cast_count=2,
                current_chapter_cast_count=3,
                on_stage_count=2,
                history_count=4,
            ),
            ("scene_skill", "memory_skill", "character_roster_skill"),
        )


if __name__ == "__main__":
    unittest.main()
