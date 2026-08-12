from __future__ import annotations

import unittest

from Director.DirectorBrief import empty_director_brief
from Director.DirectorRuntime import normalize_director_brief


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


if __name__ == "__main__":
    unittest.main()
