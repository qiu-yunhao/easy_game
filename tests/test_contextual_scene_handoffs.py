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

from CharacterProfile import ensure_character_profile
from ComponentFactory import ComponentFactory
from GameState import create_character_runtime_state
from Graph.builder import prepare_chapter_turn
from Graph.contextual_scene_handoffs import (
    apply_contextual_scene_progression,
    build_contextual_scene_handoff,
)
from Graph.nodes import GraphDependencies
from Graph.transition_nodes import scene_transition_node
from ResolvedActUtils import build_resolved_act_payload
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
)


class FakeDirector:
    def update_stage(self, state, character_profiles):
        del character_profiles
        player_id = str(state["player"].get("controlled_character", "") or "").strip()
        on_stage = [
            actor_id
            for actor_id in state["scene"].get("on_stage", [])
            if str(actor_id).strip()
        ]
        focus_character = on_stage[0] if on_stage else player_id
        return {
            "beat": str(state["scene"].get("beat", "") or "").strip(),
            "beat_goal": str(state["scene_plan"].get("scene_goal", "") or "").strip(),
            "focus_character": focus_character,
            "tension_target": float(state["scene"].get("tension", 0.35) or 0.35),
            "allow_interrupt": False,
            "who_should_respond": [focus_character] if focus_character else [],
            "stage_actions": {
                "enter": [],
                "leave": [],
                "suppress": [],
                "unsuppress": [],
            },
            "notes": [],
        }


class EnteringDirector:
    def update_stage(self, state, character_profiles):
        hall_guide_id = "hall_guide"
        if (
            str(state["scene"].get("location_id", "") or "").strip() == "宗门大殿"
            and hall_guide_id in character_profiles
            and hall_guide_id not in state["scene"].get("on_stage", [])
        ):
            return {
                "beat": "宗门大殿的接引与试探",
                "beat_goal": "由导演判断此处需要一名接引弟子现身",
                "focus_character": hall_guide_id,
                "tension_target": 0.38,
                "allow_interrupt": False,
                "who_should_respond": [hall_guide_id],
                "stage_actions": {
                    "enter": [hall_guide_id],
                    "leave": [],
                    "suppress": [],
                    "unsuppress": [],
                },
                "notes": ["此环境是否带 NPC，由导演基于场景目标决定。"],
            }
        return FakeDirector().update_stage(state, character_profiles)


class ContextualSceneHandoffTests(unittest.TestCase):
    def _build_state_and_deps(self):
        character_profiles = build_default_character_profiles()
        state = build_default_state(
            character_profiles=character_profiles,
            player_character=PLAYER_CHARACTER_ID,
        )
        deps = GraphDependencies(
            scene_config=build_default_scene_config(),
            character_profiles=character_profiles,
            director_agent=FakeDirector(),
            component_factory=ComponentFactory(),
            agent_first=False,
        )
        return state, deps

    def _build_travel_state(self, state, player_input: str):
        resolved_act = build_resolved_act_payload(
            actor=PLAYER_CHARACTER_ID,
            mode="move",
            target=None,
            content="沈云烟收束气息，循着心中目标离开原处。",
            spoken_text="",
            nonverbal_action="沈云烟提气掠步，已然踏上前路。",
            next_intent=player_input,
        )
        return {
            **state,
            "player": {
                **state["player"],
                "last_input": player_input,
            },
            "runtime": {
                **state["runtime"],
                "resolved_act": resolved_act,
                "scene_finished": True,
                "chapter_finished": False,
            },
        }

    def test_contextual_handoff_defaults_to_player_only_scene(self) -> None:
        state, deps = self._build_state_and_deps()
        state = self._build_travel_state(state, "前往宗门大殿，领取镇宗功法")
        original_profile_ids = set(deps.character_profiles)

        handoff = build_contextual_scene_handoff(
            state,
            scene_config=deps.scene_config,
            character_profiles=deps.character_profiles,
            actor_create_agent=None,
        )
        self.assertIsNotNone(handoff)
        assert handoff is not None
        self.assertEqual(handoff["default_on_stage"], [PLAYER_CHARACTER_ID])
        self.assertEqual(handoff["supplemental_profiles"], {})
        self.assertFalse(handoff["skip_transition_intro"])

        next_state = scene_transition_node(state, deps)

        self.assertEqual(next_state["scene"]["location_id"], "宗门大殿")
        self.assertEqual(next_state["scene"]["on_stage"], [PLAYER_CHARACTER_ID])
        self.assertEqual(next_state["runtime"]["eligible_actors"], [PLAYER_CHARACTER_ID])
        self.assertEqual(next_state["runtime"]["pending_intro_kind"], "scene")
        self.assertEqual(next_state["plot"]["scene_candidates_source"], "contextual_handoff")
        self.assertEqual(set(deps.character_profiles), original_profile_ids)

    def test_prepare_chapter_turn_keeps_player_as_only_scheduled_actor(self) -> None:
        state, deps = self._build_state_and_deps()
        state = self._build_travel_state(state, "前往宗门大殿，领取镇宗功法")
        state = scene_transition_node(state, deps)

        next_state = prepare_chapter_turn(state, deps)

        self.assertEqual(next_state["scene"]["on_stage"], [PLAYER_CHARACTER_ID])
        self.assertEqual(next_state["director_brief"]["who_should_respond"], [PLAYER_CHARACTER_ID])
        self.assertEqual(next_state["runtime"]["next_act"]["actor"], PLAYER_CHARACTER_ID)

    def test_director_can_choose_to_bring_off_stage_actor_into_environment(self) -> None:
        state, deps = self._build_state_and_deps()
        deps.director_agent = EnteringDirector()
        deps.character_profiles["hall_guide"] = ensure_character_profile(
            {
                "character_id": "hall_guide",
                "name": "殿前引路弟子",
                "story_role": "负责在宗门大殿维持秩序并为新入门弟子指路的 ActorAgent。",
                "persona": ["克制", "守礼"],
                "base_style": "答话简短，不失分寸。",
                "introduction_hint": "若导演认为需要人出面接引，可由他先行现身。",
            },
            character_id="hall_guide",
        )
        state["characters"]["hall_guide"] = create_character_runtime_state(
            intent="在需要时接引前来领取功法的弟子。"
        )
        state = self._build_travel_state(state, "前往宗门大殿，领取镇宗功法")
        state = scene_transition_node(state, deps)

        next_state = prepare_chapter_turn(state, deps)

        self.assertIn("hall_guide", next_state["scene"]["on_stage"])
        self.assertEqual(next_state["director_brief"]["focus_character"], "hall_guide")
        self.assertEqual(next_state["director_brief"]["who_should_respond"], ["hall_guide"])
        self.assertEqual(next_state["runtime"]["next_act"]["actor"], "hall_guide")

    def test_explicit_direct_cut_skips_transition_intro(self) -> None:
        state, deps = self._build_state_and_deps()
        state = self._build_travel_state(state, "直接前往宗门大殿，领取镇宗功法")

        state = scene_transition_node(state, deps)

        self.assertEqual(state["scene"]["location_id"], "宗门大殿")
        self.assertEqual(state["runtime"]["pending_intro_kind"], "")
        history_count = len(state["history"])

        state = prepare_chapter_turn(state, deps)

        self.assertEqual(len(state["history"]), history_count)
        self.assertEqual(state["runtime"]["next_act"]["actor"], PLAYER_CHARACTER_ID)

    def test_reward_claim_updates_backpack_without_npc_handover(self) -> None:
        state, deps = self._build_state_and_deps()
        resolved_act = build_resolved_act_payload(
            actor=PLAYER_CHARACTER_ID,
            mode="act",
            target=None,
            content="沈云烟依照门规领取镇宗功法，将玉简收入袖中。",
            spoken_text="",
            nonverbal_action="她抬手接过玉简，指尖在封纹上轻轻一按。",
            triggered_plot_flags={"领取镇宗功法": "宗门登记已完成"},
        )
        state = {
            **state,
            "scene_plan": {
                **state["scene_plan"],
                "must_happen": ["领取镇宗功法"],
            },
            "runtime": {
                **state["runtime"],
                "resolved_act": resolved_act,
            },
        }

        apply_contextual_scene_progression(state, deps.character_profiles)

        self.assertEqual(
            deps.character_profiles[PLAYER_CHARACTER_ID]["backpack"],
            [{"id": "镇宗功法", "name": "镇宗功法", "quantity": 1}],
        )


if __name__ == "__main__":
    unittest.main()
