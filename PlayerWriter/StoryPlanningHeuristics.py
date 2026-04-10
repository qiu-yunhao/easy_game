from __future__ import annotations

import re
from typing import Any

from CharacterProfile import CharacterProfile
from StoryStateUtils import (
    clean_str_list,
    clean_text,
    current_outline_entry,
    resolve_player_profile,
    story_outline_entries,
)
from Cultivation import (
    build_chapter_transition_requirement,
    chapter_realm_sequence,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
)
from GameState import ChapterOutline, GameState, SceneCandidate
from SceneConfig import SceneConfig


_clean_text = clean_text
_clean_label_list = clean_str_list
_resolve_player_profile = resolve_player_profile


def _realm_chapter_title(realm_stage: str) -> str:
    return f"{realm_stage}篇"


def _realm_chapter_goal(realm_stage: str, next_realm: str) -> str:
    if realm_stage == next_realm:
        return f"在{realm_stage}阶段继续拓宽修行路，寻找更接近长生的积累与答案。"
    return f"围绕{realm_stage}阶段的修行困局、资源与机缘展开探索，为迈入{next_realm}做足准备。"


def _realm_chapter_summary(player_name: str, realm_stage: str, next_realm: str) -> str:
    if realm_stage == next_realm:
        return f"{player_name}已经站在更高层次的修行门槛前，本章将继续把视野推向更远的天地与更久的寿命。"
    return (
        f"{player_name}在{realm_stage}阶段不设唯一主线，只围绕求长生这一目标自由探索。"
        f"宗门、坊市、秘境、古修遗府与人情势力都可能成为通往{next_realm}的路。"
    )


def _build_outline_brief(
    chapter_id_prefix: str,
    start_number: int,
    desired_chapter_count: int,
    player_name: str,
    starting_realm: str,
) -> list[ChapterOutline]:
    outline: list[ChapterOutline] = []
    for offset, (realm_stage, next_realm) in enumerate(
        chapter_realm_sequence(starting_realm, desired_chapter_count)
    ):
        chapter_number = start_number + offset
        outline.append(
            {
                "chapter_id": f"{chapter_id_prefix}-{chapter_number}",
                "title": _realm_chapter_title(realm_stage),
                "main_goal": _realm_chapter_goal(realm_stage, next_realm),
                "summary": _realm_chapter_summary(player_name, realm_stage, next_realm),
                "exploration_hooks": [],
                "key_locations": [],
                "realm_stage": realm_stage,
                "next_realm": next_realm,
            }
        )
    return outline


def _resolve_outline_generation_start(
    state: GameState,
    player_realm: str,
) -> tuple[str, int, str]:
    story_outline = story_outline_entries(state)
    if story_outline:
        last_chapter = story_outline[-1]
        last_chapter_id = _clean_text(last_chapter.get("chapter_id"))
        next_offset = 1
        starting_realm = _clean_text(last_chapter.get("next_realm")) or next_major_realm(
            _clean_text(last_chapter.get("realm_stage"), normalize_major_realm(player_realm))
        )
    else:
        last_chapter_id = _clean_text(state["plot"].get("chapter_id"), "longevity-road-1")
        next_offset = 0
        starting_realm = normalize_major_realm(player_realm)

    match = re.match(r"^(.*?)-(\d+)$", last_chapter_id)
    if match:
        return match.group(1), int(match.group(2)) + next_offset, starting_realm
    return last_chapter_id or "longevity-road", 1, starting_realm


def build_heuristic_story_premise(
    state: GameState,
    scene_config: SceneConfig,
    character_profiles: dict[str, CharacterProfile],
) -> dict[str, str]:
    _, player_profile = _resolve_player_profile(state, character_profiles)
    player_name = _clean_text(player_profile.get("name"), "无名修士")
    race = _clean_text(player_profile.get("race"), "人族")
    background = _clean_text(player_profile.get("background"), "出身寻常微末")
    spiritual_root = _clean_text(player_profile.get("spiritual_root"), "杂灵根")
    realm = normalize_realm_text(player_profile.get("realm"), "炼气初期")
    location_id = _clean_text(
        scene_config.get("default_location_id"),
        state["scene"].get("location_id", "云水古道"),
    )

    story_premise = (
        f"{player_name}身负{race}之身，以“{background}”的来路踏入修仙世界，如今停在{realm}。"
        f"故事从{location_id}开始，但没有唯一要追的旧案，也没有固定要破解的真相；"
        f"只有一个稳定的目标: 继续修行，寻觅更长的寿数、更高的境界，与真正可行的长生之路。"
        f"{spiritual_root}只是起点，不是命运的全部。"
    )
    exploration_drive = (
        "每一章都对应一个大境界。玩家可以通过宗门修行、坊市求财、秘境夺机缘、结交同道、"
        "参悟功法、炼丹炼器、游历山河等任何方式推动修为增长；只要能向下一个大境界迈进，就是有效推进。"
    )
    return {
        "story_premise": story_premise,
        "exploration_drive": exploration_drive,
    }


def build_heuristic_story_outline_brief(
    state: GameState,
    scene_config: SceneConfig,
    character_profiles: dict[str, CharacterProfile],
    desired_chapter_count: int = 3,
) -> list[ChapterOutline]:
    _, player_profile = _resolve_player_profile(state, character_profiles)
    player_name = _clean_text(player_profile.get("name"), "无名修士")
    player_realm = normalize_realm_text(player_profile.get("realm"), "炼气初期")
    chapter_id_prefix, start_number, starting_realm = _resolve_outline_generation_start(
        state,
        player_realm,
    )
    return _build_outline_brief(
        chapter_id_prefix=chapter_id_prefix,
        start_number=start_number,
        desired_chapter_count=desired_chapter_count,
        player_name=player_name,
        starting_realm=starting_realm,
    )


def build_heuristic_chapter_expansion(
    state: GameState,
    scene_config: SceneConfig,
    character_profiles: dict[str, CharacterProfile],
) -> dict[str, Any]:
    _, player_profile = _resolve_player_profile(state, character_profiles)
    story_outline = story_outline_entries(state)
    current = current_outline_entry(state) or (
        story_outline[0] if story_outline else None
    )

    realm_stage = _clean_text((current or {}).get("realm_stage"), state["plot"].get("current_chapter_realm", "炼气"))
    next_realm = _clean_text((current or {}).get("next_realm"), state["plot"].get("next_chapter_realm", next_major_realm(realm_stage)))
    title = _clean_text((current or {}).get("title"), _realm_chapter_title(realm_stage))
    goal = _clean_text((current or {}).get("main_goal"), _realm_chapter_goal(realm_stage, next_realm))
    summary = _clean_text((current or {}).get("summary"), _realm_chapter_summary(_clean_text(player_profile.get("name"), "无名修士"), realm_stage, next_realm))

    locations_map = {
        "炼气": ["云水古道", "山脚坊市", "溪谷灵田"],
        "筑基": ["外海小岛", "古修洞府", "宗门藏经阁"],
        "金丹": ["裂空遗府", "北荒大城", "地火丹室"],
        "元婴": ["星陨秘境", "万里海眼", "古战场边缘"],
        "化神": ["天外碎界", "万象道台", "上古宗门残址"],
    }
    hooks_map = {
        "炼气": ["确定主修方向", "积累突破资源", "接触第一批同道或势力"],
        "筑基": ["稳固道基", "筛选真正值得深交的传承或伙伴", "寻找跨境界机缘"],
        "金丹": ["确认本命道路", "处理资源与势力的交换代价", "为更高境界准备护道手段"],
        "元婴": ["扩张视野到更大的天地", "处理因名声与因果带来的压力", "寻找承载更高境界的道法"],
        "化神": ["辨明道统与自我之别", "对抗更高层次的天命约束", "为继续长生之路奠定新秩序"],
    }

    locations = _clean_label_list(
        locations_map.get(
            realm_stage,
            [scene_config.get("default_location_id", "云水古道"), "远行城镇", "无名遗迹"],
        )
    )
    hooks = _clean_label_list(
        hooks_map.get(
            realm_stage,
            ["寻找适合自己的修行法门", "积累通往下一境界的条件", "在开放世界里验证自己的选择"],
        )
    )

    overview = (
        f"{summary} 本章的核心不是追逐单一主线，而是在{realm_stage}阶段的广阔天地里，"
        f"通过自由探索、修炼、结交、交易、历练与悟道，为迈入{next_realm}积累足够的条件。"
    )
    transition_requirement = build_chapter_transition_requirement(realm_stage, next_realm)

    return {
        "chapter_title": title,
        "chapter_goal": goal,
        "chapter_overview": overview,
        "exploration_hooks": [*hooks, transition_requirement],
        "key_locations": locations,
    }


def build_heuristic_scene_candidates(
    state: GameState,
    scene_config: SceneConfig,
    character_profiles: dict[str, CharacterProfile],
) -> list[SceneCandidate]:
    player_id, player_profile = _resolve_player_profile(state, character_profiles)
    player_name = _clean_text(player_profile.get("name"), player_id or "修士")
    chapter_goal = _clean_text(state["plot"].get("chapter_goal"), "继续推进当前境界的修行")
    chapter_title = _clean_text(state["plot"].get("current_chapter_title"), "当前章节")
    chapter_realm = _clean_text(state["plot"].get("current_chapter_realm"), normalize_major_realm(player_profile.get("realm", "")))
    next_realm = _clean_text(state["plot"].get("next_chapter_realm"), next_major_realm(chapter_realm))
    current_location = _clean_text(
        state["scene"].get("location_id"),
        scene_config.get("default_location_id", "未知地点"),
    )
    key_locations = _clean_label_list(
        [
            *list(
                next(
                    (
                        chapter.get("key_locations", [])
                        for chapter in state["plot"].get("story_outline", [])
                        if _clean_text(chapter.get("chapter_id")) == _clean_text(state["plot"].get("chapter_id"))
                    ),
                    [],
                )
            ),
            current_location,
        ]
    )
    exploration_location = key_locations[0] if key_locations else current_location
    practice_location = key_locations[1] if len(key_locations) > 1 else exploration_location
    exchange_location = key_locations[2] if len(key_locations) > 2 else practice_location
    on_stage = list(state["scene"].get("on_stage", []))

    return [
        {
            "candidate_id": "survey-opportunity",
            "label": f"{chapter_title} · 探路",
            "location_id": exploration_location,
            "beat": "勘察眼前可走的修行方向",
            "scene_goal": f"在{chapter_realm}阶段先看清可行的资源、情报、人物或地脉，把{chapter_goal}落到实际方向上。",
            "must_happen": [],
            "must_not_happen": ["提前锁死唯一主线", "把所有机会都写成同一路径"],
            "dramatic_curve": ["观察", "比较", "定向"],
            "character_objectives": {
                cid: ("判断这条路是否值得继续走下去" if cid == player_id else "回应玩家当前的试探")
                for cid in on_stage
            },
            "exit_condition": "玩家已经明确下一步最想追逐的修行方向、地点或机缘类型。",
            "notes": [
                f"{player_name}的总目标始终是修仙求长生，而不是被单一剧情牵着走。",
                f"这一幕只需要把通往{next_realm}的某个方向照亮。",
            ],
        },
        {
            "candidate_id": "practice-and-prepare",
            "label": f"{chapter_title} · 修炼",
            "location_id": practice_location,
            "beat": "把见闻转化为修行积累",
            "scene_goal": f"通过修炼、参悟、炼丹、炼器或闭关准备，推动{chapter_realm}阶段向{next_realm}靠近。",
            "must_happen": [],
            "must_not_happen": ["一幕之内直接替代整章突破", "把修炼写成毫无选择的流水账"],
            "dramatic_curve": ["准备", "尝试", "见到边界"],
            "character_objectives": {
                cid: ("验证当前修行方向是否真能带来突破" if cid == player_id else "对玩家造成助力或扰动")
                for cid in on_stage
            },
            "exit_condition": "玩家确认当前修炼法、资源或悟道方向值得继续投入。",
            "notes": [
                "允许静态修行与行动探索并存。",
                "重点是让玩家感到自己确实在朝下一境界累积。",
            ],
        },
        {
            "candidate_id": "exchange-with-world",
            "label": f"{chapter_title} · 交游",
            "location_id": exchange_location,
            "beat": "通过人与势力拓宽路子",
            "scene_goal": f"在外部世界中换来推进{next_realm}所需的消息、资源、人脉或承诺。",
            "must_happen": [],
            "must_not_happen": ["强制绑定唯一阵营", "让所有人都只服务于单一主线"],
            "dramatic_curve": ["接触", "权衡", "留下后手"],
            "character_objectives": {
                cid: ("试探谁值得结交、交易或保持距离" if cid == player_id else "给出自己的条件与态度")
                for cid in on_stage
            },
            "exit_condition": "玩家获得了一个值得继续追下去的人、势力、地点或资源渠道。",
            "notes": [
                "世界应表现为开放网络，而不是一条线。",
                f"只要这条路有助于迈向{next_realm}，它就算有效推进。",
            ],
        },
    ]
