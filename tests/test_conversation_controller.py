import unittest
from unittest.mock import patch

from Graph.conversation_controller import (
    ConversationController,
    never_stop,
    stop_at_player_turn,
)


def _fake_is_player_turn(state):
    next_act = state["runtime"].get("next_act") or {}
    return next_act.get("actor") == "player"


def _base_state(next_act):
    return {
        "player": {"controlled_character": "player"},
        "scene": {"on_stage": ["player", "npc_a"], "suppressed": [], "focus_character": ""},
        "runtime": {"next_act": next_act, "eligible_actors": ["player", "npc_a"], "scene_finished": False},
    }


class PrimeOpeningTurnTest(unittest.TestCase):
    def test_prime_sets_player_next_act(self):
        controller = ConversationController(deps=object())
        state = _base_state(None)
        primed = controller.prime_opening_turn(state)
        self.assertEqual(primed["runtime"]["next_act"]["actor"], "player")

    def test_prime_no_player_yields_none_next_act(self):
        controller = ConversationController(deps=object())
        state = _base_state(None)
        state["player"]["controlled_character"] = ""  # 自动模式:无玩家角色
        primed = controller.prime_opening_turn(state)
        self.assertIsNone(primed["runtime"]["next_act"])


class AdvanceStopAtPlayerTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_stops_when_already_player_turn(self):
        # 一开始就是玩家回合、且无 NPC 先行动 → 立即停,提示等待玩家。
        controller = ConversationController(deps=object())
        state = _base_state({"actor": "player"})
        result, reason = controller.advance(state, stop_when=stop_at_player_turn)
        self.assertEqual(result["runtime"]["next_act"]["actor"], "player")
        self.assertIn("等待玩家", reason)

    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_runs_npc_then_stops_at_player(self):
        # 先 NPC 回合 → resolve 后变玩家回合 → 停并提示已结算。
        calls = {"n": 0}

        def _fake_resolve(state, deps, on_event=None):
            calls["n"] += 1
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "player"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(state, stop_when=stop_at_player_turn)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result["runtime"]["next_act"]["actor"], "player")
        self.assertIn("已结算", reason)


class AdvanceNeverStopTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_never_stop_runs_until_scene_finished(self):
        # 自动模式:连跑 NPC 回合,即便中途是玩家回合也不停,直到 scene_finished。
        seq = iter([
            {"actor": "player"},   # 第1跳:玩家回合,但 never_stop 不停,继续 resolve
            {"actor": "npc_a"},    # 第2跳:NPC 回合
        ])

        def _fake_resolve(state, deps, on_event=None):
            try:
                nxt = next(seq)
                return {**state, "runtime": {**state["runtime"], "next_act": nxt}}
            except StopIteration:
                return {**state, "runtime": {**state["runtime"], "scene_finished": True,
                                             "scene_end_evaluation": {"reason": "剧终"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            result, reason = controller.advance(state, stop_when=never_stop, max_hops=24)
        self.assertTrue(result["runtime"]["scene_finished"])
        self.assertEqual(reason, "剧终")


class AdvanceMaxHopsTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_raises_when_exceeds_max_hops(self):
        # 永不终止的 NPC 回合 → 超 max_hops 抛错。
        def _fake_resolve(state, deps, on_event=None):
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "npc_a"}}}

        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            with self.assertRaises(RuntimeError):
                controller.advance(state, stop_when=never_stop, max_hops=3)


class AdvanceOnEventTest(unittest.TestCase):
    @patch("Graph.conversation_controller.is_player_turn", _fake_is_player_turn)
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_on_event_passed_to_resolve(self):
        # 断言 advance 把 on_event 原样透传给 resolve_story_turn。
        seen = {}

        def _fake_resolve(state, deps, on_event=None):
            seen["cb"] = on_event
            return {**state, "runtime": {**state["runtime"], "next_act": {"actor": "player"}}}

        cb = lambda entry: None
        controller = ConversationController(deps=object())
        state = _base_state({"actor": "npc_a"})
        with patch("Graph.conversation_controller.resolve_story_turn", _fake_resolve):
            controller.advance(state, stop_when=stop_at_player_turn, on_event=cb)
        self.assertIs(seen["cb"], cb)


class AdvanceNextActNoneTest(unittest.TestCase):
    @patch("Graph.conversation_controller.prepare_chapter_turn", lambda s, d: s)
    def test_advance_returns_when_next_act_none(self):
        # scene 未结束、prepare 也补不出 next_act(patch 原样返回)→ 早返回「无新动作」。
        controller = ConversationController(deps=object())
        state = _base_state(None)  # next_act=None 且 scene 未结束
        result, reason = controller.advance(state, stop_when=never_stop)
        self.assertIn("没有新的自动后续动作", reason)


if __name__ == "__main__":
    unittest.main()
