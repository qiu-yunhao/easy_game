import unittest
from unittest.mock import patch

from session_bootstrap import PLAYER_CHARACTER_ID
from web_session import SessionConfig, WebGameSession


def _session():
    # heuristic 模式 + player_profile → 免 LLM/DB 起一个已初始化会话。
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.reset(player_profile={"name": "测试玩家"})
    return session


class SetAutoModeTest(unittest.TestCase):
    def test_enable_flips_flags_and_leaves_profile_untouched(self):
        session = _session()
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
        session.set_auto_mode(True)
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertTrue(session.state["player"].get("auto_mode"))
        # 共享档案全程不被篡改。
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_disable_restores_flags_and_leaves_profile_untouched(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(False)
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_enable_twice_is_idempotent(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(True)  # 第二次 no-op
        self.assertTrue(session.state["player"].get("auto_mode"))
        session.set_auto_mode(False)
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_disable_twice_is_noop(self):
        session = _session()
        session.set_auto_mode(False)  # 本就没开,no-op 不报错
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))


class AutoStepTest(unittest.TestCase):
    def test_auto_step_calls_advance_with_never_stop_and_max_beats(self):
        session = _session()
        session.set_auto_mode(True)
        captured = {}

        def _fake_advance(state, *, stop_when, max_beats=None, max_hops=24, stop_on_chapter_end=False, on_event=None):
            captured["stop_when"] = stop_when
            captured["max_beats"] = max_beats
            captured["stop_on_chapter_end"] = stop_on_chapter_end
            return state, "已自动推进 2 拍。"

        with patch.object(session._controller, "advance", _fake_advance):
            result = session.auto_step(max_beats=2)

        from Graph.conversation_controller import never_stop
        self.assertIs(captured["stop_when"], never_stop)
        self.assertEqual(captured["max_beats"], 2)
        self.assertTrue(captured["stop_on_chapter_end"])
        self.assertEqual(result["handoff_reason"], "已自动推进 2 拍。")

    def test_auto_step_sets_chapter_paused_when_chapter_changes(self):
        # advance 返回后 chapter_id 变了 → serialize_state 的 chapter_paused 为真。
        session = _session()
        session.set_auto_mode(True)
        original_chapter = str(session.state["plot"].get("chapter_id", "") or "")

        def _fake_advance(state, *, stop_when, max_beats=None, max_hops=24, stop_on_chapter_end=False, on_event=None):
            bumped = {**state, "plot": {**state["plot"], "chapter_id": original_chapter + "-next"}}
            return bumped, "本章已结束，等待确认后进入下一章。"

        with patch.object(session._controller, "advance", _fake_advance):
            result = session.auto_step(max_beats=4)
        self.assertTrue(result["chapter_paused"])

    def test_auto_step_raises_when_auto_not_enabled(self):
        session = _session()
        with self.assertRaises(RuntimeError):
            session.auto_step()

    def test_auto_step_raises_when_not_initialized(self):
        # 不给 player_profile → 未初始化。手动置 auto_mode 以越过"未开自动"校验,
        # 断言"未初始化"校验先命中。
        session = WebGameSession(SessionConfig(mode="heuristic"))
        session.auto_mode = True
        with self.assertRaises(RuntimeError):
            session.auto_step()

    def test_auto_step_raises_when_scene_finished(self):
        session = _session()
        session.set_auto_mode(True)
        session.state = {
            **session.state,
            "runtime": {**session.state["runtime"], "scene_finished": True},
        }
        with self.assertRaises(RuntimeError):
            session.auto_step()


class AutoStepStreamingTest(unittest.TestCase):
    def test_streaming_passes_on_event_to_advance(self):
        session = _session()
        session.set_auto_mode(True)
        captured = {}

        def _fake_advance(state, *, stop_when, max_beats=None, max_hops=24, stop_on_chapter_end=False, on_event=None):
            captured["stop_when"] = stop_when
            captured["max_beats"] = max_beats
            captured["on_event"] = on_event
            return state, "已自动推进 3 拍。"

        sink = []
        with patch.object(session._controller, "advance", _fake_advance):
            result = session.auto_step_streaming(sink.append, max_beats=3)

        from Graph.conversation_controller import never_stop
        self.assertIs(captured["stop_when"], never_stop)
        self.assertEqual(captured["max_beats"], 3)
        # advance 拿到的是一个可调用的 emitter(而非 None),流式才成立。
        self.assertTrue(callable(captured["on_event"]))
        self.assertEqual(result["handoff_reason"], "已自动推进 3 拍。")

    def test_streaming_raises_when_auto_not_enabled(self):
        session = _session()
        with self.assertRaises(RuntimeError):
            session.auto_step_streaming(lambda _entry: None)


class AutoStepAutosaveTest(unittest.TestCase):
    def test_autosave_fires_when_save_context_bound(self):
        session = _session()
        session.set_auto_mode(True)
        session.save_store = object()  # 非 None 即视为已配置存储
        session.active_user_id = 7
        session.active_player_id = 42

        with patch.object(session._controller, "advance", lambda state, **_k: (state, "ok")), \
                patch.object(session, "_save_player_session_unlocked") as save_mock:
            session.auto_step(max_beats=2)

        save_mock.assert_called_once()
        _, kwargs = save_mock.call_args
        self.assertEqual(kwargs.get("user_id"), 7)
        self.assertEqual(kwargs.get("player_id"), 42)
        self.assertEqual(kwargs.get("save_kind"), "auto")

    def test_autosave_skipped_when_no_save_context(self):
        session = _session()
        session.set_auto_mode(True)
        # 未绑定 user/player → 不应尝试存档。
        self.assertIsNone(session.active_user_id)

        with patch.object(session._controller, "advance", lambda state, **_k: (state, "ok")), \
                patch.object(session, "_save_player_session_unlocked") as save_mock:
            session.auto_step(max_beats=2)

        save_mock.assert_not_called()

    def test_autosave_failure_does_not_break_advance(self):
        session = _session()
        session.set_auto_mode(True)
        session.save_store = object()
        session.active_user_id = 1
        session.active_player_id = 2

        def _boom(**_k):
            raise RuntimeError("db down")

        with patch.object(session._controller, "advance", lambda state, **_k: (state, "ok")), \
                patch.object(session, "_save_player_session_unlocked", _boom):
            # autosave 抛错被吞掉,auto_step 仍正常返回。
            result = session.auto_step(max_beats=2)
        self.assertIn("handoff_reason", result)


class ExportSnapshotDuringAutoTest(unittest.TestCase):
    def test_export_while_auto_normalizes_player_to_manual(self):
        # 自动模式开着时导出快照:player.enabled 归 True、auto_mode 归 False;
        # 档案 agent_type 始终原值(从未被改);会话本体仍保持自动叠加态。
        session = _session()
        session.set_auto_mode(True)
        snapshot = session._export_runtime_snapshot_unlocked()

        self.assertEqual(
            snapshot["character_profiles"][PLAYER_CHARACTER_ID].get("agent_type"),
            "actor",
        )
        self.assertTrue(snapshot["state"]["player"].get("enabled"))
        self.assertFalse(snapshot["state"]["player"].get("auto_mode"))

        # 会话本体不受导出影响,仍在自动叠加态。
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertTrue(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_export_while_not_auto_keeps_live_values(self):
        session = _session()
        snapshot = session._export_runtime_snapshot_unlocked()
        self.assertEqual(
            snapshot["character_profiles"][PLAYER_CHARACTER_ID].get("agent_type"),
            "actor",
        )
        self.assertTrue(snapshot["state"]["player"].get("enabled"))


class ResetClearsAutoFlagsTest(unittest.TestCase):
    def test_reset_clears_auto_mode_flags(self):
        session = _session()
        session.set_auto_mode(True)
        session._last_chapter_advanced = True
        session.reset(player_profile={"name": "重开玩家"})
        self.assertFalse(session.auto_mode)
        self.assertFalse(session._last_chapter_advanced)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertFalse(session.state["player"].get("auto_mode"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_load_snapshot_clears_auto_mode_flags(self):
        session = _session()
        clean_snapshot = session._export_runtime_snapshot_unlocked()
        session.set_auto_mode(True)
        session._last_chapter_advanced = True
        session._load_runtime_snapshot_unlocked(clean_snapshot)
        self.assertFalse(session.auto_mode)
        self.assertFalse(session._last_chapter_advanced)
        self.assertFalse(session.state["player"].get("auto_mode"))


if __name__ == "__main__":
    unittest.main()
