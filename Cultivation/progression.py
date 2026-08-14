from __future__ import annotations

from typing import TYPE_CHECKING

from Cultivation.realms import (
    build_chapter_transition_requirement,
    detect_breakthrough_realm,
    has_reached_realm,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
)
from GameState import GameState
from StoryStateUtils import (
    clean_text as _clean_text,
    current_outline_entry,
    resolve_player_character_id,
)

if TYPE_CHECKING:
    # 仅类型引用,运行期不导入 Graph,避免 Graph <-> Cultivation 成环。
    from Graph.dependencies import GraphDependencies


# 判定玩家当前回合是否属于"修炼行为"的中文/英文信号词。
CULTIVATION_SIGNAL_MARKERS = (
    "修炼",
    "打坐",
    "吐纳",
    "运功",
    "调息",
    "闭关",
    "冲关",
    "炼化",
    "灵气",
    "周天",
    "丹药",
    "服下",
    "药力",
)


def _looks_like_cultivation_turn(candidate_text: str) -> bool:
    lowered = candidate_text.lower()
    return any(marker in candidate_text for marker in CULTIVATION_SIGNAL_MARKERS) or any(
        marker in lowered for marker in ("cultivat", "meditat", "breathwork")
    )


def _build_cultivation_result_text(
    state: GameState,
    deps: "GraphDependencies",
    *,
    player_actor: str,
    breakthrough_realm: str = "",
) -> str:
    player_name = str(
        deps.character_profiles.get(player_actor, {}).get("name", "") or player_actor
    ).strip()
    latest_input = " ".join(
        [
            str(state["player"].get("last_input", "") or "").strip(),
            str((state["runtime"].get("resolved_act") or {}).get("content", "") or "").strip(),
        ]
    )
    used_pill = any(marker in latest_input for marker in ("丹", "药", "药力"))
    if breakthrough_realm:
        return (
            f"{player_name}在洞府中运转周天，"
            f"体内灵息终于由散而聚，"
            f"一举踏入{breakthrough_realm}。"
        )
    if used_pill:
        return (
            f"{player_name}盘坐调息之间，"
            "药力沿经脉缓缓化开，"
            "气息比先前更凝练了几分，"
            "只是距破境还差最后一线水磨功夫。"
        )
    return (
        f"{player_name}收敛心神，在洞府中缓缓吐纳，"
        "体内灵息虽未立刻破关，"
        "却已在一次次循环之间渐渐稳固。"
    )


def _sync_plot_cultivation_state(state: GameState, deps: "GraphDependencies") -> GameState:
    player_actor = resolve_player_character_id(state, deps.character_profiles)
    player_profile = deps.character_profiles.get(player_actor, {})
    current_player_realm = normalize_realm_text(player_profile.get("realm", ""), "炼气一层")
    current_outline = current_outline_entry(state) or {}
    current_chapter_realm = _clean_text(
        current_outline.get("realm_stage"),
    ) or _clean_text(state["plot"].get("current_chapter_realm", "")) or normalize_major_realm(
        current_player_realm
    )
    next_chapter_realm = _clean_text(
        current_outline.get("next_realm"),
    ) or _clean_text(state["plot"].get("next_chapter_realm", "")) or next_major_realm(
        current_chapter_realm
    )
    next_plot = {
        **state["plot"],
        "cultivation_goal": str(state["plot"].get("cultivation_goal", "") or "").strip() or "修仙求长生",
        "current_player_realm": current_player_realm,
        "current_chapter_realm": current_chapter_realm,
        "next_chapter_realm": next_chapter_realm,
        "chapter_transition_requirement": build_chapter_transition_requirement(
            current_chapter_realm,
            next_chapter_realm,
        ),
    }
    return {
        **state,
        "plot": next_plot,
    }


def cultivation_progress_node(state: GameState, deps: "GraphDependencies") -> GameState:
    # 惰性导入旁白追加器:避免 Cultivation 顶层依赖 Graph 造成环。
    from Graph.narration_nodes import _append_narration_event

    state = _sync_plot_cultivation_state(state, deps)
    resolved_act = state["runtime"].get("resolved_act") or {}
    if not resolved_act:
        return state

    player_actor = resolve_player_character_id(state, deps.character_profiles)
    if str(resolved_act.get("actor", "") or "").strip() != player_actor:
        return state

    target_realm = _clean_text(state["plot"].get("next_chapter_realm", ""))
    if not target_realm:
        return state

    candidate_text = " ".join(
        [
            str(resolved_act.get("content", "") or "").strip(),
            str(state["player"].get("last_input", "") or "").strip(),
        ]
    ).strip()
    cultivation_signal = _looks_like_cultivation_turn(candidate_text)
    breakthrough_realm = detect_breakthrough_realm(candidate_text, [target_realm])
    if breakthrough_realm is not None:
        current_realm = deps.character_profiles.get(player_actor, {}).get("realm", "")
        if not has_reached_realm(current_realm, breakthrough_realm):
            deps.character_profiles.update_field(
                player_actor, "realm", breakthrough_realm
            )
            chapter_id = _clean_text(state["plot"].get("chapter_id", ""))
            plot_flags = dict(state["plot"].get("plot_flags", {}))
            if chapter_id:
                plot_flags[f"{chapter_id}_breakthrough"] = breakthrough_realm

            next_state = {
                **state,
                "plot": {
                    **state["plot"],
                    "plot_flags": plot_flags,
                },
            }
            synced_state = _sync_plot_cultivation_state(next_state, deps)
            return _append_narration_event(
                state=synced_state,
                content=_build_cultivation_result_text(
                    synced_state,
                    deps,
                    player_actor=player_actor,
                    breakthrough_realm=breakthrough_realm,
                ),
                source="cultivation_progress",
                style_preset=str(deps.gameplay_tuning.narration.style_preset or "xianxia_default").strip(),
            )

    if not cultivation_signal:
        return state

    return _append_narration_event(
        state=state,
        content=_build_cultivation_result_text(
            state,
            deps,
            player_actor=player_actor,
        ),
        source="cultivation_progress",
        style_preset=str(deps.gameplay_tuning.narration.style_preset or "xianxia_default").strip(),
    )
