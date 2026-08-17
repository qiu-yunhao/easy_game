import unittest

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


if __name__ == "__main__":
    unittest.main()
