from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PromptUtils import render_json_instruction
from StoryStateUtils import clean_text
from StoryToolContext import build_story_tool_prompt_context

if TYPE_CHECKING:
    from CharacterRosterTools import CharacterRosterToolRuntime
    from GameState import GameState


CONFLICT_MARKERS = (
    "conflict",
    "tension_peak",
    "对峙",
    "冲突",
    "争吵",
    "争执",
    "战斗",
    "敌对",
    "威胁",
    "背叛",
    "破裂",
    "剑拔弩张",
    "关系转折",
)


def _contains_conflict_marker(value: Any) -> bool:
    text = clean_text(value).lower()
    return bool(text) and any(marker in text for marker in CONFLICT_MARKERS)


def _build_conflict_transition_profile(state: "GameState") -> dict[str, Any]:
    reasons: list[str] = []
    for label, value in (
        ("scene.beat", state["scene"].get("beat", "")),
        ("scene_plan.scene_goal", state["scene_plan"].get("scene_goal", "")),
        ("director_memory.beat_suggestion", state["memory"]["director_memory"].get("beat_suggestion", "")),
        ("director_memory.active_conflicts", " ".join(state["memory"]["director_memory"].get("active_conflicts", []))),
    ):
        if _contains_conflict_marker(value):
            reasons.append(f"{label} carries conflict markers")

    if float(state["scene"].get("tension", 0.0) or 0.0) >= 0.58:
        reasons.append("scene tension is already elevated")
    if str(state["memory"]["director_memory"].get("tension_trend", "") or "").strip() == "high":
        reasons.append("director memory marks the scene as high tension")

    return {
        "required": bool(reasons),
        "reasons": reasons[:4],
        "lead_in_requirement": "If required=true, `lead_in_text` must be 2-3 Chinese sentences that only build pressure, atmosphere, and body language before the clash.",
        "wrap_up_requirement": "If required=true, `wrap_up_text` must be 2-3 Chinese sentences that only describe aftermath, emotional residue, and the scene settling after the clash.",
    }


def _serialize_stage_character(
    *,
    character_id: str,
    state: "GameState",
    character_profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    runtime = state["characters"].get(character_id, {})
    profile = character_profiles.get(character_id, {})
    agent_type = clean_text(profile.get("agent_type", "actor"), "actor")
    l1_profile = profile.get("l1_profile", {})
    layer_assignment = profile.get("layer_assignment", {})

    block = {
        "character_id": character_id,
        "name": profile.get("name", character_id),
        "agent_type": agent_type,
        "layer_assignment": layer_assignment if isinstance(layer_assignment, dict) else {},
        "story_role": profile.get("story_role", ""),
        "persona": profile.get("persona", []),
        "base_style": profile.get("base_style", ""),
        "intent": runtime.get("intent", ""),
        "emotion": runtime.get("emotion", {}),
        "last_turn": runtime.get("last_turn", -1),
    }
    if agent_type == "L1":
        block["l1_profile"] = l1_profile if isinstance(l1_profile, dict) else {}
        block["dramatic_weight"] = "This is a major role. Prefer them when the beat needs conflict, decision pressure, revelation, or relationship turning points."
    return block


def _group_actor_ids_by_tier(actor_ids: list[str], character_profiles: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    grouped = {
        "L1": [],
        "actor": [],
    }
    for actor_id in actor_ids:
        agent_type = clean_text(character_profiles.get(actor_id, {}).get("agent_type", "actor"), "actor")
        if agent_type != "L1":
            agent_type = "actor"
        grouped[agent_type].append(actor_id)
    return grouped


class DirectorFormatter:
    def build_instruction(
        self,
        state: GameState,
        character_profiles: dict[str, dict[str, Any]],
        character_roster_snapshot: dict[str, Any] | None = None,
        character_roster_tool_runtime: "CharacterRosterToolRuntime | None" = None,
    ) -> str:
        known_character_ids: list[str] = []
        for collection in (state["scene"]["on_stage"], state["characters"].keys(), character_profiles.keys()):
            for character_id in collection:
                resolved_id = str(character_id).strip()
                if resolved_id and resolved_id not in known_character_ids:
                    known_character_ids.append(resolved_id)

        on_stage_ids = [str(character_id).strip() for character_id in state["scene"]["on_stage"] if str(character_id).strip()]
        character_blocks = [
            _serialize_stage_character(
                character_id=cid,
                state=state,
                character_profiles=character_profiles,
            )
            for cid in on_stage_ids
        ]

        available_stage_candidates = []
        for cid in known_character_ids:
            if cid in on_stage_ids:
                continue
            profile = character_profiles.get(cid, {})
            candidate = _serialize_stage_character(
                character_id=cid,
                state=state,
                character_profiles=character_profiles,
            )
            candidate["introduction_hint"] = profile.get("introduction_hint", "")
            candidate["planned_chapter_ids"] = profile.get("planned_chapter_ids", [])
            available_stage_candidates.append(candidate)

        on_stage_tiers = _group_actor_ids_by_tier(on_stage_ids, character_profiles)
        available_candidate_tiers = _group_actor_ids_by_tier(
            [str(candidate["character_id"]).strip() for candidate in available_stage_candidates if str(candidate.get("character_id", "")).strip()],
            character_profiles,
        )

        payload = {
            "tiered_directing_contract": {
                "selection_order": [
                    "1. First check whether any L1 role or player-facing conflict needs the beat focus.",
                    "2. If no L1 pressure is active, decide whether the player should stay centered or whether the environment can breathe for a moment.",
                    "3. Bring in NPC-Actor roles only when they can support the beat through Help, Block, Buffer, or Inform.",
                    "4. NPC-Actor roles may shape the local situation, but they should not replace the chapter's main dramatic center unless no L1 conflict is available.",
                ],
                "L1_priority_rule": "Prefer L1 when the scene needs confrontation, revelation, decision pressure, relationship turning points, or a major stance shift.",
                "environment_rule": "After an environment change, NPC appearance is optional; choose it only when it serves the beat.",
            },
            "narrative_transition_contract": {
                "lead_in_text": "用于核心事件发生前的 1-2 句过渡描写，可表现时间流逝、氛围变化、压迫感或视线转移；若不需要可留空。",
                "wrap_up_text": "用于核心事件结束后的 1-2 句收尾描写，可表现余波、众人反应、环境回落或把控制权自然交还给玩家；若不需要可留空。",
                "conflict_override": "若 `conflict_transition_profile.required=true`，则必须把 `lead_in_text` 和 `wrap_up_text` 都写成 2-3 句，并保持引子/核心/余波的三段式节奏。",
            },
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
            "scene": {
                "location_id": state["scene"]["location_id"],
                "time_tag": state["scene"]["time_tag"],
                "beat": state["scene"]["beat"],
                "tension": state["scene"]["tension"],
                "focus_character": state["scene"]["focus_character"],
                "on_stage": state["scene"]["on_stage"],
                "suppressed": state["scene"].get("suppressed", []),
                "allow_interrupt": state["scene"]["allow_interrupt"],
            },
            "scene_plan": state["scene_plan"],
            "director_memory": state["memory"]["director_memory"],
            "conflict_transition_profile": _build_conflict_transition_profile(state),
            **build_story_tool_prompt_context(
                task="director_update",
                game_state=state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                cast_size=len(character_profiles),
                on_stage_count=len(on_stage_ids),
                available_stage_candidate_count=len(available_stage_candidates),
                history_count=len(state.get("history", [])),
                completed_chapter_count=len(state["plot"].get("completed_chapters", [])),
            ),
            "stage_tiers": {
                "on_stage_l1": on_stage_tiers["L1"],
                "on_stage_other": on_stage_tiers["actor"],
                "available_l1_candidates": available_candidate_tiers["L1"],
                "available_other_candidates": available_candidate_tiers["actor"],
            },
            "characters_on_stage": character_blocks,
            "available_stage_candidates": available_stage_candidates,
            "recent_history": state["history"][-6:],
        }

        return render_json_instruction(
            "Use the following story state to produce a DirectorBrief that advances the current beat "
            "without writing dialogue.",
            payload,
        )
