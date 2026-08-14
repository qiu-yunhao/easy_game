from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from CharacterProfile import CharacterProfile, ensure_character_profile
from CharacterRepository import CharacterRepository
from GameState import GameState, SceneCandidate
from ScenePlan import ScenePlan
from StoryStateUtils import clean_text as _clean_text

if TYPE_CHECKING:
    from Actor.ActorCreateAgent import ActorCreateAgent
    from SceneConfig import SceneConfig


TRAVEL_MARKERS = (
    "前往",
    "赶往",
    "去往",
    "前去",
    "赶去",
    "来到",
    "走向",
    "回到",
    "返回",
    "返回到",
    "折返",
    "归向",
)
DIRECT_CUT_MARKERS = (
    "直接切换",
    "直接切到",
    "直接换景",
    "直接前往",
    "直接过去",
    "直接到",
    "跳到",
    "跳转到",
    "略过路程",
    "不用过渡",
)
OBJECTIVE_MARKERS = (
    "领取",
    "拿取",
    "取走",
    "获得",
    "得到",
    "收下",
    "借取",
    "拜见",
    "求见",
    "寻找",
    "查看",
    "调查",
    "进入",
    "修炼",
    "闭关",
)
REWARD_MARKERS = ("领取", "拿取", "取走", "获得", "得到", "收下", "拿到")
HANDOVER_MARKERS = ("递来", "交给", "奉上", "递上", "送来", "发下", "放到", "收下")
PHRASE_BOUNDARIES = "，。！？,.!?;；:：\n\t "


class ContextualSceneCue(TypedDict):
    destination: str
    objective: str
    reward_item: str
    player_intent: str
    skip_transition_intro: bool


class ContextualSceneHandoff(TypedDict):
    next_location: str
    next_focus: str | None
    next_tension: float
    default_on_stage: list[str]
    scene_candidate: SceneCandidate
    scene_plan: ScenePlan
    supplemental_profiles: dict[str, CharacterProfile]
    skip_transition_intro: bool


def _first_non_empty(*values: object) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _normalize_phrase(value: object) -> str:
    cleaned = _clean_text(value).strip("，。！？,.!?;；:： ")
    for prefix in ("一个", "一名", "一位", "一部", "一本", "一卷"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned


def _take_first_phrase(value: str, *, stop_markers: tuple[str, ...] = ()) -> str:
    phrase = _normalize_phrase(value)
    stop_indexes = [len(phrase)]
    for index, char in enumerate(phrase):
        if char in PHRASE_BOUNDARIES:
            stop_indexes.append(index)
            break
    for marker in stop_markers:
        position = phrase.find(marker)
        if position > 0:
            stop_indexes.append(position)
    return phrase[: min(stop_indexes)].strip()


def _looks_like_travel_intent(text: str, resolved_act: dict[str, object]) -> bool:
    if str(resolved_act.get("mode", "") or "").strip() == "move":
        return True
    return any(marker in text for marker in TRAVEL_MARKERS)


def _wants_direct_cut(text: str) -> bool:
    return any(marker in text for marker in DIRECT_CUT_MARKERS)


def _extract_destination(text: str) -> str:
    cleaned = _clean_text(text)
    for marker in TRAVEL_MARKERS:
        if marker not in cleaned:
            continue
        destination = _take_first_phrase(
            cleaned.split(marker, 1)[1],
            stop_markers=OBJECTIVE_MARKERS,
        )
        if destination:
            return destination
    return ""


def _extract_objective(text: str) -> str:
    cleaned = _clean_text(text)
    for marker in OBJECTIVE_MARKERS:
        if marker not in cleaned:
            continue
        objective_tail = _take_first_phrase(cleaned.split(marker, 1)[1])
        return f"{marker}{objective_tail}".strip() if objective_tail else marker

    for boundary in ("，", ",", "。", ".", "；", ";"):
        if boundary not in cleaned:
            continue
        tail = _normalize_phrase(cleaned.split(boundary, 1)[1])
        if tail:
            return tail
    return ""


def _extract_reward_item(text: str) -> str:
    cleaned = _clean_text(text)
    for marker in REWARD_MARKERS:
        if marker not in cleaned:
            continue
        reward_item = _take_first_phrase(cleaned.split(marker, 1)[1])
        if reward_item:
            return reward_item
    return ""


def _resolve_player_name(
    player_id: str,
    character_profiles: dict[str, CharacterProfile],
) -> str:
    return _clean_text(character_profiles.get(player_id, {}).get("name", ""), player_id)


def _build_scene_plan(
    *,
    cue: ContextualSceneCue,
    player_id: str,
    player_name: str,
) -> ScenePlan:
    destination = cue["destination"]
    objective = cue["objective"] or f"观察{destination}的环境变化"
    reward_item = cue["reward_item"]
    must_happen = [objective] if objective else []
    exit_condition = (
        f"{player_name}在{destination}完成“{objective}”后，当前场景便可自然收束。"
        if objective
        else f"{player_name}在{destination}确认周遭情况后，当前场景便可自然收束。"
    )
    notes = [
        f"环境切换至{destination}后，先用场景与感官描写承接，不要生硬跳切。",
        "若导演未明确调度新角色，场景可以暂时只有玩家一人。",
        "若后续确有剧情需要，再由导演决定是否安排角色登场或推动新的互动。",
    ]
    if reward_item:
        notes.append(f"若玩家主动完成“{objective}”，应允许将{reward_item}写入背包。")

    return {
        "scene_goal": f"{player_name}抵达{destination}，并设法完成“{objective}”。",
        "must_happen": must_happen,
        "must_not_happen": ["无预兆硬切到下一幕", "未被导演调度时强行安排陌生角色登场"],
        "dramatic_curve": ["余波未散", "转入新境", "等待下一拍触发"],
        "character_objectives": {
            player_id: objective,
        },
        "exit_condition": exit_condition,
        "notes": notes,
    }


def _build_scene_candidate(
    *,
    cue: ContextualSceneCue,
    scene_plan: ScenePlan,
    scene_index: int,
) -> SceneCandidate:
    objective = cue["objective"] or f"观察{cue['destination']}的环境变化"
    return {
        "candidate_id": f"contextual-scene-{scene_index + 1}",
        "label": f"{cue['destination']}场景过渡",
        "location_id": cue["destination"],
        "beat": f"{cue['destination']}的环境转换与落脚观察",
        "scene_goal": scene_plan["scene_goal"],
        "must_happen": list(scene_plan["must_happen"]),
        "must_not_happen": list(scene_plan["must_not_happen"]),
        "dramatic_curve": list(scene_plan["dramatic_curve"]),
        "character_objectives": dict(scene_plan["character_objectives"]),
        "exit_condition": scene_plan["exit_condition"],
        "notes": [*scene_plan["notes"], f"当前落点目标：{objective}。"],
    }


def _looks_like_reward_claim_turn(state: GameState, reward_item: str) -> bool:
    resolved_act = state["runtime"].get("resolved_act") or {}
    turn_text = " ".join(
        _clean_text(resolved_act.get(field, ""))
        for field in ("content", "spoken_text", "nonverbal_action")
        if _clean_text(resolved_act.get(field, ""))
    ).strip()
    if not turn_text or reward_item not in turn_text:
        return False
    return any(marker in turn_text for marker in (*REWARD_MARKERS, *HANDOVER_MARKERS))


def detect_contextual_scene_cue(state: GameState) -> ContextualSceneCue | None:
    resolved_act = state["runtime"].get("resolved_act") or {}
    player_id = str(state["player"].get("controlled_character", "") or "").strip()
    if not player_id or str(resolved_act.get("actor", "") or "").strip() != player_id:
        return None

    primary_intent = _first_non_empty(
        state["player"].get("last_input", ""),
        resolved_act.get("next_intent", ""),
        resolved_act.get("content", ""),
        resolved_act.get("nonverbal_action", ""),
    )
    if not primary_intent or not _looks_like_travel_intent(primary_intent, resolved_act):
        return None

    destination = _extract_destination(primary_intent)
    if not destination:
        return None

    current_location = _clean_text(state["scene"].get("location_id", ""))
    if current_location == destination:
        return None

    objective = _extract_objective(primary_intent)
    reward_item = _extract_reward_item(objective or primary_intent)
    return {
        "destination": destination,
        "objective": objective,
        "reward_item": reward_item,
        "player_intent": primary_intent,
        "skip_transition_intro": _wants_direct_cut(primary_intent),
    }


def build_contextual_scene_handoff(
    state: GameState,
    *,
    scene_config: "SceneConfig",
    character_profiles: dict[str, CharacterProfile],
    actor_create_agent: "ActorCreateAgent | None",
) -> ContextualSceneHandoff | None:
    del scene_config, actor_create_agent
    cue = detect_contextual_scene_cue(state)
    if cue is None:
        return None

    player_id = str(state["player"].get("controlled_character", "") or "").strip()
    player_name = _resolve_player_name(player_id, character_profiles)
    scene_plan = _build_scene_plan(
        cue=cue,
        player_id=player_id,
        player_name=player_name,
    )
    scene_candidate = _build_scene_candidate(
        cue=cue,
        scene_plan=scene_plan,
        scene_index=int(state["plot"].get("current_scene_index", 0) or 0) + 1,
    )
    return {
        "next_location": cue["destination"],
        "next_focus": player_id or None,
        "next_tension": 0.34,
        "default_on_stage": [player_id] if player_id else [],
        "scene_candidate": scene_candidate,
        "scene_plan": scene_plan,
        "supplemental_profiles": {},
        "skip_transition_intro": cue["skip_transition_intro"],
    }


def _resolve_reward_item_from_turn(state: GameState) -> str:
    resolved_act = state["runtime"].get("resolved_act") or {}
    for flag in resolved_act.get("triggered_plot_flags", {}):
        reward_item = _extract_reward_item(flag)
        if reward_item:
            return reward_item

    for planned_item in state["scene_plan"].get("must_happen", []):
        reward_item = _extract_reward_item(planned_item)
        if reward_item and _looks_like_reward_claim_turn(state, reward_item):
            return reward_item
    return ""


def _grant_item_to_backpack(
    character_profiles: CharacterRepository,
    *,
    player_id: str,
    item_name: str,
) -> None:
    existing_profile = character_profiles.get(player_id, {})
    normalized_profile = ensure_character_profile(
        existing_profile,
        character_id=player_id,
        include_backpack=True,
    )
    backpack = list(normalized_profile.get("backpack", []))
    for item in backpack:
        if _clean_text(item.get("name", "")) == item_name or _clean_text(item.get("id", "")) == item_name:
            character_profiles.set_profile(player_id, normalized_profile)
            return

    backpack.append(
        {
            "id": item_name,
            "name": item_name,
            "quantity": 1,
        }
    )
    normalized_profile["backpack"] = backpack
    character_profiles.set_profile(player_id, normalized_profile)


def apply_contextual_scene_progression(
    state: GameState,
    character_profiles: CharacterRepository,
) -> GameState:
    resolved_act = state["runtime"].get("resolved_act")
    if resolved_act is None:
        return state

    next_state = state
    if detect_contextual_scene_cue(state) is not None and not bool(resolved_act.get("should_end_scene", False)):
        next_state = {
            **state,
            "runtime": {
                **state["runtime"],
                "resolved_act": {
                    **resolved_act,
                    "should_end_scene": True,
                },
            },
        }

    reward_item = _resolve_reward_item_from_turn(next_state)
    player_id = str(next_state["player"].get("controlled_character", "") or "").strip()
    if reward_item and player_id:
        _grant_item_to_backpack(
            character_profiles,
            player_id=player_id,
            item_name=reward_item,
        )
    return next_state
