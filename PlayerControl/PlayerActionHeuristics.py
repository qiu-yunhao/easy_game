from __future__ import annotations

from Actor.ActorFormatter import normalize_resolved_act
from CharacterProfile import CharacterProfile
from GameState import GameState, ResolvedAct
from PlayerControl.PlayerCommandTools import infer_player_tool_call
from ResolvedActUtils import build_resolved_act_payload


def _infer_mode(raw_input: str, fallback_mode: str) -> str:
    lowered = raw_input.lower()
    if not raw_input.strip():
        return "silence"
    if any(token in lowered for token in ("打断", "interrupt", "插话", "抢先")):
        return "interrupt"
    if any(token in lowered for token in ("walk", "move", "grab", "take", "open", "close", "push")):
        return "action"
    return fallback_mode or "speak"


def _infer_target(
    raw_input: str,
    fallback_target: str | None,
    actor_id: str,
    character_profiles: dict[str, CharacterProfile],
) -> str | None:
    lowered = raw_input.lower()
    for candidate_id, profile in character_profiles.items():
        if candidate_id == actor_id:
            continue
        name = str(profile.get("name", candidate_id)).lower()
        if candidate_id.lower() in lowered or name in lowered:
            return candidate_id
    return fallback_target


def _infer_relationship_update(raw_input: str, target: str | None) -> dict[str, float]:
    if target is None:
        return {}

    lowered = raw_input.lower()
    if any(token in lowered for token in ("trust", "help", "sorry", "support", "保护", "相信")):
        return {target: 0.1}
    if any(token in lowered for token in ("threat", "force", "accuse", "lie", "质问", "威胁", "逼")):
        return {target: -0.15}
    return {}


def _infer_triggered_plot_flags(state: GameState, raw_input: str) -> dict[str, str]:
    lowered = raw_input.lower()
    triggered: dict[str, str] = {}
    for item in state["scene_plan"].get("must_happen", []):
        normalized_item = item.replace("_", " ").lower()
        if normalized_item and normalized_item in lowered:
            triggered[item] = raw_input[:120] or "completed"
    return triggered


def _build_raw_result(
    raw_input: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> ResolvedAct:
    planned_act = state["runtime"].get("next_act") or {}
    actor_id = str(planned_act.get("actor") or "")
    target = _infer_target(
        raw_input=raw_input,
        fallback_target=planned_act.get("target"),
        actor_id=actor_id,
        character_profiles=character_profiles,
    )
    tool_call = infer_player_tool_call(raw_input, character_profiles=character_profiles) or None
    mode = "event" if tool_call is not None else _infer_mode(raw_input, str(planned_act.get("mode", "speak")))

    payload = build_resolved_act_payload(
        actor=actor_id or None,
        mode=mode,
        target=target,
        content=raw_input.strip() or "...",
        next_intent=state["characters"].get(actor_id, {}).get("intent", ""),
        relationship_update={} if tool_call is not None else _infer_relationship_update(raw_input, target),
        triggered_plot_flags={} if tool_call is not None else _infer_triggered_plot_flags(state, raw_input),
    )
    if tool_call is not None:
        payload["tool_call"] = tool_call
    return payload


def build_heuristic_player_resolved_act(
    raw_input: str,
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
) -> ResolvedAct:
    raw_result = _build_raw_result(raw_input, state, character_profiles)
    normalized = normalize_resolved_act(
        raw_result=raw_result,
        planned_act=state["runtime"].get("next_act"),
        scene_plan=state["scene_plan"],
        on_stage=state["scene"].get("on_stage", []),
    )
    if isinstance(raw_result, dict) and isinstance(raw_result.get("tool_call"), dict):
        normalized["tool_call"] = raw_result["tool_call"]
    return normalized
