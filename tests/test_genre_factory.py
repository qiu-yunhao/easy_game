from __future__ import annotations

import unittest

from WorldSetting import get_template, list_genres, validate_world_setting
from WorldSetting.validation import WorldSettingError


class GenreFactoryTests(unittest.TestCase):
    def test_all_builtin_genres_are_valid_and_independent(self) -> None:
        tags = [item["genre_tag"] for item in list_genres()]
        self.assertEqual(tags, ["xianxia", "wuxia", "infinite_flow"])
        for tag in tags:
            validate_world_setting(get_template(tag))
        first = get_template("wuxia")
        first["title"] = "changed"
        self.assertNotEqual(get_template("wuxia")["title"], "changed")

    def test_unknown_genre_fails(self) -> None:
        with self.assertRaises(WorldSettingError):
            get_template("space_opera")


if __name__ == "__main__":
    unittest.main()
