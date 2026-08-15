from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from Graph.beat_subgraph import is_player_turn
from Graph.builder import prepare_chapter_turn, resolve_story_turn

if TYPE_CHECKING:
    from Graph.dependencies import GraphDependencies
    from GameState import GameState

# StopCondition:给定当前 state,判断是否该停下把控制权交出去。
StopCondition = Callable[[dict[str, Any]], bool]


def stop_at_player_turn(state: dict[str, Any]) -> bool:
    # Web 用:推进到玩家回合就停,把控制权交回给玩家。
    return is_player_turn(state)


def never_stop(state: dict[str, Any]) -> bool:
    # 自动写小说用:永不主动停,只靠 scene_finished 自然终止(见 advance 循环)。
    return False


class ConversationController:
    """mode-agnostic 会话推进控制器。

    无状态:持 deps 只读引用,state 每次传入、返回新的,
    让 Web 与将来的自动入口各自管理 state 生命周期。
    """

    def __init__(self, deps: "GraphDependencies") -> None:
        self._deps = deps

    def prime_opening_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        # 开场把首回合交给玩家;无 player_actor(自动模式)时 next_act=None,自然退化。
        player_actor = str(state["player"].get("controlled_character", "") or "").strip()
        suppressed = {
            str(actor_id).strip()
            for actor_id in state["scene"].get("suppressed", [])
            if str(actor_id).strip()
        }
        eligible_actors = [
            str(actor_id).strip()
            for actor_id in state["scene"].get("on_stage", [])
            if str(actor_id).strip() and str(actor_id).strip() not in suppressed
        ]
        if player_actor and player_actor not in eligible_actors:
            eligible_actors.insert(0, player_actor)
        target = str(state["scene"].get("focus_character", "") or "").strip()
        if target == player_actor:
            target = ""
        if not target:
            target = next((actor_id for actor_id in eligible_actors if actor_id != player_actor), "")
        next_act = (
            {
                "actor": player_actor,
                "mode": "speak",
                "target": target or None,
                "motivation": "开场先交给玩家，让玩家定义第一步，再进入导演调度。",
                "content": "",
            }
            if player_actor
            else None
        )
        return {
            **state,
            "runtime": {
                **state["runtime"],
                "eligible_actors": eligible_actors,
                "pending_beat_actors": [],
                "beat_fallback_turns_remaining": 0,
                "narration_queue": [],
                "next_act": next_act,
                "resolved_act": None,
                "scene_end_evaluation": None,
            },
        }

    def advance(
        self,
        state: dict[str, Any],
        *,
        stop_when: StopCondition,
        max_hops: int = 24,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> tuple[dict[str, Any], str]:
        # 唯一一份推进循环。stop_when 决定何时停下交接:
        # Web 传 stop_at_player_turn,自动模式传 never_stop。
        # 注意:never_stop 下 max_hops 是硬安全上限——若场景 NPC 回合可能超 max_hops,
        # 自动入口须传更大的 max_hops。
        hops = 0
        npc_acted = False
        while hops < max_hops:
            hops += 1
            # _ensure_prepared_turn 内联:next_act 为空则补一个回合。
            if not state["runtime"].get("scene_finished", False) and state["runtime"].get("next_act") is None:
                state = prepare_chapter_turn(state, self._deps)
            if state["runtime"].get("scene_finished", False):
                reason = state["runtime"].get("scene_end_evaluation", {}).get("reason", "")
                return state, (reason or "当前场景已经结束。")
            next_act = state["runtime"].get("next_act")
            if next_act is None:
                return state, "当前没有新的自动后续动作。"
            if stop_when(state):
                if npc_acted:
                    return state, "场景角色动作已结算，等待玩家回应。"
                eligible = [
                    actor_id
                    for actor_id in state["runtime"].get("eligible_actors", [])
                    if actor_id != state["player"].get("controlled_character")
                ]
                return state, (
                    "等待玩家行动。当前仍有可响应角色在场：" + "、".join(eligible) + "。"
                    if eligible
                    else "等待玩家定义下一步行动。"
                )
            state = resolve_story_turn(state, self._deps, on_event)
            npc_acted = True
        raise RuntimeError("自动推进超过安全跳数，仍未到达稳定交接点。")
