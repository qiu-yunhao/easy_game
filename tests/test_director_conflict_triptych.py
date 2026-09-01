from __future__ import annotations

import unittest

from Director.DirectorRuntime import apply_director_brief
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state
from History.GameMemory import empty_memory_state
from ScenePlan import empty_scene_plan


def _sentence_count(value: str) -> int:
    return len([chunk for chunk in value.replace("！", "。").replace("？", "。").split("。") if chunk.strip()])


def _build_state(*, beat: str = "", scene_goal: str = ""):
    return create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "先在山门前站稳脚跟。",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "少年踏入修行门槛，处处皆是试探。",
            "exploration_drive": "他必须辨清眼前人心与自己的去路。",
            "story_outline": [],
            "current_chapter_title": "山门前夜",
            "current_chapter_overview": "风声未定，试探与敌意在门前缓缓聚拢。",
            "active_outline_chapter_id": "",
            "story_premise_source": "",
            "story_outline_source": "",
            "chapter_expansion_source": "",
            "story_foundation_source": "",
            "chapter_focus_source": "",
            "scene_candidates_source": "",
            "current_chapter_index": 0,
            "cultivation_goal": "",
            "current_player_realm": "",
            "current_chapter_realm": "",
            "next_chapter_realm": "",
            "chapter_transition_requirement": "",
            "completed_chapters": [],
        },
        scene={
            "location_id": "云岚山门",
            "time_tag": "夜",
            "beat": beat,
            "tension": 0.34,
            "focus_character": "guard",
            "on_stage": ["player", "guard"],
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            "player": create_character_runtime_state(intent="先稳住局势。"),
            "guard": create_character_runtime_state(intent="试探来者底细。"),
        },
        scene_plan={
            **empty_scene_plan(),
            "scene_goal": scene_goal,
        },
        memory=empty_memory_state(),
        player=create_player_state(controlled_character="player"),
    )


def _build_profiles() -> dict[str, dict[str, object]]:
    return {
        "player": {
            "character_id": "player",
            "name": "沈云烟",
            "persona": ["谨慎"],
            "base_style": "先看清局势再决定。",
            "base_relationship": {},
            "secrets": [],
        },
        "guard": {
            "character_id": "guard",
            "name": "守门弟子",
            "persona": ["克制", "警惕"],
            "base_style": "说话不多，动作却总带着防备。",
            "base_relationship": {},
            "secrets": [],
        },
    }


class DirectorConflictTriptychTests(unittest.TestCase):
    def test_conflict_marker_forces_generated_lead_in_and_wrap_up(self) -> None:
        state = _build_state(beat="山门前的对峙陡然压低了空气。")
        next_state = apply_director_brief(
            state,
            {
                "beat": "守门弟子上前阻拦",
                "beat_goal": "压住来者气势",
                "focus_character": "guard",
                "tension_target": 0.45,
                "allow_interrupt": True,
                "who_should_respond": ["guard"],
                "lead_in_text": "空气凝住。",
                "wrap_up_text": "请选择你的行动。",
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
            _build_profiles(),
        )

        self.assertGreaterEqual(_sentence_count(next_state["director_brief"]["lead_in_text"]), 2)
        self.assertGreaterEqual(_sentence_count(next_state["director_brief"]["wrap_up_text"]), 2)
        self.assertNotIn("请选择", next_state["director_brief"]["wrap_up_text"])
        self.assertIn("守门弟子", next_state["director_brief"]["lead_in_text"])

    def test_negative_relationship_turn_also_forces_conflict_triptych(self) -> None:
        state = _build_state(beat="气氛尚未完全失衡。", scene_goal="先摸清守门人的态度。")
        state["runtime"]["resolved_act"] = {
            "actor": "player",
            "mode": "speak",
            "target": "guard",
            "content": "player:speak",
            "spoken_text": "player:speak",
            "nonverbal_action": "",
            "next_intent": "",
            "emotion_update": {},
            "relationship_update": {"guard": -0.8},
            "revealed_facts": [],
            "triggered_plot_flags": {},
            "should_end_scene": False,
            "should_end_chapter": False,
        }
        next_state = apply_director_brief(
            state,
            {
                "beat": "守门弟子别过眼去",
                "beat_goal": "关系已经明显转冷",
                "focus_character": "guard",
                "tension_target": 0.3,
                "allow_interrupt": True,
                "who_should_respond": ["guard"],
                "lead_in_text": "",
                "wrap_up_text": "",
                "stage_actions": {
                    "enter": [],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": [],
            },
            _build_profiles(),
        )

        self.assertGreaterEqual(_sentence_count(next_state["director_brief"]["lead_in_text"]), 2)
        self.assertGreaterEqual(_sentence_count(next_state["director_brief"]["wrap_up_text"]), 2)
        self.assertIn("裂纹", next_state["director_brief"]["wrap_up_text"])

    def test_triptych_on_cooldown_within_same_scene_is_suppressed(self) -> None:
        first = _build_state(beat="山门前的对峙陡然压低了空气。")
        conflict_brief = {
            "beat": "守门弟子上前阻拦",
            "beat_goal": "压住来者气势",
            "focus_character": "guard",
            "tension_target": 0.45,
            "allow_interrupt": True,
            "who_should_respond": ["guard"],
            "lead_in_text": "空气凝住。",
            "wrap_up_text": "请选择你的行动。",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        after_first = apply_director_brief(first, dict(conflict_brief), _build_profiles())
        # 第一次落下三段式并记录冷却标记。
        self.assertGreaterEqual(_sentence_count(after_first["director_brief"]["lead_in_text"]), 2)
        self.assertEqual(
            after_first["memory"]["director_memory"]["last_conflict_triptych_scene"], "scene-1"
        )

        # 紧接着同场景下一拍再来:仍在冷却期,兜底不应再贴,短 lead_in 原样透传。
        # 保留冲突 beat,确保是"冷却"而非"触发条件消失"导致的抑制。
        second = {
            **after_first,
            "scene": {**after_first["scene"], "beat": "山门前的对峙陡然压低了空气。"},
            "runtime": {**after_first["runtime"], "turn_index": 1, "resolved_act": None},
        }
        after_second = apply_director_brief(second, dict(conflict_brief), _build_profiles())
        self.assertEqual(after_second["director_brief"]["lead_in_text"], "空气凝住。")

    def test_triptych_fires_again_in_a_new_scene(self) -> None:
        first = _build_state(beat="山门前的对峙陡然压低了空气。")
        conflict_brief = {
            "beat": "守门弟子上前阻拦",
            "beat_goal": "压住来者气势",
            "focus_character": "guard",
            "tension_target": 0.45,
            "allow_interrupt": True,
            "who_should_respond": ["guard"],
            "lead_in_text": "空气凝住。",
            "wrap_up_text": "请选择你的行动。",
            "stage_actions": {"enter": [], "leave": [], "suppress": [], "unsuppress": []},
            "notes": [],
        }
        after_first = apply_director_brief(first, dict(conflict_brief), _build_profiles())
        # 换到新场景(scene_id 变化),即便 turn_index 未过冷却拍数也应重新可发。
        # 保留场景 beat 里的冲突标记,使第二拍仍满足三段式触发条件。
        second = {
            **after_first,
            "plot": {**after_first["plot"], "scene_id": "scene-2"},
            "scene": {**after_first["scene"], "beat": "山门前的对峙陡然压低了空气。"},
            "runtime": {**after_first["runtime"], "turn_index": 1, "resolved_act": None},
        }
        after_second = apply_director_brief(second, dict(conflict_brief), _build_profiles())
        self.assertGreaterEqual(_sentence_count(after_second["director_brief"]["lead_in_text"]), 2)


if __name__ == "__main__":
    unittest.main()
