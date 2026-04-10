from __future__ import annotations

from typing import Mapping

from CharacterProfile import CharacterProfile
from GameplayTuning import RelationshipTuning
from GameState import GameState, ResolvedAct
from ResolvedActUtils import build_resolved_act_payload
from ScenePlan import ScenePlan


_SUPPORTIVE_TOKENS = ("help", "trust", "reconcile", "comfort", "support")
_CONFRONTATIONAL_TOKENS = ("pressure", "confront", "answer", "accuse", "force")


def _derive_fallback_line(
    actor_id: str,
    target: str | None,
    scene_plan: ScenePlan,
    profile: CharacterProfile,
    runtime: Mapping[str, object],
    planned_mode: str,
    beat_goal: str,
) -> str:
    name = profile.get("name", actor_id)
    target_name = target or "the room"
    intent = runtime.get("intent") or scene_plan.get("character_objectives", {}).get(actor_id, "")
    tone = profile.get("base_style", "")
    scene_goal = beat_goal or scene_plan.get("scene_goal", "") or "the scene objective"

    if planned_mode == "action":
        style = tone or "decisive"
        return f"{name} takes a {style} action to push the scene toward {scene_goal}."
    if planned_mode == "interrupt":
        focus = intent or scene_goal or "an immediate answer"
        return f"{name} cuts in on {target_name}, forcing the moment toward {focus}."
    if planned_mode == "silence":
        return f"{name} holds back and lets the silence change the balance in the room."
    if planned_mode == "event":
        return f"An external beat shifts the room and reframes {name}'s position in the scene."
    if intent:
        style = tone or "measured"
        return f"{name} addresses {target_name} in a {style} way, pushing toward {intent}."
    return f"{name} speaks to {target_name} and nudges the scene toward {scene_goal}."


def _infer_triggered_plot_flags(
    state: GameState,
    actor_id: str | None,
    content: str,
) -> dict[str, str]:
    if actor_id is None:
        return {}

    remaining = [
        item
        for item in state["scene_plan"].get("must_happen", [])
        if item not in state["plot"].get("plot_flags", {})
    ]
    if not remaining:
        return {}

    prioritized = actor_id in state["director_brief"].get("who_should_respond", [])
    focused = state["scene"].get("focus_character") == actor_id
    if prioritized or focused:
        return {remaining[0]: content[:120] or "completed"}
    return {}


def _infer_fallback_relationship_update(
    state: GameState,
    actor_id: str,
    target: str | None,
    mode: str,
    tuning: RelationshipTuning | None = None,
) -> dict[str, float]:
    tuning = tuning or RelationshipTuning()
    if target is None or target == actor_id:
        return {}

    scene_text = " ".join(
        [
            state["scene_plan"].get("scene_goal", ""),
            state["director_brief"].get("beat_goal", ""),
            " ".join(state["scene_plan"].get("notes", [])),
        ]
    ).lower()

    if any(token in scene_text for token in _SUPPORTIVE_TOKENS):
        base_delta = tuning.supportive_delta
    elif any(token in scene_text for token in _CONFRONTATIONAL_TOKENS):
        base_delta = tuning.confrontation_delta
    elif mode == "interrupt":
        base_delta = tuning.interrupt_delta
    elif mode == "action":
        base_delta = tuning.action_delta
    elif mode == "speak":
        base_delta = tuning.speak_delta
    else:
        base_delta = 0.0

    if base_delta == 0.0:
        return {}
    return {target: base_delta}


def build_heuristic_resolved_act(
    state: GameState,
    character_profiles: dict[str, CharacterProfile],
    relationship_tuning: RelationshipTuning | None = None,
) -> ResolvedAct:
    planned_act = state["runtime"].get("next_act")
    if not planned_act or planned_act.get("actor") is None:
        return build_resolved_act_payload(
            actor=None,
            mode="event",
            target=None,
            content="",
            should_end_scene=state["runtime"].get("scene_finished", False),
            should_end_chapter=state["runtime"].get("chapter_finished", False),
        )

    actor_id = str(planned_act["actor"])
    target = planned_act.get("target")
    if target == actor_id:
        target = None
    profile = character_profiles.get(actor_id, {})
    runtime = state["characters"].get(actor_id, {})
    beat_goal = state["director_brief"].get("beat_goal") or state["scene_plan"].get("scene_goal", "")
    content = _derive_fallback_line(
        actor_id=actor_id,
        target=target,
        scene_plan=state["scene_plan"],
        profile=profile,
        runtime=runtime,
        planned_mode=str(planned_act.get("mode", "speak")),
        beat_goal=beat_goal,
    )
    triggered_plot_flags = _infer_triggered_plot_flags(state, actor_id, content)
    relationship_update = _infer_fallback_relationship_update(
        state=state,
        actor_id=actor_id,
        target=target,
        mode=str(planned_act.get("mode", "speak")),
        tuning=relationship_tuning,
    )

    return build_resolved_act_payload(
        actor=actor_id,
        mode=str(planned_act.get("mode", "speak")),
        target=target,
        content=content,
        next_intent=state["scene_plan"].get("character_objectives", {}).get(
            actor_id,
            runtime.get("intent", ""),
        ),
        relationship_update=relationship_update,
        triggered_plot_flags=triggered_plot_flags,
    )
