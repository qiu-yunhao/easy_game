import unittest

from Actor.ActorDedup import is_duplicate_act


class IsDuplicateActTest(unittest.TestCase):
    def test_verbatim_repeat_is_duplicate(self):
        text = "他将书册轻轻放回原处，指尖在书脊上略作停留，似与那字句作别。随即转身，朝藏经阁外行去。"
        self.assertTrue(is_duplicate_act(text, [{"content": text}]))

    def test_near_repeat_with_minor_edits_is_duplicate(self):
        prior = "夜风拂过衣袂，檐角风灯在身后摇曳，光影明灭。无名修士立于山道之上，抬手拢了拢衣领，目光在药圃方向沉静的山影与远处隐没云雾的散修洞府轮廓之间游移，最终落定在药圃方向，指尖在袖中微微收紧。他低声道：药圃的灵药怕是等不了那么久。"
        near = "夜风拂过衣袂，檐角风灯在身后摇曳，光影明灭。无名修士立于藏经阁门外的山道上，抬手拢了拢衣领，目光在药圃方向沉静的山影与远处隐没云雾的散修洞府轮廓之间游移，最终落定在药圃方向，指尖在袖中微微收紧。他低声道：药圃的灵药怕是等不了那么久。"
        self.assertTrue(is_duplicate_act(near, [{"content": prior}]))

    def test_genuine_progression_is_not_duplicate(self):
        prior = "他缓缓合上书册，抱在怀中，踱至窗边，眉头微蹙。"
        advanced = "他深吸一口气，迈步朝药圃方向走去，身影渐融入夜色之中。"
        self.assertFalse(is_duplicate_act(advanced, [{"content": prior}]))

    def test_empty_content_is_not_duplicate(self):
        self.assertFalse(is_duplicate_act("", [{"content": "任意内容"}]))

    def test_empty_history_is_not_duplicate(self):
        self.assertFalse(is_duplicate_act("任意内容", []))

    def test_only_compares_within_lookback_window(self):
        old = "很久以前的一段旧动作，早已滚出视野。"
        history = [{"content": old}] + [{"content": f"无关的新动作 {i}"} for i in range(5)]
        self.assertFalse(is_duplicate_act(old, history, lookback=3))


if __name__ == "__main__":
    unittest.main()
