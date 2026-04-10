from __future__ import annotations

import unittest

from Director.DirectorRuntime import apply_director_brief
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state
from Scheduler.SchedulerPolicy import HeuristicSchedulerPolicy


def _build_state(
    *,
    on_stage: list[str],
    focus_character: str | None,
    allow_interrupt: bool = True,
):
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
            "location_id": "room",
            "time_tag": "now",
            "beat": "",
            "tension": 0.1,
            "focus_character": focus_character,
            "on_stage": on_stage,
            "allow_interrupt": allow_interrupt,
            "suppressed": [],
        },
        characters={
            actor_id: create_character_runtime_state(intent=f"{actor_id}-intent")
            for actor_id in {"player", *on_stage, "npc_c"}
        },
        player=create_player_state(enabled=False),
    )


def _build_character_profiles(
    actor_ids: list[str],
    *,
    agent_types: dict[str, str] | None = None,
) -> dict[str, dict[str, object]]:
    agent_types = agent_types or {}
    profiles: dict[str, dict[str, object]] = {}
    for actor_id in actor_ids:
        profile: dict[str, object] = {
            "character_id": actor_id,
            "name": actor_id,
            "persona": [],
            "base_style": "",
            "base_relationship": {},
            "secrets": [],
            "spiritual_root": "",
            "realm": "",
            "main_technique": "",
            "agent_type": agent_types.get(actor_id, "actor"),
        }
        if profile["agent_type"] == "L1":
            profile["l1_profile"] = {}
        elif profile["agent_type"] == "L2":
            profile["l2_profile"] = {}
        profiles[actor_id] = profile
    return profiles


class HeuristicSchedulerPolicyTests(unittest.TestCase):
    def test_director_priority_can_repeat_same_actor(self) -> None:
        state = _build_state(
            on_stage=["player", "npc_a", "npc_b"],
            focus_character="npc_a",
        )
        state["runtime"]["last_actor"] = "npc_a"
        state = apply_director_brief(
            state,
            {
                "beat": "follow-up",
                "beat_goal": "let npc_a continue",
                "focus_character": "npc_a",
                "tension_target": 0.4,
                "allow_interrupt": True,
                "who_should_respond": ["npc_a", "npc_b"],
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
        )

        decision = HeuristicSchedulerPolicy().decide_next_turn(state)

        self.assertEqual(decision["next_actor"], "npc_a")
        self.assertEqual(decision["mode"], "speak")

    def test_stage_actions_flow_into_scheduler_eligibility(self) -> None:
        state = _build_state(
            on_stage=["player", "npc_a", "npc_b"],
            focus_character="npc_a",
            allow_interrupt=False,
        )
        state = apply_director_brief(
            state,
            {
                "beat": "reshuffle",
                "beat_goal": "bring in npc_c and quiet npc_b",
                "focus_character": "npc_c",
                "tension_target": 0.3,
                "allow_interrupt": False,
                "who_should_respond": ["npc_c", "npc_b", "npc_a"],
                "stage_actions": {
                    "enter": ["npc_c"],
                    "leave": [],
                    "suppress": ["npc_b"],
                    "unsuppress": [],
                },
                "notes": [],
            },
        )

        decision = HeuristicSchedulerPolicy().decide_next_turn(state)

        self.assertEqual(decision["eligible_actors"], ["npc_c", "player", "npc_a"])
        self.assertEqual(decision["next_actor"], "npc_c")
        self.assertEqual(decision["mode"], "speak")

    def test_allow_interrupt_does_not_force_interrupt_mode(self) -> None:
        state = _build_state(
            on_stage=["player", "npc_a"],
            focus_character="npc_a",
            allow_interrupt=True,
        )
        state = apply_director_brief(
            state,
            {
                "beat": "opening",
                "beat_goal": "npc_a responds first",
                "focus_character": "npc_a",
                "tension_target": 0.2,
                "allow_interrupt": True,
                "who_should_respond": ["npc_a", "player"],
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
        )

        decision = HeuristicSchedulerPolicy().decide_next_turn(state)

        self.assertEqual(decision["next_actor"], "npc_a")
        self.assertEqual(decision["mode"], "speak")

    def test_fallback_prefers_l1_when_tension_is_high(self) -> None:
        state = _build_state(
            on_stage=["player", "l1_rival", "l2_guard"],
            focus_character=None,
            allow_interrupt=False,
        )
        character_profiles = _build_character_profiles(
            ["player", "l1_rival", "l2_guard"],
            agent_types={
                "l1_rival": "L1",
                "l2_guard": "L2",
            },
        )
        state = apply_director_brief(
            state,
            {
                "beat": "pressure",
                "beat_goal": "let the major conflict role seize the beat",
                "focus_character": None,
                "tension_target": 0.72,
                "allow_interrupt": False,
                "who_should_respond": [],
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
            character_profiles=character_profiles,
        )

        decision = HeuristicSchedulerPolicy().decide_next_turn(state)

        self.assertEqual(state["runtime"]["eligible_actors"], ["l1_rival", "player", "l2_guard"])
        self.assertEqual(decision["next_actor"], "l1_rival")

    def test_fallback_keeps_focused_l2_when_director_centers_support_role(self) -> None:
        state = _build_state(
            on_stage=["player", "l1_rival", "l2_guard"],
            focus_character="l2_guard",
            allow_interrupt=False,
        )
        character_profiles = _build_character_profiles(
            ["player", "l1_rival", "l2_guard"],
            agent_types={
                "l1_rival": "L1",
                "l2_guard": "L2",
            },
        )
        state = apply_director_brief(
            state,
            {
                "beat": "support focus",
                "beat_goal": "let the support role handle the local beat",
                "focus_character": "l2_guard",
                "tension_target": 0.28,
                "allow_interrupt": False,
                "who_should_respond": [],
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
            character_profiles=character_profiles,
        )

        decision = HeuristicSchedulerPolicy().decide_next_turn(state)

        self.assertEqual(state["runtime"]["eligible_actors"], ["l2_guard", "player", "l1_rival"])
        self.assertEqual(decision["next_actor"], "l2_guard")


if __name__ == "__main__":
    unittest.main()
