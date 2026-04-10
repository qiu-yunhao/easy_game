from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim for local tests
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.builder import prepare_chapter_turn, prepare_story_setup
from Graph.nodes import GraphDependencies
from Graph.transition_nodes import chapter_transition_node, scene_transition_node
from Scheduler.SchedulerDecision import SchedulerDecision
from ScenePlan import empty_scene_plan
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
)


class FakePlaywright:
    class Formatter:
        def scene_candidate_to_plan(self, candidate):
            if not candidate:
                return empty_scene_plan()
            return {
                "scene_goal": str(candidate.get("scene_goal", "") or "").strip(),
                "must_happen": list(candidate.get("must_happen", [])),
                "must_not_happen": list(candidate.get("must_not_happen", [])),
                "dramatic_curve": list(candidate.get("dramatic_curve", [])),
                "character_objectives": dict(candidate.get("character_objectives", {})),
                "exit_condition": str(candidate.get("exit_condition", "") or "").strip(),
                "notes": list(candidate.get("notes", [])),
            }

    def __init__(self) -> None:
        self.formatter = self.Formatter()

    def plan_story_premise(self, **kwargs):
        del kwargs
        return {
            "story_premise": "凡人少年踏入山门外缘，在漫长仙途中摸索自己的因果与归处。",
            "exploration_drive": "他需要一边寻找失散亲人的线索，一边在宗门外围与凡俗地界之间积累修行资粮。",
        }

    def plan_story_outline_brief(self, **kwargs):
        del kwargs
        return [
            {
                "chapter_id": "opening-arc-1",
                "title": "云岚山门外缘",
                "main_goal": "立足山门外缘，摸清入门前的规矩与机缘。",
                "summary": "主角初入云岚山门外缘，在灵田、坊市与接引路之间寻找落脚点，也试探失踪妹妹留下的痕迹。",
                "exploration_hooks": ["接引路旧闻", "山下坊市的悬赏"],
                "key_locations": ["云岚接引道", "山下坊市"],
                "realm_stage": "炼气",
                "next_realm": "筑基",
            },
            {
                "chapter_id": "opening-arc-2",
                "title": "古渡夜市",
                "main_goal": "循着线索前往古渡夜市，接触暗流中的人情与交易。",
                "summary": "主角离开山门外缘，前往古渡夜市追查妹妹消息，并与夜市背后的地方势力发生接触。",
                "exploration_hooks": ["夜市里的旧玉牌", "河上摆渡人的口风"],
                "key_locations": ["古渡夜市", "青石渡口"],
                "realm_stage": "炼气",
                "next_realm": "筑基",
            },
            {
                "chapter_id": "opening-arc-3",
                "title": "黑水残碑",
                "main_goal": "深入黑水旧地，确认失踪者与残碑秘闻的关联。",
                "summary": "随着线索渐明，主角被卷入一处残碑遗址的争夺，开始真正触碰修行界的暗面。",
                "exploration_hooks": ["残碑拓片", "旧宗门的欠账"],
                "key_locations": ["黑水旧地", "残碑谷口"],
                "realm_stage": "筑基",
                "next_realm": "金丹",
            },
        ]

    def expand_current_chapter(self, **kwargs):
        game_state = kwargs["game_state"]
        chapter_id = str(game_state["plot"].get("chapter_id", "") or "").strip()
        if chapter_id == "opening-arc-2":
            return {
                "chapter_title": "古渡夜市",
                "chapter_goal": "借夜市往来查清妹妹线索，同时辨明渡口势力的态度。",
                "chapter_overview": "夜市鱼龙混杂，线索与陷阱并存。主角必须在交易、试探与暗中观察之间找到突破口。",
                "exploration_hooks": ["摆渡人的沉默", "旧玉牌的来路"],
                "key_locations": ["古渡夜市", "青石渡口"],
            }
        return {
            "chapter_title": "云岚山门外缘",
            "chapter_goal": "先在山门外缘立足，再追查妹妹曾经留下的痕迹。",
            "chapter_overview": "主角初到修行地界，既要适应规矩，也要从零碎人情与旧闻里摸索自己的方向。",
            "exploration_hooks": ["接引路旧闻", "坊市悬赏"],
            "key_locations": ["云岚接引道", "山下坊市"],
        }

    def generate_scene_candidates(self, **kwargs):
        game_state = kwargs["game_state"]
        chapter_id = str(game_state["plot"].get("chapter_id", "") or "").strip()
        location_id = str(game_state["scene"].get("location_id", "") or "").strip()
        return [
            {
                "candidate_id": f"{chapter_id}-candidate-1",
                "label": "先探眼前局势",
                "location_id": location_id or "云岚接引道",
                "beat": "气氛压低，先看清四周人事。",
                "scene_goal": "让角色在新局面前先落稳视角与目标。",
                "must_happen": ["玩家获得可行动方向"],
                "must_not_happen": ["直接跳到结论"],
                "dramatic_curve": ["铺垫", "试探", "抛出选择"],
                "character_objectives": {},
                "exit_condition": "玩家或关键角色决定下一步。",
                "notes": ["保持仙侠江湖气。"],
            },
            {
                "candidate_id": f"{chapter_id}-candidate-2",
                "label": "接触线索人物",
                "location_id": location_id or "云岚接引道",
                "beat": "新人物与旧线索在同一处汇拢。",
                "scene_goal": "为当章主线制造第一轮明确牵引。",
                "must_happen": ["至少出现一个可追的线索"],
                "must_not_happen": ["过早揭底"],
                "dramatic_curve": ["接近", "辨认", "留悬念"],
                "character_objectives": {},
                "exit_condition": "线索被接住或被暂时错过。",
                "notes": ["给玩家留探索余地。"],
            },
        ]


class FakeActorCreateAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def sync_supporting_cast(self, **kwargs):
        game_state = kwargs["game_state"]
        chapter_id = str(game_state["plot"].get("chapter_id", "") or "").strip()
        self.calls.append(chapter_id or "opening")
        if chapter_id == "opening-arc-2":
            return {
                "ferryman": {
                    "character_id": "ferryman",
                    "name": "渡口老人",
                    "persona": ["沉默", "精明", "认得来往人情"],
                    "base_style": "言语不多，却总能点到要害。",
                    "base_relationship": {},
                    "secrets": ["他知道夜市中谁在倒卖旧玉牌。"],
                    "background": "守在青石渡口多年的老人，对夜市与水路的风声最熟。",
                    "story_role": "第二章的引路人，为主角打开夜市暗线。",
                    "introduction_hint": "提着旧灯站在渡口边，目光像是在等谁。",
                    "planned_chapter_count": 1,
                    "planned_chapter_ids": ["opening-arc-2"],
                    "profile_source": "actor_create_agent",
                }
            }
        return {
            "younger_sister": {
                "character_id": "younger_sister",
                "name": "阿蘅",
                "persona": ["聪慧", "倔强", "行事果断"],
                "base_style": "人虽年少，做事却有自己的章法。",
                "base_relationship": {},
                "secrets": ["她失踪前曾留下半块旧玉牌。"],
                "background": "主角失散多年的妹妹，曾在山门外缘留下短暂行踪。",
                "story_role": "主角踏上仙途的重要因果，也是前期追索的核心牵引。",
                "introduction_hint": "她的名字总在零散线索里反复浮现。",
                "planned_chapter_count": 1,
                "planned_chapter_ids": ["opening-arc-1"],
                "profile_source": "actor_create_agent",
            }
        }


class FakeNarrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def narrate_story_intro(self, *, intro_kind, **kwargs):
        del kwargs
        self.calls.append(intro_kind)
        if intro_kind == "chapter":
            return "章回再启，主角循着古渡夜色踏入新的风波。"
        return "山门云气未散，少年已怀着旧愿踏上自己的仙途。"


class FakeSceneAwareNarrator(FakeNarrator):
    def narrate_story_intro(self, *, intro_kind, **kwargs):
        if intro_kind == "scene":
            self.calls.append(intro_kind)
            return "洞府石门轻合，药香尚未散尽，沈云烟方才收拢气息，新的动静却已在下一幕悄然逼近。"
        return super().narrate_story_intro(intro_kind=intro_kind, **kwargs)


class FakeRedundantSceneNarrator(FakeNarrator):
    def narrate_story_intro(self, *, intro_kind, state, **kwargs):
        del kwargs
        self.calls.append(intro_kind)
        if intro_kind == "scene":
            return str(state["history"][-1]["content"])
        if intro_kind == "chapter":
            return "章回再启，主角循着古渡夜色踏入新的风波。"
        return "山门云气未散，少年已怀着旧愿踏上自己的仙途。"


class FakePollutedSceneNarrator(FakeNarrator):
    def narrate_story_intro(self, *, intro_kind, **kwargs):
        del kwargs
        self.calls.append(intro_kind)
        if intro_kind == "scene":
            return (
                "上一段风波余意未散。16:player:speak:做好防范准备。"
                "Heuristic scene-end threshold met: latest turn completed a planned beat."
            )
        return "章回再启，主角循着古渡夜色踏入新的风波。"


class FakeSchedulerPolicy:
    def decide_next_turn(self, state) -> SchedulerDecision:
        return {
            "next_actor": None,
            "mode": "event",
            "eligible_actors": list(state["scene"].get("on_stage", [])),
            "reason": "等待玩家或后续结算。",
        }


class NarratorIntroFlowTests(unittest.TestCase):
    def _build_deps(self):
        profiles = build_default_character_profiles(
            {
                "name": "林渡",
                "background": "出身寒村，为了寻找失踪的妹妹阿蘅而踏上修行路。",
                "persona": ["谨慎", "执拗", "不肯轻易认输"],
            }
        )
        scene_config = build_default_scene_config("xianxia_default")
        deps = GraphDependencies(
            scene_config=scene_config,
            character_profiles=profiles,
            playwright_agent=FakePlaywright(),
            actor_create_agent=FakeActorCreateAgent(),
            narrator_agent=FakeSceneAwareNarrator(),
            scheduler_policy=FakeSchedulerPolicy(),
        )
        return profiles, deps

    def test_prepare_story_setup_creates_supporting_cast_and_emits_opening_intro(self) -> None:
        profiles, deps = self._build_deps()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )

        next_state = prepare_story_setup(state, deps)

        self.assertIn("younger_sister", deps.character_profiles)
        self.assertIn("younger_sister", next_state["characters"])
        self.assertIn("spiritual_root", deps.character_profiles["younger_sister"])
        self.assertIn("realm", deps.character_profiles["younger_sister"])
        self.assertEqual(
            deps.character_profiles["younger_sister"]["main_technique"],
            "基础吐纳术",
        )
        self.assertEqual(len(next_state["history"]), 1)
        self.assertEqual(next_state["history"][0]["mode"], "event")
        self.assertEqual(next_state["history"][0]["content"], "山门云气未散，少年已怀着旧愿踏上自己的仙途。")
        self.assertEqual(next_state["history"][0]["narration_source"], "narrator_agent")
        self.assertEqual(next_state["history"][0]["narration_style_preset"], "xianxia_default")
        self.assertEqual(next_state["runtime"]["pending_intro_kind"], "")
        self.assertEqual(next_state["runtime"]["turn_index"], 1)

    def test_prepare_story_setup_only_emits_opening_intro_once(self) -> None:
        profiles, deps = self._build_deps()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )

        state = prepare_story_setup(state, deps)
        state = prepare_story_setup(state, deps)

        self.assertEqual(
            [item["content"] for item in state["history"] if item["mode"] == "event"],
            ["山门云气未散，少年已怀着旧愿踏上自己的仙途。"],
        )
        self.assertEqual(deps.narrator_agent.calls, ["opening"])

    def test_prepare_story_setup_falls_back_to_heuristic_intro_when_narrator_missing(self) -> None:
        profiles, deps = self._build_deps()
        deps.narrator_agent = None
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )

        state = prepare_story_setup(state, deps)

        self.assertEqual(state["history"][0]["narration_source"], "heuristic")
        self.assertEqual(state["history"][0]["mode"], "event")
        self.assertTrue(state["history"][0]["content"])
        self.assertIn("林渡", state["history"][0]["content"])

    def test_chapter_transition_then_prepare_chapter_turn_emits_chapter_intro(self) -> None:
        profiles, deps = self._build_deps()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )
        state = prepare_story_setup(state, deps)
        state = {
            **state,
            "runtime": {
                **state["runtime"],
                "chapter_finished": True,
            },
        }

        state = chapter_transition_node(state, deps)

        self.assertEqual(state["runtime"]["pending_intro_kind"], "chapter")
        self.assertEqual(state["plot"]["chapter_id"], "opening-arc-2")

        state = prepare_chapter_turn(state, deps)

        self.assertIn("ferryman", deps.character_profiles)
        self.assertIn("ferryman", state["characters"])
        self.assertEqual(deps.character_profiles["ferryman"]["main_technique"], "基础吐纳术")
        self.assertEqual(state["history"][-1]["mode"], "event")
        self.assertEqual(state["history"][-1]["content"], "章回再启，主角循着古渡夜色踏入新的风波。")
        self.assertEqual(state["history"][-1]["narration_source"], "narrator_agent")
        self.assertEqual(state["runtime"]["pending_intro_kind"], "")


    def test_scene_transition_then_prepare_chapter_turn_emits_scene_intro(self) -> None:
        profiles, deps = self._build_deps()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )
        state = prepare_story_setup(state, deps)
        state = {
            **state,
            "runtime": {
                **state["runtime"],
                "scene_finished": True,
            },
        }

        state = scene_transition_node(state, deps)

        self.assertEqual(state["runtime"]["pending_intro_kind"], "scene")

        state = prepare_chapter_turn(state, deps)

        self.assertEqual(state["history"][-1]["mode"], "event")
        self.assertEqual(
            state["history"][-1]["content"],
            "洞府石门轻合，药香尚未散尽，沈云烟方才收拢气息，新的动静却已在下一幕悄然逼近。",
        )
        self.assertEqual(state["runtime"]["pending_intro_kind"], "")

    def test_scene_intro_is_suppressed_when_it_duplicates_latest_player_narration(self) -> None:
        profiles, deps = self._build_deps()
        deps.narrator_agent = FakeRedundantSceneNarrator()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )
        state = prepare_story_setup(state, deps)
        latest_turn = int(state["runtime"].get("turn_index", 0) or 0) + 1
        state = {
            **state,
            "history": [
                *state["history"],
                {
                    "turn": latest_turn,
                    "actor": PLAYER_CHARACTER_ID,
                    "mode": "observe",
                    "content": "挂科最后的归宿在归墟边缘站定。足下是灰败的墟土，裂隙间升腾的灰雾如活物般缠上衣摆。他屏息凝神，目光谨慎扫过这片生机与死气纠缠湮灭的奇景。",
                },
            ],
            "runtime": {
                **state["runtime"],
                "turn_index": latest_turn,
                "scene_finished": True,
            },
        }

        state = scene_transition_node(state, deps)
        self.assertEqual(state["runtime"]["pending_intro_kind"], "scene")
        history_count = len(state["history"])

        state = prepare_chapter_turn(state, deps)

        self.assertEqual(len(state["history"]), history_count)
        self.assertEqual(state["history"][-1]["actor"], PLAYER_CHARACTER_ID)
        self.assertEqual(state["runtime"]["pending_intro_kind"], "")

    def test_scene_intro_falls_back_when_narrator_returns_internal_dump_text(self) -> None:
        profiles, deps = self._build_deps()
        deps.narrator_agent = FakePollutedSceneNarrator()
        state = build_default_state(
            player_character=PLAYER_CHARACTER_ID,
            character_profiles=profiles,
        )
        state = prepare_story_setup(state, deps)
        state = {
            **state,
            "memory": {
                **state["memory"],
                "scene_memory": {
                    **state["memory"]["scene_memory"],
                    "active_conflicts": ["守门人对峙未散"],
                    "tension_trend": "high",
                },
            },
            "runtime": {
                **state["runtime"],
                "scene_finished": True,
            },
        }

        state = scene_transition_node(state, deps)
        state = prepare_chapter_turn(state, deps)

        self.assertEqual(state["history"][-1]["narration_source"], "heuristic")
        self.assertNotIn("16:player:speak", state["history"][-1]["content"])
        self.assertNotIn("Heuristic scene-end", state["history"][-1]["content"])
        self.assertIn("余压尚未散尽", state["history"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
