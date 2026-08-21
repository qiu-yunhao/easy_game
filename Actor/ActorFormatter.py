from __future__ import annotations

from typing import Any, Mapping

from CharacterMemory import ensure_character_memory_state, normalize_character_memory_config
from GameState import GameState, ResolvedAct
from Memory.context import ActorMemoryContext
from PromptUtils import render_json_instruction
from ResolvedActUtils import build_resolved_act_payload
from ScenePlan import ScenePlan
from StoryStateUtils import clean_text


def _build_actor_runtime_prompt_state(actor_runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "emotion": actor_runtime.get("emotion", {}),
        "intent": actor_runtime.get("intent", ""),
        "known_facts": actor_runtime.get("known_facts", []),
        "relationship_delta": actor_runtime.get("relationship_delta", {}),
        "last_turn": actor_runtime.get("last_turn", -1),
    }


def _format_recalled(retrieved: list[Any]) -> list[dict[str, Any]]:
    # 把 list[ScoredDoc] 压成 prompt 友好的精简结构,口径对齐玩家工具 _query_recall。
    results: list[dict[str, Any]] = []
    for item in retrieved:
        metadata = getattr(item.doc, "metadata", {}) or {}
        results.append({
            "scene_id": metadata.get("scene_id", ""),
            "chapter_id": metadata.get("chapter_id", ""),
            "text": item.doc.text,
            "score": item.score,
        })
    return results


def _build_actor_payload(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> dict[str, Any]:
    planned_act = state["runtime"].get("next_act")
    # actor_id 以工厂 build 的 actor 为准,保证与 ctx.short_term 过滤对象一致。
    actor_id = memory_ctx.actor_id
    actor_profile = memory_ctx.persona
    actor_runtime = state["characters"].get(actor_id or "", {})
    agent_type = str(actor_profile.get("agent_type", "actor") or "actor")
    actor_memory_profile = normalize_character_memory_config(
        actor_profile.get("memory_profile", {}),
        agent_type=agent_type,
    )
    actor_memory = ensure_character_memory_state(
        actor_runtime.get("memory", {}),
        actor_profile=actor_profile,
    )
    actor_runtime_prompt = _build_actor_runtime_prompt_state(actor_runtime)
    payload: dict[str, Any] = {
        "plot": {
            "chapter_id": state["plot"]["chapter_id"],
            "scene_id": state["plot"]["scene_id"],
            "chapter_goal": state["plot"]["chapter_goal"],
            "plot_flags": state["plot"]["plot_flags"],
            "story_premise": state["plot"].get("story_premise", ""),
            "exploration_drive": state["plot"].get("exploration_drive", ""),
            "current_chapter_title": state["plot"].get("current_chapter_title", ""),
            "current_chapter_overview": state["plot"].get("current_chapter_overview", ""),
        },
        "actor_profile": actor_profile,
        "agent_contract": {
            "agent_type": agent_type,
            "l1_profile": actor_profile.get("l1_profile", {}),
            "layer_assignment": actor_profile.get("layer_assignment", {}),
            "memory_profile": actor_memory_profile,
        },
        "scene_plan": state["scene_plan"],
        "scene": state["scene"],
        "director_brief": state["director_brief"],
        "actor_runtime": actor_runtime_prompt,
        "next_act": planned_act,
        "recent_history": list(memory_ctx.short_term),
        "recalled_memories": _format_recalled(list(memory_ctx.retrieved)),
    }
    if agent_type == "L1":
        payload["player_memory"] = actor_memory.get("player_memory", {})
    return payload


def _clamp_unit(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _quote_spoken_text(spoken_text: str) -> str:
    stripped = spoken_text.strip()
    if not stripped:
        return ""
    quote_pairs = {
        "“": "”",
        "\"": "\"",
        "「": "」",
        "『": "』",
        "'": "'",
    }
    for opening, closing in quote_pairs.items():
        if stripped.startswith(opening):
            return stripped if stripped.endswith(closing) else f"{stripped}{closing}"
    for opening, closing in quote_pairs.items():
        if stripped.endswith(closing):
            return f"{opening}{stripped}"
    return f"“{stripped}”"


def compose_resolved_act_content(
    mode: str,
    spoken_text: str,
    nonverbal_action: str,
    fallback_content: str = "",
) -> str:
    spoken = _quote_spoken_text(spoken_text)
    action = nonverbal_action.strip()
    fallback = fallback_content.strip()

    if action and spoken:
        return f"{action}{spoken}"
    if spoken:
        return spoken
    if action:
        return action
    if fallback:
        return fallback
    if mode == "silence":
        return "..."
    return ""


def normalize_resolved_act(
    raw_result: Mapping[str, Any] | None,
    planned_act: Mapping[str, Any] | None,
    scene_plan: ScenePlan,
    on_stage: list[str],
) -> ResolvedAct:
    actor = None
    mode = "silence"
    target = None
    if planned_act:
        actor = planned_act.get("actor")
        mode = planned_act.get("mode", "silence")
        target = planned_act.get("target")

    if raw_result:
        actor = raw_result.get("actor") or actor
        mode = str(raw_result.get("mode", mode))
        target = raw_result.get("target", target)

    if target == actor:
        target = None
    if target not in on_stage:
        target = None

    content = ""
    spoken_text = ""
    nonverbal_action = ""
    next_intent = ""
    emotion_update: dict[str, float] = {}
    relationship_update: dict[str, float] = {}
    revealed_facts: list[str] = []
    triggered_plot_flags: dict[str, str] = {}
    should_end_scene = False
    should_end_chapter = False

    if raw_result:
        content = clean_text(raw_result.get("content", ""))
        spoken_text = clean_text(raw_result.get("spoken_text", ""))
        nonverbal_action = clean_text(raw_result.get("nonverbal_action", ""))
        next_intent = clean_text(raw_result.get("next_intent", ""))
        emotion_update = {
            str(key): _clamp_unit(value)
            for key, value in raw_result.get("emotion_update", {}).items()
            if str(key).strip()
        }
        relationship_update = {
            str(key): float(value)
            for key, value in raw_result.get("relationship_update", {}).items()
            if str(key).strip()
        }
        revealed_facts = [
            str(item) for item in raw_result.get("revealed_facts", []) if str(item).strip()
        ]
        triggered_plot_flags = {
            str(key): str(value)
            for key, value in raw_result.get("triggered_plot_flags", {}).items()
            if str(key) in scene_plan.get("must_happen", [])
        }
        should_end_scene = bool(raw_result.get("should_end_scene", False))
        should_end_chapter = bool(raw_result.get("should_end_chapter", False))

    if not spoken_text and not nonverbal_action and content:
        if mode == "speak":
            spoken_text = content
        else:
            nonverbal_action = content

    content = compose_resolved_act_content(
        mode=mode,
        spoken_text=spoken_text,
        nonverbal_action=nonverbal_action,
        fallback_content=content,
    )

    return build_resolved_act_payload(
        actor=actor,
        mode=mode,
        target=target,
        content=content,
        spoken_text=spoken_text,
        nonverbal_action=nonverbal_action,
        next_intent=next_intent,
        emotion_update=emotion_update,
        relationship_update=relationship_update,
        revealed_facts=revealed_facts,
        triggered_plot_flags=triggered_plot_flags,
        should_end_scene=should_end_scene,
        should_end_chapter=should_end_chapter,
    )


def build_actor_instruction(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> str:
    payload = _build_actor_payload(state, memory_ctx)
    return render_json_instruction(
        "Use the following scene context to produce one role-faithful turn as strict JSON.",
        payload,
    )


def build_l1_actor_instruction(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> str:
    payload = _build_actor_payload(state, memory_ctx)
    return render_json_instruction(
        "Use the following scene context to produce one L1 core-character turn as strict JSON. "
        "Honor the role's major conflict and dramatic weight while staying scene-bound.",
        payload,
    )
