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
    def test_enable_flips_enabled_and_upgrades_agent_type(self):
        session = _session()
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )
        session.set_auto_mode(True)
        self.assertTrue(session.auto_mode)
        self.assertFalse(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "L1",
        )

    def test_disable_restores_enabled_and_agent_type(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(False)
        self.assertFalse(session.auto_mode)
        self.assertTrue(session.state["player"].get("enabled"))
        self.assertEqual(
            session.deps.character_profiles.get(PLAYER_CHARACTER_ID, {}).get("agent_type"),
            "actor",
        )

    def test_enable_twice_is_idempotent_and_keeps_original_agent_type(self):
        session = _session()
        session.set_auto_mode(True)
        session.set_auto_mode(True)  # 第二次 no-op,不能把已存的原值覆盖成 L1
        session.set_auto_mode(False)
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


if __name__ == "__main__":
    unittest.main()
