from __future__ import annotations

import re

from CharacterProfile import CharacterProfile
from GameState import GameState


POLLUTED_SNIPPET_MARKERS = (
    "Heuristic scene-end",
    "response_pressure",
    "must_happen",
    "recent_history",
    "director_brief",
)
POLLUTED_TURN_PATTERN = re.compile(
    r"\b\d+:[A-Za-z_][A-Za-z0-9_]*:(?:speak|action|event|interrupt|silence|observe)\b"
)


def _clean_clause(value: str | None) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if POLLUTED_TURN_PATTERN.search(text):
        return ""
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in POLLUTED_SNIPPET_MARKERS):
        return ""
    if "{" in text or "}" in text:
        return ""
    return text


def _strip_sentence_end(value: str) -> str:
    return value.rstrip("。！？!?；;，,、\"'“”")


def _join_sentences(parts: list[str]) -> str:
    sentences = [_strip_sentence_end(_clean_clause(part)) for part in parts if _clean_clause(part)]
    return "。".join(sentences) + ("。" if sentences else "")


def _needs_transition_afterglow(state: GameState) -> bool:
    scene_memory = state.get("memory", {}).get("scene_memory", {})
    if str(scene_memory.get("tension_trend", "") or "").strip() in {"rising", "high"}:
        return True
    return bool(scene_memory.get("active_conflicts", []))


def build_fallback_narrated_text(
    *,
    actor_name: str,
    speech: str = "",
    action: str = "",
    target_name: str = "",
    connective: str = "",
) -> str:
    subject = _clean_clause(actor_name) or "某人"
    speech_text = _clean_clause(speech)
    action_text = _strip_sentence_end(_clean_clause(action))
    addressee = _clean_clause(target_name)
    scene_prefix = _clean_clause(connective)

    if not action_text:
        action_text = "敛住气息，静静观察四周"

    if addressee and addressee not in action_text:
        action_text = f"朝着{addressee}{action_text}"

    prefix = f"{scene_prefix}，" if scene_prefix else ""
    if speech_text:
        return f"{prefix}{subject}{action_text}，开口道：“{speech_text}”"
    return f"{prefix}{subject}{action_text}。"


def build_fallback_intro_text(
    *,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
    intro_kind: str,
    style_preset: str,
) -> str:
    del style_preset  # Fallback stays in a stable xianxia register.

    player_id = str(state["player"].get("controlled_character", "") or "").strip()
    player_profile = character_profiles.get(player_id, {})
    player_name = _clean_clause(str(player_profile.get("name", "") or player_id)) or "那名修士"
    player_background = _clean_clause(str(player_profile.get("background", "") or ""))
    location = _clean_clause(str(state["scene"].get("location_id", "") or "")) or "陌生地界"
    story_premise = _clean_clause(str(state["plot"].get("story_premise", "") or ""))
    exploration_drive = _clean_clause(str(state["plot"].get("exploration_drive", "") or ""))
    chapter_title = _clean_clause(str(state["plot"].get("current_chapter_title", "") or ""))
    chapter_goal = _clean_clause(str(state["plot"].get("chapter_goal", "") or ""))
    chapter_overview = _clean_clause(str(state["plot"].get("current_chapter_overview", "") or ""))
    current_chapter_id = _clean_clause(str(state["plot"].get("chapter_id", "") or ""))
    last_chapter_summary = _clean_clause(
        str((state["plot"].get("completed_chapters", []) or [{}])[-1].get("summary", "") or "")
    )
    lingering_clause = (
        f"上一场冲突留下的余压尚未散尽，{player_name}已循着新的气机来到{location}"
        if _needs_transition_afterglow(state)
        else ""
    )

    relevant_roles: list[str] = []
    relevant_ids: list[str] = []
    for actor_id in state["scene"].get("on_stage", []):
        resolved_id = _clean_clause(str(actor_id))
        if not resolved_id or resolved_id == player_id or resolved_id in relevant_ids:
            continue
        relevant_ids.append(resolved_id)

    for actor_id, profile in character_profiles.items():
        if actor_id == player_id or actor_id in relevant_ids:
            continue
        planned_chapter_ids = [
            _clean_clause(str(item))
            for item in profile.get("planned_chapter_ids", [])
            if _clean_clause(str(item))
        ]
        if current_chapter_id and current_chapter_id in planned_chapter_ids:
            relevant_ids.append(actor_id)

    for actor_id in relevant_ids[:3]:
        profile = character_profiles.get(actor_id, {})
        name = _clean_clause(str(profile.get("name", "") or actor_id))
        role = _clean_clause(
            str(profile.get("story_role", "") or profile.get("introduction_hint", "") or profile.get("background", ""))
        )
        relevant_roles.append(f"{name}{'，' + role if role else ''}")

    cast_sentence = ""
    if relevant_roles:
        cast_sentence = "此间与他相关的人物，也已渐渐浮出水面：" + "；".join(relevant_roles[:2])

    if intro_kind == "chapter":
        return _join_sentences(
            [
                lingering_clause or f"上一段风波余意未散，{player_name}已循着新的气机来到{location}",
                last_chapter_summary and f"前章留下的余波仍在：{last_chapter_summary}",
                cast_sentence
                or f"此章《{chapter_title or '新章'}》将起，前路牵动的仍是{chapter_goal or chapter_overview or '未定的机缘与冲突'}",
                chapter_overview or chapter_goal or exploration_drive or "新的机缘已在前方铺开",
            ]
        )

    background_clause = player_background or "带着尚未明朗的前缘与心愿"
    return _join_sentences(
        [
            lingering_clause or f"{location}云气未散，{player_name}{background_clause}",
            cast_sentence or story_premise or "仙途广阔，人事与机缘都还在暗处起伏",
            chapter_goal or chapter_overview or exploration_drive or "他眼下能做的，便是先踏出自己的第一步",
        ]
    )
