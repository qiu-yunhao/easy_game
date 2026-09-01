import unittest
from http import HTTPStatus
from types import SimpleNamespace

import web_server


class _FakeSession:
    def __init__(self):
        self.selected = None
        self.imported = None
    def list_templates(self):
        return [{"template_id": 1, "source_title": "鹿鼎记", "beat_count": 3, "created_at": ""}]
    def get_template_detail(self, tid):
        return {"template_id": tid, "style_bible": {}, "characters": [], "beats": [], "skeleton": []}
    def import_template(self, *, source_title, text, user_id=0):
        self.imported = (source_title, user_id)
        return 7
    def set_selected_template(self, tid):
        self.selected = tid
        return {"selected_template_id": tid}
    def reset(self, **kwargs):
        return {"reset": kwargs}
    def export_runtime_snapshot(self):
        return {}
    def bind_save_context(self, **kwargs):
        return None


class _FakeSaveStore:
    def create_new_game(self, **kwargs):
        return {"player": {"id": 1}}


def _handler():
    h = web_server.StageboundRequestHandler.__new__(web_server.StageboundRequestHandler)
    h.server = SimpleNamespace(session=_FakeSession(), save_store=_FakeSaveStore())
    return h


class PostTemplateEndpointsTest(unittest.TestCase):
    def test_import_dispatch(self):
        h = _handler()
        status, payload = h._handle_post_api_request(
            "/api/templates/import",
            {"source_title": "鹿鼎记", "text": "正文", "user_id": 0},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["template_id"], 7)
        self.assertEqual(h.server.session.imported, ("鹿鼎记", 0))

    def test_select_dispatch_and_clear(self):
        h = _handler()
        status, payload = h._handle_post_api_request("/api/templates/select", {"template_id": 1})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(h.server.session.selected, 1)
        status, payload = h._handle_post_api_request("/api/templates/select", {"template_id": None})
        self.assertIsNone(h.server.session.selected)

    def test_reset_kwargs_passes_selected_template(self):
        h = _handler()
        kwargs = h._build_reset_kwargs({"selected_template_id": 5})
        self.assertEqual(kwargs["selected_template_id"], 5)

    def test_new_game_rejects_genre_shortcut_without_world_builder_draft(self):
        h = _handler()

        with self.assertRaisesRegex(RuntimeError, "必须先完成世界观完善"):
            h._handle_post_api_request("/api/new-game", {"user_id": 1, "genre_tag": "xianxia"})


if __name__ == "__main__":
    unittest.main()
