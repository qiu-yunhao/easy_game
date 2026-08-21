from __future__ import annotations

import json
import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Actor.ActorCreateAgent import ActorCreateAgent
from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state


def _build_game_state():
    return create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "",
            "exploration_drive": "",
            "story_outline": [
                {
                    "chapter_id": "chapter-1",
                    "title": "opening",
                    "main_goal": "enter the sect",
                    "summary": "step into the cultivation world",
                    "exploration_hooks": [],
                    "key_locations": [],
                    "realm_stage": "",
                    "next_realm": "",
                },
                {
                    "chapter_id": "chapter-2",
                    "title": "old-case",
                    "main_goal": "follow the old bloodline clue",
                    "summary": "track the people tied to the old case",
                    "exploration_hooks": [],
                    "key_locations": [],
                    "realm_stage": "",
                    "next_realm": "",
                },
            ],
            "current_chapter_title": "",
            "current_chapter_overview": "",
            "active_outline_chapter_id": "",
            "story_premise_source": "",
            "story_outline_source": "",
            "chapter_expansion_source": "",
            "story_foundation_source": "",
            "chapter_focus_source": "",
            "scene_candidates_source": "",
            "current_chapter_index": 0,
            "cultivation_goal": "",
            "current_player_realm": "",
            "current_chapter_realm": "",
            "next_chapter_realm": "",
            "chapter_transition_requirement": "",
            "completed_chapters": [],
        },
        scene={
            "location_id": "mountain_gate",
            "time_tag": "dawn",
            "beat": "",
            "tension": 0.2,
            "focus_character": None,
            "on_stage": ["player"],
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            "player": create_character_runtime_state(intent="seek the truth behind the old case"),
        },
        player=create_player_state(controlled_character="player"),
    )


def _build_player_profiles(background: str) -> dict[str, dict[str, object]]:
    return {
        "player": ensure_character_profile(
            {
                "character_id": "player",
                "name": "沈云烟",
                "background": background,
                "persona": ["谨慎", "执拗"],
                "base_style": "沉静克制",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "杂灵根",
                "realm": "练气一层",
                "main_technique": "基础吐纳术",
            },
            character_id="player",
        )
    }


def _extract_payload(instruction: str) -> dict[str, object]:
    _, payload = instruction.split("\n\n", 1)
    return json.loads(payload)


class AgentProfileLayerTests(unittest.TestCase):
    def test_actor_create_instruction_loads_story_tool_skill_context(self) -> None:
        agent = ActorCreateAgent(client=object())
        instruction = agent.build_instruction(
            game_state=_build_game_state(),
            scene_config={"default_on_stage": ["player"]},
            character_profiles=_build_player_profiles("玩家在背景里提过一位旧识同门。"),
            character_roster_snapshot={
                "summary": {
                    "total_L1": 1,
                    "max_L1": 6,
                    "total_ActorAgent": 3,
                },
                "characters": [],
                "decision_hints": {},
            },
        )
        payload = _extract_payload(instruction)

        self.assertEqual([skill["skill_id"] for skill in payload["loaded_tool_skills"]], ["character_roster_skill"])
        self.assertEqual([tool["name"] for tool in payload["available_tools"]], ["query_character_roster"])
        self.assertIn("character_roster_snapshot", payload)

    def test_actor_create_profiles_default_to_l1_and_backfill_compact_fields(self) -> None:
        profile = ensure_character_profile(
            {
                "character_id": "gate_captain",
                "name": "城门卫队长",
                "story_role": "负责维持秩序的城门守卫",
                "persona": ["谨慎", "现实"],
                "base_style": "说话沉稳直接",
                "profile_source": "actor_create_agent",
                "spiritual_root": "杂灵根",
                "realm": "练气七层",
                "main_technique": "护城桩功",
            },
            character_id="gate_captain",
        )

        self.assertEqual(profile["agent_type"], "L1")
        self.assertIn("l1_profile", profile)
        self.assertTrue(profile["l1_profile"])
        self.assertEqual(profile["layer_assignment"]["plot_significance"], "core")

    def test_l1_interface_is_preserved_with_fallback_conflict_fields(self) -> None:
        profile = ensure_character_profile(
            {
                "character_id": "rival_heir",
                "name": "顾长渊",
                "agent_type": "L1",
                "story_role": "与玩家血脉旧案相关的宿敌继承人",
                "persona": ["冷峻", "傲慢"],
                "base_style": "寡言锋利",
                "spiritual_root": "金灵根",
                "realm": "筑基初期",
                "main_technique": "裂金断岳诀",
            },
            character_id="rival_heir",
        )

        self.assertEqual(profile["agent_type"], "L1")
        self.assertIn("l1_profile", profile)
        self.assertTrue(profile["l1_profile"]["core_conflict"])
        self.assertTrue(profile["l1_profile"]["outer_goal"])
        self.assertEqual(profile["layer_assignment"]["plot_significance"], "core")

    def test_actor_create_keeps_backstory_mentioned_functional_roles_at_least_l1(self) -> None:
        agent = ActorCreateAgent(client=object())
        normalized = agent.normalize_supporting_cast(
            {
                "characters": [
                    {
                        "character_id": "old_contact",
                        "name": "周掌柜",
                        "story_role": "玩家背景里提过的旧商队联络人",
                        "persona": ["温和", "机警"],
                        "base_style": "轻声却警惕",
                        "background": "他熟悉旧商路与外山消息，偶尔替玩家留意线索。",
                        "secrets": [],
                        "agent_type": "L1",
                        "layer_assignment": {
                            "mentioned_in_player_backstory": True,
                            "plot_significance": "supporting",
                            "relationship_depth": "functional",
                            "long_term_plot_significance": False,
                            "can_promote_to_l1": True,
                            "assignment_reason": "player_backstory_interactive_floor",
                        },
                        "spiritual_root": "杂灵根",
                        "realm": "练气三层",
                        "main_technique": "敛息术",
                        "base_relationship": {},
                        "planned_chapter_count": 1,
                        "planned_chapter_ids": ["chapter-1"],
                        "introduction_hint": "他可能知道外山的新消息。",
                    }
                ]
            },
            game_state=_build_game_state(),
            character_profiles=_build_player_profiles(
                "沈云烟曾受旧商队联络人周掌柜照应，如今踏入青云剑宗，希望查清血脉旧案。"
            ),
        )

        profile = normalized["old_contact"]
        self.assertEqual(profile["agent_type"], "L1")
        self.assertTrue(profile["layer_assignment"]["mentioned_in_player_backstory"])
        self.assertEqual(profile["layer_assignment"]["plot_significance"], "core")
        self.assertIn("l1_profile", profile)

    def test_actor_create_promotes_backstory_long_arc_roles_to_l1(self) -> None:
        agent = ActorCreateAgent(client=object())
        normalized = agent.normalize_supporting_cast(
            {
                "characters": [
                    {
                        "character_id": "bloodline_rival",
                        "name": "顾长渊",
                        "story_role": "玩家家族旧案中的宿敌继承人",
                        "persona": ["冷峻", "傲慢"],
                        "base_style": "锋利寡言",
                        "background": "他与玩家血脉旧案直接相关，未来会持续阻拦主线。",
                        "secrets": [],
                        "agent_type": "L1",
                        "layer_assignment": {
                            "mentioned_in_player_backstory": True,
                            "plot_significance": "core",
                            "relationship_depth": "deep",
                            "long_term_plot_significance": True,
                            "can_promote_to_l1": False,
                            "assignment_reason": "player_backstory_long_term",
                        },
                        "l1_profile": {
                            "core_conflict": "必须继承家族意志，却无法彻底无视真相",
                            "outer_goal": "压住旧案真相与玩家追查",
                            "inner_need": "承认自己并不想成为家族的工具",
                            "contradiction_axes": ["傲慢 / 动摇"],
                            "relationship_pressure": ["与玩家的宿怨持续逼近摊牌"],
                        },
                        "spiritual_root": "金灵根",
                        "realm": "筑基初期",
                        "main_technique": "裂金断岳诀",
                        "base_relationship": {},
                        "planned_chapter_count": 3,
                        "planned_chapter_ids": ["chapter-1", "chapter-2"],
                        "introduction_hint": "他会在后续章节再次现身。",
                    }
                ]
            },
            game_state=_build_game_state(),
            character_profiles=_build_player_profiles(
                "沈云烟踏上修行路，只为追查当年血脉旧案，以及那个名为顾长渊的宿敌继承人。"
            ),
        )

        profile = normalized["bloodline_rival"]
        self.assertEqual(profile["agent_type"], "L1")
        self.assertTrue(profile["layer_assignment"]["long_term_plot_significance"])
        self.assertEqual(profile["layer_assignment"]["plot_significance"], "core")
        self.assertIn("l1_profile", profile)

    def test_replaceable_functional_role_can_fall_back_to_base_actor_layer(self) -> None:
        agent = ActorCreateAgent(client=object())
        normalized = agent.normalize_supporting_cast(
            {
                "characters": [
                    {
                        "character_id": "market_blacksmith",
                        "name": "Old Zhang",
                        "occupation": "blacksmith",
                        "story_role": "repairs tools in the lower market",
                        "persona": ["practical"],
                        "base_style": "brief and direct",
                        "background": "A functional market blacksmith who appears when equipment needs repair.",
                        "secrets": [],
                        "agent_type": "actor",
                        "layer_assignment": {
                            "mentioned_in_player_backstory": False,
                            "plot_significance": "replaceable",
                            "relationship_depth": "unknown",
                            "long_term_plot_significance": False,
                            "can_promote_to_l1": False,
                            "assignment_reason": "functional_scene_role",
                        },
                        "spiritual_root": "mixed root",
                        "realm": "qi refining first layer",
                        "main_technique": "forgefire craft",
                        "base_relationship": {},
                        "planned_chapter_count": 1,
                        "planned_chapter_ids": ["chapter-1"],
                        "introduction_hint": "Can repair weapons and sell iron fittings.",
                    }
                ]
            },
            game_state=_build_game_state(),
            character_profiles=_build_player_profiles("A player with no prior tie to the blacksmith."),
        )

        profile = normalized["market_blacksmith"]
        self.assertEqual(profile["agent_type"], "actor")
        self.assertEqual(profile["story_layer"], "actor")
        self.assertEqual(profile["storage_mode"], "shared_template")
        self.assertEqual(profile["occupation"], "blacksmith")

    def test_story_manager_limits_non_backstory_l1_counts(self) -> None:
        agent = ActorCreateAgent(client=object())
        character_profiles = _build_player_profiles("A quiet cultivator entering the sect.")
        for index in range(21):
            character_profiles[f"l1_{index}"] = ensure_character_profile(
                {
                    "character_id": f"l1_{index}",
                    "name": f"L1 {index}",
                    "agent_type": "L1",
                    "story_role": "existing core role",
                    "persona": [],
                    "base_style": "",
                    "base_relationship": {},
                    "secrets": [],
                    "spiritual_root": "",
                    "realm": "",
                    "main_technique": "",
                },
                character_id=f"l1_{index}",
            )

        normalized = agent.normalize_supporting_cast(
            {
                "characters": [
                    {
                        "character_id": "overflow_core",
                        "name": "Overflow Core",
                        "story_role": "would have become a new central rival",
                        "persona": ["cold"],
                        "base_style": "sharp",
                        "background": "A late-added rival with no backstory tie.",
                        "secrets": [],
                        "agent_type": "L1",
                        "layer_assignment": {
                            "mentioned_in_player_backstory": False,
                            "plot_significance": "core",
                            "relationship_depth": "deep",
                            "long_term_plot_significance": True,
                            "can_promote_to_l1": False,
                            "assignment_reason": "late_core_addition",
                        },
                        "spiritual_root": "metal root",
                        "realm": "foundation",
                        "main_technique": "sunder blade",
                        "base_relationship": {},
                        "planned_chapter_count": 2,
                        "planned_chapter_ids": ["chapter-1", "chapter-2"],
                        "introduction_hint": "Appears later.",
                    }
                ]
            },
            game_state=_build_game_state(),
            character_profiles=character_profiles,
        )

        profile = normalized["overflow_core"]
        self.assertEqual(profile["agent_type"], "actor")
        self.assertEqual(profile["story_layer"], "actor")


if __name__ == "__main__":
    unittest.main()
