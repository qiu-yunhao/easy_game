from __future__ import annotations

import unittest

from Director.DirectorBrief import empty_director_brief
from Director.DirectorRuntime import apply_director_brief, normalize_director_brief
from GameState import (
    create_character_runtime_state,
    create_initial_game_state,
    create_player_state,
)
from History.GameMemory import empty_memory_state
from ScenePlan import empty_scene_plan


def _build_group_state(on_stage):
    cast = {"player", *on_stage}
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
            "tension": 0.2,
            "focus_character": None,
            "on_stage": list(on_stage),
            "allow_interrupt": False,
            "suppressed": [],
        },
        characters={
            actor_id: create_character_runtime_state(intent=f"{actor_id}-intent")
            for actor_id in cast
        },
        scene_plan=empty_scene_plan(),
        memory=empty_memory_state(),
        player=create_player_state(enabled=False, controlled_character=None),
    )



class EmptyDirectorBriefTest(unittest.TestCase):
    def test_empty_brief_has_response_groups(self):
        brief = empty_director_brief()
        self.assertIn("response_groups", brief)
        self.assertEqual(brief["response_groups"], [])


class NormalizeResponseGroupsTest(unittest.TestCase):
    def _base_brief(self, **overrides):
        brief = {
            "beat": "b",
            "beat_goal": "g",
            "focus_character": None,
            "tension_target": 0.3,
            "allow_interrupt": False,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a"], ["b", "c"]],
            "lead_in_text": "",
            "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        brief.update(overrides)
        return brief

    def test_valid_groups_are_kept(self):
        result = normalize_director_brief(
            self._base_brief(),
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b", "c"]])

    def test_missing_groups_degrade_to_serial(self):
        brief = self._base_brief()
        del brief["response_groups"]
        result = normalize_director_brief(
            brief,
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b"], ["c"]])

    def test_inconsistent_groups_degrade_to_serial(self):
        result = normalize_director_brief(
            self._base_brief(response_groups=[["a", "b"]]),
            current_on_stage=["a", "b", "c"],
            allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"], [["a"], ["b"], ["c"]])

    def test_offstage_ids_filtered_then_consistency_checked(self):
        result = normalize_director_brief(
            self._base_brief(
                who_should_respond=["a", "b", "z"],
                response_groups=[["a"], ["b"], ["z"]],
            ),
            current_on_stage=["a", "b"],
            allowed_actor_ids=["a", "b"],
        )
        self.assertEqual(result["who_should_respond"], ["a", "b"])
        self.assertEqual(result["response_groups"], [["a"], ["b"]])


class InterruptSplitsGroupsTest(unittest.TestCase):
    def test_allow_interrupt_splits_focus_into_own_group(self):
        brief = {
            "beat": "b", "beat_goal": "g",
            "focus_character": "a",
            "tension_target": 0.3,
            "allow_interrupt": True,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a", "b"], ["c"]],
            "lead_in_text": "", "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        result = normalize_director_brief(
            brief, current_on_stage=["a", "b", "c"], allowed_actor_ids=["a", "b", "c"],
        )
        self.assertEqual(result["response_groups"][0], ["a"])
        flat = [cid for grp in result["response_groups"] for cid in grp]
        self.assertEqual(sorted(flat), ["a", "b", "c"])


class ApplyBriefGroupsTest(unittest.TestCase):
    def test_apply_populates_pending_response_groups(self):
        state = _build_group_state(["a", "b", "c"])
        brief = {
            "beat": "b", "beat_goal": "g",
            "focus_character": None, "tension_target": 0.2,
            "allow_interrupt": False,
            "who_should_respond": ["a", "b", "c"],
            "response_groups": [["a"], ["b", "c"]],
            "lead_in_text": "", "wrap_up_text": "",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        result = apply_director_brief(state, brief, character_profiles={})
        self.assertEqual(
            result["runtime"]["pending_response_groups"],
            [["a"], ["b", "c"]],
        )


if __name__ == "__main__":
    unittest.main()
