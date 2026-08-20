from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from CharacterProfile import (
    DEFAULT_CURRENT_REALM,
    DEFAULT_MAIN_TECHNIQUE,
    DEFAULT_SPIRITUAL_ROOT,
    ensure_character_profile,
    ensure_character_profiles,
    normalize_backpack_items,
)
from ComponentFactory import ComponentFactory
from Cultivation import (
    build_chapter_transition_requirement,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
)
from GameplayTuning import GameplayTuning, NarrationTuning
from GameState import (
    GameState,
    create_character_runtime_state,
    create_initial_game_state,
    create_player_state,
)
from Actor import apply_resolved_act
from Graph.contextual_scene_handoffs import apply_contextual_scene_progression
from Graph.nodes import GraphDependencies
from History import HistoryManager
from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.MemoryRefreshPolicy import decide_refresh
from Memory.default_provider import DefaultActorMemoryProvider
from Memory.store import MemoryStore
from Narrator.NarrationPresets import (
    DEFAULT_NARRATION_STYLE_PRESET,
    resolve_narration_style_preset,
)
from PlayerControl import ConsolePlayerInterface
from StoryStateUtils import clean_str_list, clean_text


PLAYER_CHARACTER_ID = "player"
AGENT_FIRST_COMPONENT_NAMES = (
    "playwright_agent",
    "actor_create_agent",
    "director_agent",
    "actor_agent",
    "l1_actor_agent",
    "narrator_agent",
    "history_summarizer_agent",
    "player_intent_planner_agent",
    "semantic_parser_agent",
    "stylistic_polish_agent",
)


def _warm_model_client(build_client: Any) -> None:
    try:
        build_client()
    except Exception:
        # Warm-up is best-effort so we preserve the original lazy failure mode.
        return


def build_agent_first_components(
    component_factory: ComponentFactory,
    *,
    component_names: tuple[str, ...] = AGENT_FIRST_COMPONENT_NAMES,
) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=len(component_names)) as executor:
        futures = {
            name: executor.submit(getattr(component_factory, f"build_{name}"))
            for name in component_names
        }
    return {
        name: future.result()
        for name, future in futures.items()
    }


def warm_model_clients(*agents: Any) -> None:
    warmables = [
        build_client
        for agent in agents
        if callable(build_client := getattr(agent, "_build_client", None))
    ]
    if not warmables:
        return

    with ThreadPoolExecutor(max_workers=len(warmables)) as executor:
        for _ in executor.map(_warm_model_client, warmables):
            pass


def attach_agent_first_components(
    deps: GraphDependencies,
    component_factory: ComponentFactory,
    *,
    component_names: tuple[str, ...] = AGENT_FIRST_COMPONENT_NAMES,
    warm_clients_after_attach: bool = False,
) -> None:
    components = build_agent_first_components(
        component_factory,
        component_names=component_names,
    )
    for name, component in components.items():
        setattr(deps, name, component)
    if deps.history_manager is not None:
        deps.history_manager.summarizer_agent = deps.history_summarizer_agent
    if warm_clients_after_attach:
        warm_model_clients(*components.values())


def build_player_profile(
    customization: dict[str, Any] | None = None,
    *,
    profile_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    customization = customization or {}
    defaults = {
        "name": "无名修士",
        "gender": "未定",
        "race": "人族",
        "background": "出身凡俗乡野，因机缘叩开仙门，对长生之道既敬且疑。",
        "spiritual_root": DEFAULT_SPIRITUAL_ROOT,
        "realm": DEFAULT_CURRENT_REALM,
        "main_technique": DEFAULT_MAIN_TECHNIQUE,
        "persona": ["谨慎", "好奇", "不甘平凡"],
        "base_style": "言语克制，遇事先观察局势，再决定是否出手。",
        "secret_template": "{name}心底始终放不下那份想要窥见天命真相的执念。",
    }
    if profile_defaults:
        defaults.update(profile_defaults)

    name = clean_text(customization.get("name"), defaults["name"])
    gender = clean_text(customization.get("gender"), defaults["gender"])
    race = clean_text(customization.get("race"), defaults["race"])
    background = clean_text(customization.get("background"), defaults["background"])
    spiritual_root = clean_text(customization.get("spiritual_root"), defaults["spiritual_root"])
    realm = normalize_realm_text(customization.get("realm"), defaults["realm"])
    main_technique = clean_text(customization.get("main_technique"), defaults["main_technique"])
    backpack = normalize_backpack_items(customization.get("backpack", []))

    persona = clean_str_list(customization.get("persona")) or list(defaults["persona"])
    base_style = clean_text(customization.get("base_style"), defaults["base_style"])
    secrets = clean_str_list(customization.get("secrets")) or [
        defaults["secret_template"].format(name=name)
    ]

    return ensure_character_profile(
        {
            "character_id": PLAYER_CHARACTER_ID,
            "name": name,
            "gender": gender,
            "race": race,
            "background": background,
            "spiritual_root": spiritual_root,
            "realm": realm,
            "main_technique": main_technique,
            "backpack": backpack,
            "persona": persona,
            "base_style": base_style,
            "base_relationship": {},
            "secrets": secrets,
        },
        character_id=PLAYER_CHARACTER_ID,
        include_backpack=True,
    )


def build_default_character_profiles(
    player_profile: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return ensure_character_profiles({PLAYER_CHARACTER_ID: build_player_profile(player_profile)}, player_character_id=PLAYER_CHARACTER_ID)


def build_scene_config(
    *,
    scene_id: str,
    default_location_id: str,
    exit_conditions: list[str],
    narration_style_preset: str = DEFAULT_NARRATION_STYLE_PRESET,
    resolve_preset: bool = True,
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "default_location_id": default_location_id,
        "default_on_stage": [PLAYER_CHARACTER_ID],
        "entry_conditions": [],
        "exit_conditions": exit_conditions,
        "narration_style_preset": (
            resolve_narration_style_preset(narration_style_preset)
            if resolve_preset
            else narration_style_preset
        ),
    }


def build_default_scene_config(
    narration_style_preset: str = DEFAULT_NARRATION_STYLE_PRESET,
) -> dict[str, Any]:
    return build_scene_config(
        scene_id="opening-scene",
        default_location_id="云峰入门台",
        exit_conditions=["玩家已看清眼前局势，并准备正式踏入修行世界。"],
        narration_style_preset=narration_style_preset,
    )


def normalize_scene_config(
    scene_config: dict[str, Any] | None,
    *,
    default_scene_config_builder: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    resolved_scene_config = dict(scene_config or default_scene_config_builder())
    resolved_scene_config["narration_style_preset"] = resolve_narration_style_preset(
        resolved_scene_config.get("narration_style_preset", DEFAULT_NARRATION_STYLE_PRESET)
    )
    return resolved_scene_config, resolved_scene_config["narration_style_preset"]


def build_opening_state(
    *,
    player_character: str | None,
    chapter_id: str,
    scene_id: str,
    location_id: str,
    time_tag: str,
    beat: str,
    cultivation_goal: str,
    current_player_realm: str,
    current_chapter_realm: str,
    next_chapter_realm: str,
    player_intent: str,
    player_objective: str,
    scene_notes: list[str],
    director_notes: list[str],
) -> GameState:
    return create_initial_game_state(
        plot={
            "chapter_id": chapter_id,
            "scene_id": scene_id,
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
            "selected_template_id": 0,
            "cultivation_goal": cultivation_goal,
            "current_player_realm": current_player_realm,
            "current_chapter_realm": current_chapter_realm,
            "next_chapter_realm": next_chapter_realm,
            "chapter_transition_requirement": build_chapter_transition_requirement(
                current_chapter_realm,
                next_chapter_realm,
            ),
            "completed_chapters": [],
        },
        scene={
            "location_id": location_id,
            "time_tag": time_tag,
            "beat": beat,
            "tension": 0.22,
            "focus_character": PLAYER_CHARACTER_ID,
            "on_stage": [PLAYER_CHARACTER_ID],
            "allow_interrupt": True,
            "suppressed": [],
        },
        characters={
            PLAYER_CHARACTER_ID: create_character_runtime_state(intent=player_intent),
        },
        scene_plan={
            "scene_goal": "",
            "must_happen": [],
            "must_not_happen": [],
            "dramatic_curve": [],
            "character_objectives": {
                PLAYER_CHARACTER_ID: player_objective,
            },
            "exit_condition": "",
            "notes": scene_notes,
        },
        director_brief={
            "beat": "",
            "beat_goal": "",
            "focus_character": PLAYER_CHARACTER_ID,
            "tension_target": 0.22,
            "allow_interrupt": True,
            "who_should_respond": [PLAYER_CHARACTER_ID],
            "lead_in_text": "",
            "wrap_up_text": "",
            "stage_actions": {
                "enter": [],
                "leave": [],
                "suppress": [],
                "unsuppress": [],
            },
            "notes": director_notes,
        },
        player=create_player_state(controlled_character=player_character),
    )

def build_opening_player_context(
    player_profile: dict[str, Any],
    *,
    default_profile_builder: Callable[[], dict[str, Any]] = build_player_profile,
) -> dict[str, str]:
    default_profile = default_profile_builder()
    player_realm = normalize_realm_text(player_profile.get("realm", ""), default_profile["realm"])
    current_realm_stage = normalize_major_realm(player_realm)
    return {
        "name": player_profile["name"],
        "background": player_profile.get("background", ""),
        "realm": player_realm,
        "current_realm_stage": current_realm_stage,
        "next_realm_stage": next_major_realm(current_realm_stage),
        "spiritual_root": player_profile.get("spiritual_root", default_profile["spiritual_root"]),
        "main_technique": player_profile.get("main_technique", default_profile["main_technique"]),
    }


def build_default_state(
    player_character: str | None = None,
    character_profiles: dict[str, dict[str, Any]] | None = None,
) -> GameState:
    profiles = ensure_character_profiles(character_profiles or build_default_character_profiles(), player_character_id=PLAYER_CHARACTER_ID)
    player_profile = profiles[PLAYER_CHARACTER_ID]
    player_context = build_opening_player_context(player_profile)

    return build_opening_state(
        player_character=player_character,
        chapter_id="opening-arc-1",
        scene_id="opening-scene",
        location_id="云峰入门台",
        time_tag="清晨",
        beat="初入仙门",
        cultivation_goal="先在修仙世界立足，摸清自身天赋与可行道路。",
        current_player_realm=player_context["realm"],
        current_chapter_realm=player_context["current_realm_stage"],
        next_chapter_realm=player_context["next_realm_stage"],
        player_intent="先观察环境与他人，再决定是探路、问讯还是开始修炼。",
        player_objective="弄清此地规则、可接触的人物与下一步修行方向。",
        scene_notes=[
            f"玩家角色：{player_context['name']}",
            f"玩家背景：{player_context['background']}",
            f"灵根 / 当前境界 / 主修功法：{player_context['spiritual_root']} / {player_context['realm']} / {player_context['main_technique']}",
            "这一幕重点是让玩家看清环境、获得方向感，并感受到修仙世界的门槛与诱惑。",
        ],
        director_notes=[
            "开场优先给玩家空间观察和自我定位，再逐步引出可交互人物与修行线索。",
        ],
    )


def build_runtime_dependencies(
    *,
    mode: str,
    interactive: bool,
    character_profiles: dict[str, dict[str, Any]],
    scene_config: dict[str, Any] | None,
    default_scene_config_builder: Callable[[], dict[str, Any]],
    component_names: tuple[str, ...] = AGENT_FIRST_COMPONENT_NAMES,
    warm_clients_after_attach: bool = False,
) -> GraphDependencies:
    agent_first = mode in {"agent-first", "live"}
    resolved_scene_config, narration_style_preset = normalize_scene_config(scene_config, default_scene_config_builder=default_scene_config_builder)
    component_factory = ComponentFactory()
    deps = GraphDependencies(
        scene_config=resolved_scene_config,
        character_profiles=character_profiles,
        actor_memory_provider=DefaultActorMemoryProvider(
            character_profiles=character_profiles,
            recent_rounds=3,
            granularity="on_stage",
        ),
        history_manager=HistoryManager(compression_trigger_size=30, summary_horizon_turns=45),
        gameplay_tuning=GameplayTuning(narration=NarrationTuning(style_preset=narration_style_preset)),
        component_factory=component_factory,
        agent_first=agent_first,
        player_interface=ConsolePlayerInterface() if interactive else None,
    )
    if agent_first:
        attach_agent_first_components(
            deps,
            component_factory,
            component_names=component_names,
            warm_clients_after_attach=warm_clients_after_attach,
        )
    if deps.history_manager is not None:
        deps.memory_store = MemoryStore(history_manager=deps.history_manager)
        deps.memory_compactor = AsyncMemoryCompactor(memory_store=deps.memory_store)
        deps.memory_compactor.start()
    register_default_hooks(deps)
    return deps


def build_graph_dependencies(
    mode: str,
    interactive: bool = False,
    character_profiles: dict[str, dict[str, Any]] | None = None,
    scene_config: dict[str, Any] | None = None,
) -> GraphDependencies:
    return build_runtime_dependencies(
        mode=mode,
        interactive=interactive,
        character_profiles=ensure_character_profiles(character_profiles or build_default_character_profiles(), player_character_id=PLAYER_CHARACTER_ID),
        scene_config=scene_config,
        default_scene_config_builder=build_default_scene_config,
        warm_clients_after_attach=True,
    )


def register_default_hooks(deps: GraphDependencies) -> None:
    """Register default hooks that were previously separate subgraph steps.

    - actor.after: history_commit → contextual_progression (order sensitive)
    - narration.after: refresh_history (conditional memory refresh)
    """
    registry = deps.hook_registry

    def _history_commit(state):
        return apply_resolved_act(
            state,
            deps.gameplay_tuning.relationship,
            character_profiles=deps.character_profiles,
        )

    def _contextual_progression(state):
        return apply_contextual_scene_progression(state, deps.character_profiles)

    def _refresh_history(state):
        manager = deps.history_manager
        store = deps.memory_store
        compactor = deps.memory_compactor
        # store 与 compactor 绑定同生死(见 build_runtime_dependencies 同一守卫构造),
        # 三者缺任一即整体降级,避免「有 store 无 compactor → 压缩永不入队」的静默退化。
        if manager is None or store is None or compactor is None:
            return state

        merged_state = state
        # 轮首:join 上一轮后台压缩结果(若有),合并 blocks + 推进游标 + 驱逐已压缩 history。
        pending = compactor.take_pending()
        if pending is not None:
            blocks, new_last = pending
            evicted_history = manager.evict_compressed_history(state["history"], new_last)
            merged_state = {
                **state,
                "history": evicted_history,
                "memory": {
                    **state["memory"],
                    "scene_memory": {
                        **state["memory"]["scene_memory"],
                        "compressed_blocks": blocks,
                    },
                    "last_compressed_turn": new_last,
                },
            }

        # 快路径:从现有 blocks 同步 derive Agent 视图(不做压缩),走 store。
        existing_blocks = merged_state["memory"]["scene_memory"]["compressed_blocks"]
        merged_state = {**merged_state, "memory": store.derive_views(merged_state, existing_blocks)}

        # policy 判定该压缩 → enqueue 快照到后台(非阻塞)。
        decision = decide_refresh(merged_state, trigger_size=manager.compression_trigger_size)
        if decision.should_compress:
            compactor.enqueue(merged_state)

        return merged_state

    registry.register("actor.after", _history_commit)
    registry.register("actor.after", _contextual_progression)
    registry.register("narration.after", _refresh_history)
