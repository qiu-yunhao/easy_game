from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from CharacterProfile import ensure_character_profiles
from GameState import GameState
from Graph.builder import plan_story_round
from Graph.nodes import GraphDependencies
from Narrator.NarrationPresets import DEFAULT_NARRATION_STYLE_PRESET
from session_bootstrap import (
    AGENT_FIRST_COMPONENT_NAMES,
    PLAYER_CHARACTER_ID,
    build_opening_state,
    build_opening_player_context,
    build_player_profile as build_base_player_profile,
    build_runtime_dependencies,
    build_scene_config,
)


def build_player_profile(customization: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_base_player_profile(
        customization,
        profile_defaults={
            "name": "沈清蘅",
            "gender": "女",
            "race": "人族",
            "background": "出身寻常微末，却始终不肯把一生困在凡俗年月里，怀着求道与求长生的执念踏上修行路。",
            "spiritual_root": "风木双灵根",
            "realm": "炼气六层",
            "persona": ["沉静", "好学", "耐性极强"],
            "base_style": "收敛克制，话不多，但下决定很稳",
            "secret_template": "{name}不愿把命数押在单一宗门、单一师承或单一机缘上，只想走出真正属于自己的长生路。",
        },
    )


def build_demo_character_profiles(
    player_profile: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return ensure_character_profiles({PLAYER_CHARACTER_ID: build_player_profile(player_profile)}, player_character_id=PLAYER_CHARACTER_ID)


def build_demo_scene_config(
    narration_style_preset: str = DEFAULT_NARRATION_STYLE_PRESET,
) -> dict[str, Any]:
    return build_scene_config(
        scene_id="longevity-road-opening",
        default_location_id="云水古道",
        exit_conditions=["玩家明确当前境界阶段最想追逐的修行方向"],
        narration_style_preset=narration_style_preset,
        resolve_preset=False,
    )


def build_demo_state(
    player_character: str | None = None,
    character_profiles: dict[str, dict[str, Any]] | None = None,
) -> GameState:
    profiles = character_profiles or build_demo_character_profiles()
    player_profile = profiles[PLAYER_CHARACTER_ID]
    player_context = build_opening_player_context(player_profile, default_profile_builder=build_player_profile)

    return build_opening_state(
        player_character=player_character,
        chapter_id="longevity-road-1",
        scene_id="longevity-road-opening",
        location_id="云水古道",
        time_tag="清晨",
        beat="初入尘途",
        cultivation_goal="修仙求长生",
        current_player_realm=player_context["realm"],
        current_chapter_realm=player_context["current_realm_stage"],
        next_chapter_realm=player_context["next_realm_stage"],
        player_intent="寻找适合当前境界的修行方向与长生机缘",
        player_objective="先看清眼前有哪些值得尝试的修行路",
        scene_notes=[
            f"玩家角色：{player_context['name']}，{player_profile.get('gender', '未知性别')}，{player_profile.get('race', '未知种族')}。",
            f"背景：{player_context['background']}",
            f"灵根与境界：{player_context['spiritual_root']}，{player_context['realm']}。",
            "开局保持开放感，不预设唯一主线，只保留修仙求长生这一总目标。",
        ],
        director_notes=[
            "先把开局交给玩家决定去向，后续再由剧情系统扩写。"
        ],
    )


def build_dependencies(
    mode: str,
    interactive: bool = False,
    character_profiles: dict[str, dict[str, Any]] | None = None,
    scene_config: dict[str, Any] | None = None,
) -> GraphDependencies:
    return build_runtime_dependencies(
        mode=mode,
        interactive=interactive,
        character_profiles=character_profiles or build_demo_character_profiles(),
        scene_config=scene_config,
        default_scene_config_builder=build_demo_scene_config,
        component_names=tuple(
            name
            for name in AGENT_FIRST_COMPONENT_NAMES
            if name not in {"l1_actor_agent", "l2_actor_agent"}
            and (interactive or name != "semantic_parser_agent")
        ),
    )


def print_round_summary(
    round_index: int,
    state: GameState,
    character_profiles: dict[str, dict[str, Any]],
) -> None:
    runtime = state["runtime"]
    latest_history = state["history"][-1] if state["history"] else None
    latest_actor = runtime.get("last_actor") or "none"
    latest_mode = runtime.get("last_mode") or "none"
    latest_actor_name = character_profiles.get(latest_actor, {}).get("name", latest_actor)
    scene_end = runtime.get("scene_end_evaluation") or {}

    print(f"\n=== Round {round_index} ===")
    print(f"Turn index      : {runtime['turn_index']}")
    if state["plot"].get("current_chapter_title", ""):
        print(f"Chapter         : {state['plot']['current_chapter_title']}")
    print(f"Chapter index   : {state['plot'].get('current_chapter_index', 0)}")
    print(f"Chapter realm   : {state['plot'].get('current_chapter_realm', '')}")
    print(f"Next realm      : {state['plot'].get('next_chapter_realm', '')}")
    print(f"Player realm    : {state['plot'].get('current_player_realm', '')}")
    print(f"Scene index     : {state['plot'].get('current_scene_index', 0)}")
    print(f"Archived arcs   : {len(state['plot'].get('completed_chapters', []))}")
    if state["plot"].get("story_foundation_source", ""):
        print(f"Outline source  : {state['plot']['story_foundation_source']}")
    if state["plot"].get("chapter_focus_source", ""):
        print(f"Chapter source  : {state['plot']['chapter_focus_source']}")
    if state["plot"].get("scene_candidates_source", ""):
        print(f"Scene source    : {state['plot']['scene_candidates_source']}")
    if state["plot"].get("story_premise", ""):
        print(f"Story premise   : {state['plot']['story_premise']}")
    if state["plot"].get("current_chapter_overview", ""):
        print(f"Chapter brief   : {state['plot']['current_chapter_overview']}")
    print(f"Last actor/mode : {latest_actor_name} / {latest_mode}")
    if latest_history:
        print(f"Latest line     : {latest_history['content']}")
    print(f"Plot flags      : {json.dumps(state['plot']['plot_flags'], ensure_ascii=False)}")
    for character_id, runtime_state in state["characters"].items():
        display_name = character_profiles.get(character_id, {}).get("name", character_id)
        print(
            f"{display_name:<16}: "
            f"{json.dumps(runtime_state['relationship_delta'], ensure_ascii=False)}"
        )
    print(
        "Scene end       : "
        f"{scene_end.get('should_end_scene', False)} | {scene_end.get('reason', '')}"
    )
    print(f"Chapter finished: {state['runtime'].get('chapter_finished', False)}")
    print(f"Memory summary  : {state['memory']['scene_memory']['summary']}")
    if state["player"].get("enabled", False):
        print(f"Last player input: {state['player'].get('last_input', '')}")
        parsed_act = state["player"].get("last_parsed_act") or {}
        if parsed_act:
            print(
                "Parsed player act: "
                f"{parsed_act.get('mode', 'unknown')} -> {parsed_act.get('target') or 'none'}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a xianxia dialogue demo and inspect the result."
    )
    parser.add_argument(
        "--mode",
        choices=("agent-first", "heuristic", "live"),
        default="agent-first",
        help=(
            "`agent-first` prefers Playwright/Director/Actor agents. "
            "`heuristic` uses only local fallback logic. "
            "`live` is kept as an alias for `agent-first`."
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Maximum number of rounds to simulate.",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="Print the final full state as JSON.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable player-controlled interaction in the terminal.",
    )
    parser.add_argument(
        "--player-character",
        default=None,
        help="Character id controlled by the player. Implies `--interactive`.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interactive = args.interactive or args.player_character is not None
    player_character = args.player_character or (PLAYER_CHARACTER_ID if interactive else None)
    character_profiles = build_demo_character_profiles()
    state = build_demo_state(
        player_character=player_character,
        character_profiles=character_profiles,
    )
    deps = build_dependencies(
        args.mode,
        interactive=interactive,
        character_profiles=character_profiles,
    )

    if player_character is not None and player_character not in state["characters"]:
        print(f"Unknown player character: {player_character}", file=sys.stderr)
        return 2

    print(f"Mode            : {args.mode}")
    print(f"Scene goal      : {state['scene_plan']['scene_goal']}")
    print(f"Max rounds      : {args.rounds}")
    print(f"Interactive     : {interactive}")
    if interactive and player_character is not None:
        print(
            "Player role     : "
            f"{character_profiles[player_character]['name']} ({player_character})"
        )

    try:
        for round_index in range(1, args.rounds + 1):
            state = plan_story_round(state, deps)
            print_round_summary(round_index, state, character_profiles)
            if state["runtime"].get("scene_finished", False):
                print("\nScene finished early.")
                break
    except RuntimeError as exc:
        print(f"\nRun failed: {exc}", file=sys.stderr)
        if args.mode in {"agent-first", "live"}:
            print(
                "Tip: install the `openai` package and confirm your LLM env vars are configured.",
                file=sys.stderr,
            )
        return 1

    if args.dump_json:
        print("\n=== Final State JSON ===")
        print(json.dumps(state, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
