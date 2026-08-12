from __future__ import annotations

import unittest

from Director.DirectorBrief import empty_director_brief


class EmptyDirectorBriefTest(unittest.TestCase):
    def test_empty_brief_has_response_groups(self):
        brief = empty_director_brief()
        self.assertIn("response_groups", brief)
        self.assertEqual(brief["response_groups"], [])


if __name__ == "__main__":
    unittest.main()
