from __future__ import annotations

import unittest

from Actor.ActorFormatter import _build_actor_payload
from CharacterProfile import ensure_character_profile
from Memory.default_provider import DefaultActorMemoryProvider
from GameState import create_character_runtime_state, create_initial_game_state, create_player_state


def _build_state_and_profiles() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    actor_profile = ensure_character_profile(
        {
            "character_id": "guard",
            "name": "Guard",
            "agent_type": "L2",
            "persona": ["careful"],
            "base_style": "brief",
            "base_relationship": {},
            "secrets": [],
            "spiritual_root": "",
            "realm": "",
            "main_technique": "",
            "l2_profile": {
                "core_drive": "keep order",
                "judgement_preference": ["follow authority"],
                "behavior_rule": ["protect self"],
                "speech_style": ["firm"],
                "personality_tags": ["careful"],
            },
        },
        character_id="guard",
    )
    player_profile = ensure_character_profile(
        {
            "character_id": "player",
            "name": "Player",
            "persona": [],
            "base_style": "",
            "base_relationship": {},
            "secrets": [],
            "spiritual_root": "",
            "realm": "",
            "main_technique": "",
        },
        character_id="player",
        include_backpack=True,
    )

    short_term_memory = [
        {
            "turn_recorded": index,
            "summary": f"short-term event {index}",
            "participants": ["guard"],
            "emotion_delta": {},
        }
        for index in range(12)
    ]
    long_term_memory = [
        {
            "turn_recorded": 1,
            "event_summary": "The guard received a warning.",
            "subjective_interpretation": "The tension is rising.",
            "belief_formed": "The player may be a threat.",
            "priority": "high",
            "tags": ["warning"],
            "pin_candidate": False,
            "pin_reason": "",
            "linked_characters": ["player"],
        }
    ]
    pinned_long_term_memory = [
        {
            "turn_recorded": 0,
            "event_summary": "The sect ordered the gate to stay sealed.",
            "subjective_interpretation": "Breaking protocol would be dangerous.",
            "belief_formed": "The gate must not be opened lightly.",
            "priority": "critical",
            "tags": ["plot_flag"],
            "pin_candidate": True,
            "pin_reason": "plot_flag",
            "linked_characters": ["player"],
        }
    ]
    consolidated_memory = [
        {
            "turn_start": 3,
            "turn_end": 7,
            "topic": "player_relation",
            "event_summary": "Repeated exchanges with the player settled into a cautious stance.",
            "subjective_interpretation": "The player rarely shows intent directly.",
            "belief_formed": "Watch for omissions rather than open threats.",
            "linked_characters": ["player"],
            "source_event_count": 3,
            "priority": "high",
        }
    ]
    player_memory = {
        "overall_impression": "Measured but hard to read.",
        "relation_state": {"player": 0.5},
        "key_events": [
            {
                "turn": 11,
                "summary": "The player stayed calm under pressure.",
                "impression": "Composed under stress.",
                "rationale": "The guard expected panic but saw restraint.",
                "relation_delta": 0.25,
                "tags": ["calm"],
            }
        ],
    }

    state = create_initial_game_state(
        plot={
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "current_scene_index": 0,
            "chapter_goal": "Hold the gate.",
            "current_chapter_hooks": [],
            "plot_flags": {},
            "story_premise": "A suspicious visitor arrives at the gate.",
            "exploration_drive": "Decide whether to trust the visitor.",
            "story_outline": [],
            "current_chapter_title": "Gate Tension",
            "current_chapter_overview": "The guard must decide how to respond.",
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
            "location_id": "gate",
            "time_tag": "morning",
            "beat": "A tense inspection.",
            "tension": 0.4,
            "focus_character": "guard",
            "on_stage": ["player", "guard"],
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            "player": create_character_runtime_state(intent="wait"),
            "guard": create_character_runtime_state(
                emotion={"wariness": 0.8},
                intent="question the player",
                known_facts=["The player carries a sealed letter."],
                relationship_delta={"player": -0.5},
                last_turn=11,
                memory={
                    "pinned_long_term_memory": pinned_long_term_memory,
                    "long_term_memory": long_term_memory,
                    "consolidated_memory": consolidated_memory,
                    "short_term_memory": short_term_memory,
                    "player_memory": player_memory,
                },
            ),
        },
        history=[
            {"turn": 1, "speaker": "player", "content": "I need to pass.", "message_kind": "scene"},
            {"turn": 2, "speaker": "guard", "content": "Show your papers.", "message_kind": "scene"},
        ],
        player=create_player_state(controlled_character="player"),
    )
    state["runtime"]["next_act"] = {
        "actor": "guard",
        "mode": "speak",
        "target": "player",
        "motivation": "Probe for a weakness.",
        "content": "",
    }

    profiles = {
        "player": player_profile,
        "guard": actor_profile,
    }
    return state, profiles


class ActorFormatterPayloadTests(unittest.TestCase):
    def test_actor_payload_reorders_memory_and_drops_runtime_memory(self) -> None:
        state, profiles = _build_state_and_profiles()

        actor_id = state["runtime"]["next_act"]["actor"]
        ctx = DefaultActorMemoryProvider(character_profiles=profiles).build(actor_id, state)
        payload = _build_actor_payload(state, ctx)

        self.assertEqual(
            list(payload.keys()),
            [
                "plot",
                "actor_profile",
                "agent_contract",
                "actor_memory",
                "scene_plan",
                "scene",
                "director_brief",
                "player_memory",
                "actor_runtime",
                "next_act",
                "recent_history",
                "recent_short_term_memory",
            ],
        )
        self.assertEqual(
            list(payload["actor_memory"].keys()),
            ["pinned_long_term_memory", "consolidated_memory", "long_term_memory"],
        )
        self.assertEqual(
            payload["actor_memory"]["pinned_long_term_memory"][0]["pin_reason"],
            "plot_flag",
        )
        self.assertEqual(
            payload["actor_memory"]["consolidated_memory"][0]["topic"],
            "player_relation",
        )
        self.assertEqual(payload["player_memory"]["overall_impression"], "Measured but hard to read.")
        self.assertEqual(payload["player_memory"]["relation_state"]["player"], 0.5)
        self.assertNotIn("memory", payload["actor_runtime"])
        self.assertEqual(payload["actor_runtime"]["intent"], "question the player")
        self.assertEqual(len(payload["recent_short_term_memory"]), 10)
        self.assertEqual(
            [item["summary"] for item in payload["recent_short_term_memory"]],
            [f"short-term event {index}" for index in range(2, 12)],
        )
        # recent_history 改用工厂在场过滤后的短期(ctx.short_term),而非 history[-8:]。
        self.assertEqual(payload["recent_history"], list(ctx.short_term))
        # actor_profile 改由 ctx.persona 供给(等价替换)。
        self.assertEqual(payload["actor_profile"], ctx.persona)


if __name__ == "__main__":
    unittest.main()
