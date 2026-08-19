import unittest
from unittest.mock import patch

import web_demo


class TemplateWiringTest(unittest.TestCase):
    def test_maybe_setup_template_binds_when_urls_present(self):
        calls = {}
        class _Sess:
            def bind_story_template_service(self, svc):
                calls["bound"] = svc
        with patch.object(web_demo, "build_story_template_service", return_value="SVC") as b:
            web_demo._maybe_setup_story_template(
                _Sess(), mysql_url="mysql://x", pg_url="pg://y",
            )
        self.assertEqual(calls.get("bound"), "SVC")
        b.assert_called_once()

    def test_maybe_setup_template_noop_without_urls(self):
        class _Sess:
            def bind_story_template_service(self, svc):
                raise AssertionError("should not bind")
        web_demo._maybe_setup_story_template(_Sess(), mysql_url="", pg_url="")

    def test_maybe_setup_template_propagates_build_error(self):
        class _Sess:
            def __init__(self): self.bound = False
            def bind_story_template_service(self, svc): self.bound = True
        sess = _Sess()
        with patch.object(web_demo, "build_story_template_service", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                web_demo._maybe_setup_story_template(sess, mysql_url="mysql://x", pg_url="pg://y")
        self.assertFalse(sess.bound)


if __name__ == "__main__":
    unittest.main()
