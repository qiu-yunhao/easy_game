from __future__ import annotations

import unittest

from Actor.ActorRuntime import apply_resolved_act
from CharacterProfile import ensure_character_profile
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state
from GameplayTuning import RelationshipTuning
from ResolvedActUtils import build_resolved_act_payload


def _build_state(*, guard_agent_type: str) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    profiles: dict[str, dict[str, object]] = {
        "player": ensure_character_profile(
            {
                "character_id": "player",
                "name": "Player",
                "persona": [],
                "base_style": "",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "",
                "realm": "",
                "main_technique": "",
            },
            character_id="player",
            include_backpack=True,
        ),
        "guard": ensure_character_profile(
            {
                "character_id": "guard",
                "name": "Guard",
                "agent_type": guard_agent_type,
                "persona": ["careful"],
                "base_style": "brief",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "",
                "realm": "",
                "main_technique": "",
                "l2_profile": {
                    "core_drive": "keep order",
                    "judgement_preference": ["follow authority"],
                    "behavior_rule": ["protect self"],
                    "speech_style": ["firm"],
                    "personality_tags": ["careful"],
                },
                "l1_profile": {
                    "core_conflict": "duty versus sympathy",
                    "outer_goal": "hold the line",
                    "inner_need": "learn to trust",
                    "contradiction_axes": ["duty / empathy"],
                    "relationship_pressure": ["player"],
                },
            },
            character_id="guard",
        ),
    }

    state = create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "",
            "exploration_drive": "",
            "story_outline": [],
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
            "location_id": "courtyard",
            "time_tag": "morning",
            "beat": "",
            "tension": 0.2,
            "focus_character": "player",
            "on_stage": ["player", "guard"],
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            "player": create_character_runtime_state(intent="observe"),
            "guard": create_character_runtime_state(intent="watch the player"),
        },
        player=create_player_state(controlled_character="player"),
    )
    return state, profiles


class CharacterMemoryLayerTests(unittest.TestCase):
    def test_profile_defaults_expand_l1_and_compact_l2_memory(self) -> None:
        l1_profile = ensure_character_profile(
            {
                "character_id": "senior",
                "name": "Senior",
                "agent_type": "L1",
                "persona": [],
                "base_style": "",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "",
                "realm": "",
                "main_technique": "",
            },
            character_id="senior",
        )
        l2_profile = ensure_character_profile(
            {
                "character_id": "guard",
                "name": "Guard",
                "agent_type": "L2",
                "persona": [],
                "base_style": "",
                "base_relationship": {},
                "secrets": [],
                "spiritual_root": "",
                "realm": "",
                "main_technique": "",
            },
            character_id="guard",
        )

        self.assertEqual(l1_profile["memory_profile"]["long_term_limit"], 7)
        self.assertEqual(l1_profile["memory_profile"]["short_term_limit"], 30)
        self.assertEqual(l1_profile["memory_profile"]["player_memory_limit"], 8)
        self.assertEqual(l2_profile["memory_profile"]["long_term_limit"], 3)
        self.assertEqual(l2_profile["memory_profile"]["short_term_limit"], 30)
        self.assertEqual(l2_profile["memory_profile"]["player_memory_limit"], 3)

    def test_player_action_updates_guard_memories(self) -> None:
        state, profiles = _build_state(guard_agent_type="L2")
        state["runtime"]["resolved_act"] = build_resolved_act_payload(
            actor="player",
            mode="action",
            target="guard",
            content="Player offers the guard a clear explanation.",
            next_intent="wait for a response",
            relationship_update={"guard": 2.0},
            revealed_facts=["the player carries a sect token"],
        )

        next_state = apply_resolved_act(
            state,
            RelationshipTuning(),
            character_profiles=profiles,
        )

        guard_memory = next_state["characters"]["guard"]["memory"]
        self.assertEqual(len(guard_memory["short_term_memory"]), 1)
        self.assertEqual(
            guard_memory["short_term_memory"][0]["summary"],
            "Player offers the guard a clear explanation.",
        )
        self.assertGreaterEqual(len(guard_memory["long_term_memory"]), 1)
        self.assertEqual(
            guard_memory["long_term_memory"][-1]["event_summary"],
            "Player offers the guard a clear explanation.",
        )
        self.assertEqual(len(guard_memory["player_memory"]["key_events"]), 1)
        self.assertAlmostEqual(
            guard_memory["player_memory"]["relation_state"]["player"],
            1.0,
        )

    def test_l2_prunes_long_term_and_player_memory_faster_than_l1(self) -> None:
        l2_state, l2_profiles = _build_state(guard_agent_type="L2")
        l1_state, l1_profiles = _build_state(guard_agent_type="L1")

        for index in range(5):
            act = build_resolved_act_payload(
                actor="player",
                mode="action",
                target="guard",
                content=f"Player pressures the guard about answer {index}.",
                next_intent="continue pressing",
                relationship_update={"guard": 2.0},
                revealed_facts=[f"fact-{index}"],
            )
            l2_state["runtime"]["resolved_act"] = act
            l1_state["runtime"]["resolved_act"] = act
            l2_state = apply_resolved_act(
                l2_state,
                RelationshipTuning(),
                character_profiles=l2_profiles,
            )
            l1_state = apply_resolved_act(
                l1_state,
                RelationshipTuning(),
                character_profiles=l1_profiles,
            )

        l2_memory = l2_state["characters"]["guard"]["memory"]
        l1_memory = l1_state["characters"]["guard"]["memory"]
        self.assertEqual(len(l2_memory["short_term_memory"]), 5)
        self.assertEqual(len(l2_memory["long_term_memory"]), 3)
        self.assertEqual(len(l2_memory["player_memory"]["key_events"]), 3)
        self.assertEqual(len(l1_memory["short_term_memory"]), 5)
        self.assertEqual(len(l1_memory["long_term_memory"]), 7)
        self.assertEqual(len(l1_memory["player_memory"]["key_events"]), 5)


if __name__ == "__main__":
    unittest.main()
