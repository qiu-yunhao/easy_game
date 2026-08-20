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

from ComponentFactory import ComponentFactory
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state
from GameplayTuning import GameplayTuning, NarrationTuning
from Graph.builder import resolve_story_turn
from Graph.nodes import GraphDependencies, actor_node, cultivation_progress_node, director_node, scheduler_node
from History.GameMemory import empty_memory_state
from Memory.default_provider import DefaultActorMemoryProvider
from PlayerControl import BufferedPlayerInterface
from ResolvedActUtils import build_resolved_act_payload
from ScenePlan import empty_scene_plan
from session_bootstrap import register_default_hooks


class FakeDirector:
    def __init__(self, brief: dict[str, object]) -> None:
        self.brief = brief

    def update_stage(self, state, character_profiles):
        del state, character_profiles
        return self.brief


class FakeActor:
    def perform_turn(self, state, memory_ctx):
        del memory_ctx
        planned = state["runtime"].get("next_act") or {}
        actor = planned.get("actor")
        mode = planned.get("mode", "speak")
        target = planned.get("target")
        return build_resolved_act_payload(
            actor=actor,
            mode=mode,
            target=target,
            content=f"{actor}:{mode}",
            spoken_text=f"{actor}:{mode}",
        )


class FakeTierActor:
    def __init__(self, label: str) -> None:
        self.label = label

    def perform_turn(self, state, memory_ctx):
        del memory_ctx
        planned = state["runtime"].get("next_act") or {}
        actor = planned.get("actor")
        return build_resolved_act_payload(
            actor=actor,
            mode=planned.get("mode", "speak"),
            target=planned.get("target"),
            content=f"{self.label}:{actor}",
            spoken_text=f"{self.label}:{actor}",
        )


class FakeSemanticParser:
    def parse_action(self, raw_input, state, character_profiles):
        del raw_input, character_profiles
        planned = state["runtime"].get("next_act") or {}
        actor = planned.get("actor")
        mode = planned.get("mode", "speak")
        target = planned.get("target")
        return build_resolved_act_payload(
            actor=actor,
            mode=mode,
            target=target,
            content=f"{actor}:{mode}",
            spoken_text=f"{actor}:{mode}",
        )


class FakeNarratorAgent:
    def narrate_action_batch(self, *, state, character_profiles, batch, style_preset):
        del state, character_profiles, style_preset
        return [
            {
                "history_turn": item["history_turn"],
                "actor": item["actor"],
                "narrated_text": f"NARRATED[{item['actor']}]",
            }
            for item in batch
        ]


class FakeStylisticPolishAgent:
    def polish_narration_batch(self, segments, *, style_preset, state, character_profiles):
        del style_preset, state, character_profiles
        return [
            {
                **segment,
                "narrated_text": f"POLISHED[{segment['narrated_text']}]",
            }
            for segment in segments
        ]


def _build_state(
    *,
    on_stage: list[str],
    focus_character: str | None,
    player_enabled: bool = False,
    player_character: str | None = None,
):
    cast = {"player", *on_stage}
    return create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "",
            "exploration_drive": "",
            "story_outline": [],
            "current_chapter_title": "",
            "current_chapter_overview": "",
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
            "location_id": "room",
            "time_tag": "now",
            "beat": "",
            "tension": 0.2,
            "focus_character": focus_character,
            "on_stage": on_stage,
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            actor_id: create_character_runtime_state(intent=f"{actor_id}-intent")
            for actor_id in cast
        },
        scene_plan={
            **empty_scene_plan(),
            "scene_goal": "advance the beat",
            "character_objectives": {
                actor_id: f"{actor_id}-objective" for actor_id in cast
            },
        },
        memory=empty_memory_state(),
        player=create_player_state(
            enabled=player_enabled,
            controlled_character=player_character,
        ),
    )


def _build_profiles(cast: list[str]) -> dict[str, dict[str, object]]:
    return {
        actor_id: {
            "character_id": actor_id,
            "name": actor_id,
            "persona": [],
            "base_style": "",
            "background": "",
            "spiritual_root": "",
            "realm": "",
            "main_technique": "",
            "gender": "",
            "race": "",
            "base_relationship": {},
            "secrets": [],
        }
        for actor_id in cast
    }


class BeatResolutionTests(unittest.TestCase):
    def test_actor_node_folds_l2_into_default_actor_agent(self) -> None:
        state = _build_state(
            on_stage=["npc_a"],
            focus_character="npc_a",
        )
        state["runtime"]["next_act"] = {
            "actor": "npc_a",
            "mode": "speak",
            "target": None,
            "motivation": "",
            "content": "",
        }
        profiles = _build_profiles(["player", "npc_a"])
        profiles["npc_a"]["agent_type"] = "L2"
        profiles["npc_a"]["l2_profile"] = {
            "core_drive": "保住差事",
            "judgement_preference": ["服从权威"],
            "behavior_rule": ["先稳局面"],
            "speech_style": ["简短谨慎"],
            "personality_tags": ["谨慎"],
        }
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            actor_agent=FakeTierActor("default"),
            l1_actor_agent=FakeTierActor("l1"),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)

        next_state = actor_node(state, deps)

        # Two-tier: former L2 profiles now route to the NPC-Actor (default) agent.
        self.assertEqual(next_state["runtime"]["resolved_act"]["spoken_text"], "default:npc_a")

    def test_actor_node_dispatches_to_l1_actor_agent(self) -> None:
        state = _build_state(
            on_stage=["npc_a"],
            focus_character="npc_a",
        )
        state["runtime"]["next_act"] = {
            "actor": "npc_a",
            "mode": "speak",
            "target": None,
            "motivation": "",
            "content": "",
        }
        profiles = _build_profiles(["player", "npc_a"])
        profiles["npc_a"]["agent_type"] = "L1"
        profiles["npc_a"]["l1_profile"] = {
            "core_conflict": "在责任与私欲之间摇摆",
            "outer_goal": "赢下这一局",
            "inner_need": "证明自己不是傀儡",
            "contradiction_axes": ["责任/自由"],
            "relationship_pressure": ["师门期待"],
        }
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            actor_agent=FakeTierActor("default"),
            l1_actor_agent=FakeTierActor("l1"),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)

        next_state = actor_node(state, deps)

        self.assertEqual(next_state["runtime"]["resolved_act"]["spoken_text"], "l1:npc_a")

    def test_actor_node_keeps_default_actor_agent_for_plain_actor_profiles(self) -> None:
        state = _build_state(
            on_stage=["npc_a"],
            focus_character="npc_a",
        )
        state["runtime"]["next_act"] = {
            "actor": "npc_a",
            "mode": "speak",
            "target": None,
            "motivation": "",
            "content": "",
        }
        profiles = _build_profiles(["player", "npc_a"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            actor_agent=FakeTierActor("default"),
            l1_actor_agent=FakeTierActor("l1"),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)

        next_state = actor_node(state, deps)

        self.assertEqual(next_state["runtime"]["resolved_act"]["spoken_text"], "default:npc_a")

    def test_resolve_story_turn_emits_director_lead_in_and_wrap_up_around_auto_event(self) -> None:
        state = _build_state(
            on_stage=["player", "npc_a"],
            focus_character="npc_a",
            player_enabled=True,
            player_character="player",
        )
        profiles = _build_profiles(["player", "npc_a"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["player", "npc_a"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "mysterious arrival",
                    "beat_goal": "npc_a breaks the silence and then yields back to the player",
                    "focus_character": "npc_a",
                    "tension_target": 0.42,
                    "allow_interrupt": False,
                    "who_should_respond": ["npc_a", "player"],
                    "lead_in_text": "屋内的烛火轻轻一晃，沉闷的空气像是被什么无形的东西牵动了一瞬。",
                    "wrap_up_text": "那一瞬掠过众人心头的异样并未散去，视线仍不自觉地停在刚刚发声之人的方向。",
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            player_interface=BufferedPlayerInterface(),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        self.assertEqual([item["actor"] for item in state["history"]], [None, "npc_a", None])
        self.assertEqual(
            [item["content"] for item in state["history"]],
            [
                "屋内的烛火轻轻一晃，沉闷的空气像是被什么无形的东西牵动了一瞬。",
                "POLISHED[NARRATED[npc_a]]",
                "那一瞬掠过众人心头的异样并未散去，视线仍不自觉地停在刚刚发声之人的方向。",
            ],
        )
        self.assertEqual(
            [item.get("narration_source", "") for item in state["history"]],
            ["director_lead_in", "narrator_agent", "director_wrap_up"],
        )
        self.assertEqual(state["runtime"]["next_act"]["actor"], "player")
        self.assertEqual(state["director_brief"]["lead_in_text"], "")
        self.assertEqual(state["director_brief"]["wrap_up_text"], "")

    def test_resolve_story_turn_consumes_multiple_actor_actions_in_one_beat(self) -> None:
        state = _build_state(
            on_stage=["npc_a", "npc_b"],
            focus_character="npc_a",
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a", "npc_b"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "exchange",
                    "beat_goal": "npc_a and npc_b both answer",
                    "focus_character": "npc_a",
                    "tension_target": 0.3,
                    "allow_interrupt": True,
                    "who_should_respond": ["npc_a", "npc_b"],
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        self.assertEqual([item["actor"] for item in state["history"]], ["npc_a", "npc_b"])
        self.assertEqual(
            [item["content"] for item in state["history"]],
            ["POLISHED[NARRATED[npc_a]]", "POLISHED[NARRATED[npc_b]]"],
        )
        self.assertIsNone(state["runtime"]["next_act"])
        self.assertEqual(state["runtime"]["pending_beat_actors"], [])
        self.assertEqual(state["runtime"]["beat_fallback_turns_remaining"], 0)
        self.assertEqual(state["runtime"]["narration_queue"], [])

    def test_resolve_story_turn_pauses_at_player_handoff_and_can_resume(self) -> None:
        player_interface = BufferedPlayerInterface()
        state = _build_state(
            on_stage=["player", "npc_a", "npc_b"],
            focus_character="npc_a",
            player_enabled=True,
            player_character="player",
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["player", "npc_a", "npc_b"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "handoff",
                    "beat_goal": "npc_a, player, npc_b act in order",
                    "focus_character": "npc_a",
                    "tension_target": 0.4,
                    "allow_interrupt": True,
                    "who_should_respond": ["npc_a", "player", "npc_b"],
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            semantic_parser_agent=FakeSemanticParser(),
            player_interface=player_interface,
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        self.assertEqual([item["actor"] for item in state["history"]], ["npc_a"])
        self.assertEqual(state["history"][0]["content"], "POLISHED[NARRATED[npc_a]]")
        self.assertEqual(state["runtime"]["next_act"]["actor"], "player")
        self.assertEqual(state["runtime"]["pending_beat_actors"], ["player", "npc_b"])

        player_interface.push_action("player speaks")
        state = resolve_story_turn(state, deps)

        self.assertEqual(
            [item["actor"] for item in state["history"]],
            ["npc_a", "player", "npc_b"],
        )
        self.assertEqual(
            [item["content"] for item in state["history"]],
            [
                "POLISHED[NARRATED[npc_a]]",
                "POLISHED[NARRATED[player]]",
                "POLISHED[NARRATED[npc_b]]",
            ],
        )
        self.assertIsNone(state["runtime"]["next_act"])
        self.assertEqual(state["runtime"]["pending_beat_actors"], [])
        self.assertEqual(state["runtime"]["narration_queue"], [])

    def test_resolve_story_turn_batches_three_distinct_actors(self) -> None:
        state = _build_state(
            on_stage=["npc_a", "npc_b", "npc_c"],
            focus_character="npc_a",
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b", "npc_c"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a", "npc_b", "npc_c"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "triangle",
                    "beat_goal": "three actors exchange reactions",
                    "focus_character": "npc_a",
                    "tension_target": 0.35,
                    "allow_interrupt": True,
                    "who_should_respond": ["npc_a", "npc_b", "npc_c"],
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        self.assertEqual(
            [item["actor"] for item in state["history"]],
            ["npc_a", "npc_b", "npc_c"],
        )
        self.assertEqual(
            [item["content"] for item in state["history"]],
            [
                "POLISHED[NARRATED[npc_a]]",
                "POLISHED[NARRATED[npc_b]]",
                "POLISHED[NARRATED[npc_c]]",
            ],
        )

    def test_resolve_story_turn_persists_selected_narration_style_on_history(self) -> None:
        state = _build_state(
            on_stage=["npc_a", "npc_b"],
            focus_character="npc_a",
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a", "npc_b"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "exchange",
                    "beat_goal": "npc_a and npc_b both answer",
                    "focus_character": "npc_a",
                    "tension_target": 0.3,
                    "allow_interrupt": True,
                    "who_should_respond": ["npc_a", "npc_b"],
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            gameplay_tuning=GameplayTuning(
                narration=NarrationTuning(style_preset="epic")
            ),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        self.assertTrue(state["history"])
        self.assertTrue(
            all(item.get("narration_style_preset") == "epic" for item in state["history"])
        )

    def test_cultivation_progress_emits_visible_result_even_without_breakthrough(self) -> None:
        state = _build_state(
            on_stage=["player"],
            focus_character="player",
            player_enabled=True,
            player_character="player",
        )
        profiles = _build_profiles(["player"])
        profiles["player"].update(
            {
                "name": "沈云烟",
                "realm": "练气一层",
            }
        )
        state["plot"]["current_player_realm"] = "练气一层"
        state["plot"]["current_chapter_realm"] = "练气一层"
        state["plot"]["next_chapter_realm"] = "练气二层"
        state["runtime"]["resolved_act"] = build_resolved_act_payload(
            actor="player",
            mode="action",
            target=None,
            content="沈云烟回到洞府，服下养气丹后盘膝修炼。",
            nonverbal_action="沈云烟回到洞府，服下养气丹后盘膝修炼。",
            next_intent="继续稳固修为。",
        )
        state["player"]["last_input"] = "回到清静洞府，服下养气丹修炼。"

        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["player"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            component_factory=ComponentFactory(),
        )
        register_default_hooks(deps)

        next_state = cultivation_progress_node(state, deps)

        self.assertEqual(next_state["history"][-1]["mode"], "event")
        self.assertEqual(next_state["history"][-1]["narration_source"], "cultivation_progress")
        self.assertIn("沈云烟", next_state["history"][-1]["content"])
        self.assertEqual(deps.character_profiles["player"]["realm"], "练气一层")


class ParallelGroupBeatTest(unittest.TestCase):
    def test_group_of_two_read_same_start_history(self) -> None:
        seen_history_lens: dict[str, int] = {}

        class RecordingActor:
            def perform_turn(self, state, memory_ctx):
                del memory_ctx
                planned = state["runtime"].get("next_act") or {}
                actor = planned.get("actor")
                seen_history_lens[actor] = len(state["history"])
                return build_resolved_act_payload(
                    actor=actor,
                    mode=planned.get("mode", "speak"),
                    target=planned.get("target"),
                    content=f"{actor}:line",
                    spoken_text=f"{actor}:line",
                )

        state = _build_state(
            on_stage=["npc_a", "npc_b"],
            focus_character=None,
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a", "npc_b"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "parallel",
                    "beat_goal": "npc_a and npc_b speak independently",
                    "focus_character": None,
                    "tension_target": 0.3,
                    "allow_interrupt": False,
                    "who_should_respond": ["npc_a", "npc_b"],
                    "response_groups": [["npc_a", "npc_b"]],
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=RecordingActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        self.assertEqual(
            state["runtime"]["pending_response_groups"],
            [["npc_a", "npc_b"]],
        )

        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        actors = [item["actor"] for item in state["history"] if item["actor"] in ("npc_a", "npc_b")]
        self.assertEqual(actors, ["npc_a", "npc_b"])
        # Parallel invariant: both actors generated against the SAME group-start
        # history. In the old serial loop npc_b would have seen npc_a's line
        # (history_len larger by one).
        self.assertEqual(seen_history_lens["npc_a"], seen_history_lens["npc_b"])
        self.assertIsNone(state["runtime"]["next_act"])
        self.assertEqual(state["runtime"]["pending_beat_actors"], [])


    def test_group_path_emits_director_lead_in(self) -> None:
        lead_in = "两人几乎同时开口，屋内的空气骤然绷紧。"

        state = _build_state(
            on_stage=["npc_a", "npc_b"],
            focus_character=None,
        )
        profiles = _build_profiles(["player", "npc_a", "npc_b"])
        deps = GraphDependencies(
            scene_config={
                "scene_id": "scene-1",
                "default_location_id": "room",
                "default_on_stage": ["npc_a", "npc_b"],
            },
            character_profiles=profiles,
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
            director_agent=FakeDirector(
                {
                    "beat": "parallel",
                    "beat_goal": "npc_a and npc_b speak independently",
                    "focus_character": None,
                    "tension_target": 0.3,
                    "allow_interrupt": False,
                    "who_should_respond": ["npc_a", "npc_b"],
                    "response_groups": [["npc_a", "npc_b"]],
                    "lead_in_text": lead_in,
                    "stage_actions": {
                        "enter": [],
                        "leave": [],
                        "suppress": [],
                        "unsuppress": [],
                    },
                    "notes": [],
                }
            ),
            actor_agent=FakeActor(),
            narrator_agent=FakeNarratorAgent(),
            stylistic_polish_agent=FakeStylisticPolishAgent(),
            component_factory=ComponentFactory(),
            agent_first=True,
        )
        register_default_hooks(deps)

        state = director_node(state, deps)
        state = scheduler_node(state, deps)
        state = resolve_story_turn(state, deps)

        # The beat's one-shot lead-in fires on the group path (regression: it was
        # previously dropped because _group_step skipped director_lead_in).
        lead_in_events = [
            item for item in state["history"]
            if item.get("narration_source") == "director_lead_in"
        ]
        self.assertEqual([item["content"] for item in lead_in_events], [lead_in])
        self.assertEqual(state["director_brief"]["lead_in_text"], "")


if __name__ == "__main__":
    unittest.main()
