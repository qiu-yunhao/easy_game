import unittest

from web_session import SessionConfig, WebGameSession


class _FakeTemplateService:
    def __init__(self):
        self.imported = []
    def list_templates(self):
        return [{"template_id": 1, "source_title": "鹿鼎记", "beat_count": 3, "created_at": ""}]
    def get_template_detail(self, template_id):
        return {"template_id": template_id, "style_bible": {"tone_tags": ["古雅"]},
                "characters": [], "beats": [{"beat_id": "b1", "label": "闯宫",
                "tags": [], "summary": "s", "dramatic_function": "", "reusable_conflict": ""}],
                "skeleton": []}
    def import_novel(self, *, source_title, text, user_id=0):
        self.imported.append((source_title, user_id))
        return 42
    def suggest_plot_beats(self, template_id, *, query, top_k=5):
        return [{"beat_id": "b1", "label": "闯宫", "tags": [], "summary": "s",
                 "dramatic_function": "", "reusable_conflict": ""}]


def _session_with_fake():
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.bind_story_template_service(_FakeTemplateService())
    session.reset(player_profile={"name": "测试玩家"})
    return session


class SelectedTemplateStateTest(unittest.TestCase):
    def test_set_and_clear_selected_template(self):
        session = _session_with_fake()
        self.assertIsNone(session.selected_template_id)
        session.set_selected_template(1)
        self.assertEqual(session.selected_template_id, 1)
        session.set_selected_template(None)
        self.assertIsNone(session.selected_template_id)

    def test_list_and_detail_and_import_delegate(self):
        session = _session_with_fake()
        self.assertEqual(session.list_templates()[0]["template_id"], 1)
        self.assertEqual(session.get_template_detail(1)["template_id"], 1)
        self.assertEqual(session.import_template(source_title="t", text="x", user_id=0), 42)


class ResetAndSnapshotTemplateTest(unittest.TestCase):
    def test_reset_accepts_selected_template_id(self):
        session = _session_with_fake()
        session.reset(player_profile={"name": "玩家"}, selected_template_id=1)
        self.assertEqual(session.selected_template_id, 1)
        state = session.get_state()
        self.assertEqual(state["selected_template_id"], 1)

    def test_snapshot_roundtrips_selected_template(self):
        session = _session_with_fake()
        session.set_selected_template(1)
        snap = session.export_runtime_snapshot()
        self.assertEqual(snap["selected_template_id"], 1)
        session.set_selected_template(None)
        session.load_runtime_snapshot(snap)
        self.assertEqual(session.selected_template_id, 1)


if __name__ == "__main__":
    unittest.main()
