from __future__ import annotations

import types
import unittest

from Graph.narration_nodes import director_lead_in_node


def _fake_deps() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        gameplay_tuning=types.SimpleNamespace(
            narration=types.SimpleNamespace(style_preset="xianxia_default"),
        ),
    )


_LEAD_IN = (
    "云岚山门里的气流像是被谁一点点按住，原本浮动的声息也跟着低了下去。"
    "守门弟子没有立刻开口，只是将视线稳稳压在来者身上，肩背与指节都透出难以忽视的绷紧。"
    "那份无声积蓄的压迫感缓慢堆高，谁都能感觉到，接下来不会只是寻常一句应答。"
)


def _base_state(*, lead_in_text: str, history: list[dict]) -> dict:
    return {
        "history": history,
        "director_brief": {"lead_in_text": lead_in_text, "wrap_up_text": ""},
        "scene": {"on_stage": ["player", "guard"], "location_id": "云岚山门"},
        "player": {"controlled_character": "player"},
        "runtime": {"turn_index": 5, "next_act": {"actor": "guard"}},
    }


class DirectorTransitionDedupTests(unittest.TestCase):
    def test_repeated_lead_in_is_skipped(self) -> None:
        # 上一条同源 lead-in 已是这段兜底文本,再来一遍近乎重复 -> 跳过落库,清空字段。
        state = _base_state(
            lead_in_text=_LEAD_IN,
            history=[
                {"turn": 3, "actor": None, "content": _LEAD_IN, "narration_source": "director_lead_in"},
            ],
        )
        result = director_lead_in_node(state, _fake_deps())
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["director_brief"]["lead_in_text"], "")

    def test_distinct_lead_in_is_committed(self) -> None:
        state = _base_state(
            lead_in_text="门后传来一阵新的脚步声，气氛骤然不同。守门弟子偏过头去，神色一凛。",
            history=[
                {"turn": 3, "actor": None, "content": _LEAD_IN, "narration_source": "director_lead_in"},
            ],
        )
        result = director_lead_in_node(state, _fake_deps())
        self.assertEqual(len(result["history"]), 2)
        self.assertEqual(result["director_brief"]["lead_in_text"], "")

    def test_no_prior_same_source_commits_normally(self) -> None:
        state = _base_state(lead_in_text=_LEAD_IN, history=[])
        result = director_lead_in_node(state, _fake_deps())
        self.assertEqual(len(result["history"]), 1)


if __name__ == "__main__":
    unittest.main()
