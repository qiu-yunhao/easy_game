from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from CharacterRosterTools import CharacterRosterToolRuntime
from CharacterProfile import ensure_character_profile, ensure_character_profiles
from Graph.builder import (
    initialize_story_session,
    prepare_chapter_turn,
    prepare_story_setup,
    resolve_story_turn,
)
from Graph.beat_subgraph import is_player_turn
from Narrator.NarrationPresets import (
    DEFAULT_NARRATION_STYLE_PRESET,
    NARRATION_STYLE_GUIDANCE,
    resolve_narration_style_preset,
)
from PlayerControl import BufferedPlayerInterface
from PlayerControl.PlayerCommandTools import (
    PlayerCommandToolRuntime,
    looks_like_tool_request,
    normalize_tool_call,
)
from PlayerControl.PlayerIntentPlannerAgent import build_heuristic_player_intent_plan
from ResolvedActUtils import build_resolved_act_payload
from session_bootstrap import (
    PLAYER_CHARACTER_ID,
    build_default_character_profiles,
    build_default_scene_config,
    build_default_state,
    build_graph_dependencies,
    warm_model_clients,
)

if TYPE_CHECKING:
    from Persistence.Store import GameSaveStore


TRAILING_SENTENCE_MARKS = "。！？!?…"
NARRATION_STYLE_LABELS = {
    "xianxia_default": "仙侠克制",
    "light_novel": "轻小说",
    "epic": "史诗感",
}
NARRATION_STYLE_DESCRIPTIONS = {
    "xianxia_default": "克制、凝练，带一点古典韵味。",
    "light_novel": "轻快、清晰，情绪和动作都更直观。",
    "epic": "庄重、宏阔，强调史诗感但不额外虚构。",
}


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _strip_trailing_sentence_marks(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip() or fallback
    while text and text[-1] in TRAILING_SENTENCE_MARKS:
        text = text[:-1].rstrip()
    return text or fallback


def _serialize_narration_style_options() -> list[dict[str, str]]:
    return [
        {
            "value": preset,
            "label": NARRATION_STYLE_LABELS.get(preset, preset),
            "description": NARRATION_STYLE_DESCRIPTIONS.get(preset, guidance),
        }
        for preset, guidance in NARRATION_STYLE_GUIDANCE.items()
    ]


def _display_name(character_id: str | None, profiles: dict[str, dict[str, Any]]) -> str:
    if character_id is None:
        return "系统"
    return str(profiles.get(character_id, {}).get("name", character_id))


def _serialize_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    normalized = ensure_character_profile(
        profile,
        character_id=str(profile.get("character_id", "") or "").strip(),
        include_backpack="backpack" in profile,
    )
    return {
        "character_id": normalized.get("character_id", ""),
        "name": normalized.get("name", ""),
        "gender": normalized.get("gender", ""),
        "race": normalized.get("race", ""),
        "background": normalized.get("background", ""),
        "spiritual_root": normalized.get("spiritual_root", ""),
        "realm": normalized.get("realm", ""),
        "main_technique": normalized.get("main_technique", ""),
        "backpack": list(normalized.get("backpack", [])),
        "persona": list(normalized.get("persona", [])),
        "base_style": normalized.get("base_style", ""),
        "agent_type": normalized.get("agent_type", "actor"),
        "story_layer": normalized.get("story_layer", "actor"),
        "storage_mode": normalized.get("storage_mode", "player_bound_instance"),
        "occupation": normalized.get("occupation", ""),
        "l2_profile": dict(normalized.get("l2_profile", {})),
        "l1_profile": dict(normalized.get("l1_profile", {})),
        "layer_assignment": dict(normalized.get("layer_assignment", {})),
        "memory_profile": dict(normalized.get("memory_profile", {})),
        "is_active": bool(normalized.get("is_active", True)),
        "is_offstage": bool(normalized.get("is_offstage", False)),
    }


def _build_prompt_templates(state: dict[str, Any]) -> list[dict[str, str]]:
    scene_goal = _strip_trailing_sentence_marks(state.get("scene_goal"), "推进当前场景")
    chapter_goal = _strip_trailing_sentence_marks(state.get("chapter_goal"), scene_goal)
    beat_goal = _strip_trailing_sentence_marks(state.get("beat_goal"), scene_goal)
    scene_location = str(state.get("scene_location", "") or "").strip() or "当前区域"
    return [
        {
            "label": "观察局势",
            "fill": f"我先停下来观察{scene_location}的情况，确认最值得注意的线索、人物或风险，再决定如何{scene_goal}。",
        },
        {
            "label": "稳住节奏",
            "fill": f"我先稳住自己，梳理眼下已知的信息和条件，再选择最稳妥的一步，朝着“{chapter_goal}”推进。",
        },
        {
            "label": "主动接触",
            "fill": f"我主动接近这里最关键的人、线索或障碍，直接推动场面朝“{beat_goal}”发展。",
        },
    ]


def _serialize_history_entry(
    item: dict[str, Any],
    player_character: str | None,
    profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    system_message = item.get("message_kind") == "system" or item["actor"] is None
    return {
        "turn": item["turn"],
        "actor": item["actor"],
        "speaker": "系统" if system_message else _display_name(item["actor"], profiles),
        "role": "系统" if system_message else ("玩家" if item["actor"] == player_character else "角色"),
        "mode": item["mode"],
        "content": item["content"],
        "spoken_text": item.get("spoken_text", ""),
        "nonverbal_action": item.get("nonverbal_action", ""),
        "kind": item.get("message_kind") or ("system" if system_message else ("player" if item["actor"] == player_character else "npc")),
        "message_kind": item.get("message_kind", ""),
        "narration_source": item.get("narration_source", ""),
        "tool_name": item.get("tool_name", ""),
    }


def _resolve_parser_status(story_initialized: bool, state: dict[str, Any]) -> str:
    if not story_initialized:
        return "等待设定"
    if state["runtime"].get("scene_finished", False):
        return "场景完成"
    return "等待玩家" if is_player_turn(state) else "推进场景中"


@dataclass(slots=True)
class SessionConfig:
    mode: str = "agent-first"
    player_character: str = PLAYER_CHARACTER_ID
    player_profile: dict[str, Any] | None = None
    narration_style_preset: str = DEFAULT_NARRATION_STYLE_PRESET


class WebGameSession:
    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()
        self.config.narration_style_preset = resolve_narration_style_preset(self.config.narration_style_preset)
        self._lock = threading.Lock()
        self._player_interface = BufferedPlayerInterface()
        self.save_store: GameSaveStore | None = None
        self.active_user_id: int | None = None
        self.active_player_id: int | None = None
        self.last_handoff_reason = "请先确认玩家档案，然后初始化当前场景。"
        self.story_initialized = False
        self.character_profiles: dict[str, dict[str, Any]] = {}
        self.scene_config: dict[str, Any] = {}
        self._rebuild_session(initialize_story=bool(self.config.player_profile))

    def reset(
        self,
        *,
        mode: str | None = None,
        player_character: str | None = None,
        player_profile: dict[str, Any] | None = None,
        narration_style_preset: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            for field, value in (
                ("mode", mode),
                ("player_character", player_character),
                ("player_profile", player_profile),
            ):
                if value is not None:
                    setattr(self.config, field, value)
            if narration_style_preset is not None:
                self.config.narration_style_preset = resolve_narration_style_preset(narration_style_preset)
            self.last_handoff_reason = "设定已更新，正在重建开场场景。"
            self._rebuild_session(initialize_story=True)
            return self.serialize_state()

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return self.serialize_state()

    def bind_save_context(
        self,
        *,
        save_store: GameSaveStore | None = None,
        user_id: int | None = None,
        player_id: int | None = None,
    ) -> None:
        with self._lock:
            self._bind_save_context_unlocked(save_store=save_store, user_id=user_id, player_id=player_id)

    def _bind_save_context_unlocked(
        self,
        *,
        save_store: GameSaveStore | None = None,
        user_id: int | None = None,
        player_id: int | None = None,
    ) -> None:
        if save_store is not None or self.save_store is None:
            self.save_store = save_store
        self.active_user_id = user_id
        self.active_player_id = player_id

    def _current_save_context_unlocked(self) -> dict[str, int | None]:
        return {"user_id": self.active_user_id, "player_id": self.active_player_id}

    def _require_save_store_unlocked(self) -> "GameSaveStore":
        if self.save_store is None:
            raise RuntimeError("数据库未配置，请先提供 --database-url 或 STAGEBOUND_DATABASE_URL。")
        return self.save_store

    def list_players_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return self._list_players_for_user_unlocked(user_id)

    def _list_players_for_user_unlocked(self, user_id: int) -> list[dict[str, Any]]:
        return self._require_save_store_unlocked().list_players_for_user(user_id)

    def save_player_session(
        self,
        *,
        user_id: int,
        player_id: int,
        save_kind: str = "manual",
        save_label: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._save_player_session_unlocked(
                user_id=user_id,
                player_id=player_id,
                save_kind=save_kind,
                save_label=save_label,
            )

    def _save_player_session_unlocked(
        self,
        *,
        user_id: int,
        player_id: int,
        save_kind: str = "manual",
        save_label: str | None = None,
    ) -> dict[str, Any]:
        result = self._require_save_store_unlocked().save_player_session(
            user_id=user_id,
            player_id=player_id,
            session_snapshot=self._export_runtime_snapshot_unlocked(),
            save_kind=save_kind,
            save_label=save_label,
        )
        self._bind_save_context_unlocked(save_store=self.save_store, user_id=user_id, player_id=player_id)
        return result

    def load_player_session(
        self,
        *,
        user_id: int,
        player_id: int,
    ) -> dict[str, Any]:
        with self._lock:
            return self._load_player_session_unlocked(user_id=user_id, player_id=player_id)

    def _load_player_session_unlocked(
        self,
        *,
        user_id: int,
        player_id: int,
    ) -> dict[str, Any]:
        loaded = self._require_save_store_unlocked().load_player_session(user_id=user_id, player_id=player_id)
        state = self._load_runtime_snapshot_unlocked(loaded["snapshot"])
        self._bind_save_context_unlocked(save_store=self.save_store, user_id=user_id, player_id=player_id)
        return {**loaded, "state": state}

    def export_runtime_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._export_runtime_snapshot_unlocked()

    def _export_runtime_snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "session": {
                "mode": self.config.mode,
                "player_character": self.config.player_character,
                "narration_style_preset": self.config.narration_style_preset,
                "story_initialized": self.story_initialized,
                "last_handoff_reason": self.last_handoff_reason,
            },
            "state": _json_clone(self.state),
            "character_profiles": _json_clone(self.character_profiles),
            "scene_config": _json_clone(self.scene_config),
        }

    def load_runtime_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._load_runtime_snapshot_unlocked(snapshot)

    def _load_runtime_snapshot_unlocked(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        session_meta = snapshot.get("session")
        state = snapshot.get("state")
        character_profiles = snapshot.get("character_profiles")
        scene_config = snapshot.get("scene_config")
        if not isinstance(session_meta, dict):
            raise RuntimeError("存档缺少 session 配置。")
        if not isinstance(state, dict):
            raise RuntimeError("存档缺少 game state。")
        if not isinstance(character_profiles, dict):
            raise RuntimeError("存档缺少 character_profiles。")
        if not isinstance(scene_config, dict):
            raise RuntimeError("存档缺少 scene_config。")

        self.config.mode = str(session_meta.get("mode") or self.config.mode or "agent-first")
        self.config.player_character = str(session_meta.get("player_character") or self.config.player_character or PLAYER_CHARACTER_ID)
        self.config.narration_style_preset = resolve_narration_style_preset(
            str(session_meta.get("narration_style_preset") or self.config.narration_style_preset or DEFAULT_NARRATION_STYLE_PRESET)
        )
        self.character_profiles = ensure_character_profiles(
            character_profiles,
            player_character_id=self.config.player_character or PLAYER_CHARACTER_ID,
        )
        self.scene_config = _json_clone(scene_config)
        self.state = _json_clone(state)
        self._reload_dependencies()
        self.story_initialized = bool(session_meta.get("story_initialized", False))
        self.last_handoff_reason = str(session_meta.get("last_handoff_reason") or "已从数据库存档恢复。")
        return self.serialize_state()

    def apply_player_action(self, raw_input: str) -> dict[str, Any]:
        with self._lock:
            if not self.story_initialized:
                raise RuntimeError("请先初始化场景，再提交玩家动作。")
            if self.state["runtime"].get("scene_finished", False):
                raise RuntimeError("当前场景已经结束，请重置后继续。")
            self._advance_until_player_turn()
            if not is_player_turn(self.state):
                raise RuntimeError("当前还没有轮到玩家行动。")
            tool_response = self._maybe_handle_player_intent_plan_unlocked(raw_input)
            if tool_response is not None:
                return tool_response
            self._player_interface.push_action(raw_input)
            self.state = resolve_story_turn(self.state, self.deps)
            self.last_handoff_reason = self._advance_until_player_turn()
            return self.serialize_state()

    def apply_player_action_streaming(
        self,
        raw_input: str,
        on_event: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Resolve a player action, streaming each committed history entry.

        Returns the final full state snapshot (same shape as
        ``apply_player_action``) so the client can reconcile non-history state
        after the stream completes.
        """
        with self._lock:
            if not self.story_initialized:
                raise RuntimeError("请先初始化场景，再提交玩家动作。")
            if self.state["runtime"].get("scene_finished", False):
                raise RuntimeError("当前场景已经结束，请重置后继续。")
            self._advance_until_player_turn()
            if not is_player_turn(self.state):
                raise RuntimeError("当前还没有轮到玩家行动。")

            profiles = self.character_profiles
            player_character = self.config.player_character

            def _emit(entry: dict[str, Any]) -> None:
                on_event(_serialize_history_entry(entry, player_character, profiles))

            tool_response = self._maybe_handle_player_intent_plan_unlocked(raw_input)
            if tool_response is not None:
                # Tool path doesn't run the beat loop; replay its history so
                # streaming clients still receive the new entries in order.
                for entry in tool_response.get("history", []):
                    on_event(entry)
                return tool_response
            self._player_interface.push_action(raw_input)
            self.state = resolve_story_turn(self.state, self.deps, _emit)
            self.last_handoff_reason = self._advance_until_player_turn(on_event=_emit)
            return self.serialize_state()

    def _maybe_handle_player_intent_plan_unlocked(self, raw_input: str) -> dict[str, Any] | None:
        if not looks_like_tool_request(raw_input) or self.deps.player_command_tools is None:
            return None
        planner_agent = self.deps.player_intent_planner_agent
        plan = (
            planner_agent.plan_action(raw_input=raw_input, state=self.state, character_profiles=self.deps.character_profiles)
            if planner_agent is not None
            else build_heuristic_player_intent_plan(raw_input, character_profiles=self.deps.character_profiles)
        )
        planned_steps = list(plan.get("planned_steps", [])) if isinstance(plan, dict) else []
        if not any(step.get("kind") == "tool_call" for step in planned_steps if isinstance(step, dict)):
            return None

        executed = False
        for step in planned_steps[:5]:
            if not isinstance(step, dict):
                continue
            if step.get("kind") == "tool_call":
                tool_call = normalize_tool_call(step.get("tool_call") if isinstance(step.get("tool_call"), dict) else None)
                if not tool_call["should_call"]:
                    continue
                parsed_act = build_resolved_act_payload(
                    actor=(self.state["runtime"].get("next_act") or {}).get("actor"),
                    mode="event",
                    target=None,
                    content=str(step.get("content") or raw_input).strip() or raw_input,
                )
                parsed_act["tool_call"] = tool_call
                parsed_act["planned_steps"] = planned_steps
                result = self.deps.player_command_tools.execute(tool_call)
                self._append_tool_message_unlocked(raw_input=raw_input, parsed_act=parsed_act, result=result)
                executed = True
                if not result.get("success", False):
                    break
            else:
                action_text = str(step.get("content") or "").strip()
                if not action_text:
                    continue
                self._player_interface.push_action(action_text)
                self.state = resolve_story_turn(self.state, self.deps)
                self.last_handoff_reason = self._advance_until_player_turn()
                executed = True
                if self.state["runtime"].get("scene_finished", False):
                    break
        if not executed:
            return None
        return self.serialize_state()

    def _append_tool_message_unlocked(
        self,
        *,
        raw_input: str,
        parsed_act: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        next_turn = int(self.state["runtime"].get("turn_index", 0) or 0) + 1
        tool_payload = _json_clone(result.get("payload", {})) if isinstance(result.get("payload"), dict) else {}
        self.state = {
            **self.state,
            "history": [
                *self.state["history"],
                {
                    "turn": next_turn,
                    "actor": None,
                    "mode": "event",
                    "content": str(result.get("text", "") or "").strip(),
                    "spoken_text": "",
                    "nonverbal_action": "",
                    "tool_name": str(result.get("tool_name", "") or "").strip(),
                    "tool_payload": tool_payload,
                    "message_kind": "system",
                },
            ],
            "runtime": {
                **self.state["runtime"],
                "turn_index": next_turn,
                "last_actor": None,
                "last_mode": "event",
                "resolved_act": None,
            },
            "player": {
                **self.state["player"],
                "last_input": raw_input,
                "last_parsed_act": {
                    **parsed_act,
                    "tool_name": str(result.get("tool_name", "") or "").strip(),
                    "tool_result_text": str(result.get("text", "") or "").strip(),
                    "tool_result_payload": tool_payload,
                },
            },
        }

    def _rebuild_session(self, *, initialize_story: bool = False) -> None:
        self.character_profiles = build_default_character_profiles(self.config.player_profile)
        self.scene_config = build_default_scene_config(self.config.narration_style_preset)
        self.state = build_default_state(
            player_character=self.config.player_character,
            character_profiles=self.character_profiles,
        )
        self._reload_dependencies()
        self.story_initialized = False
        if initialize_story:
            self._initialize_story()

    def _reload_dependencies(self) -> None:
        self.deps = build_graph_dependencies(
            self.config.mode,
            interactive=False,
            character_profiles=self.character_profiles,
            scene_config=self.scene_config,
        )
        self.character_profiles = self.deps.character_profiles
        self.scene_config = self.deps.scene_config
        self._bind_dependencies()

    def _bind_dependencies(self) -> None:
        self._player_interface.clear()
        self.deps.player_interface = self._player_interface
        self.deps.player_command_tools = PlayerCommandToolRuntime(
            resolve_store=lambda: self.save_store,
            resolve_context=self._current_save_context_unlocked,
            export_session_snapshot=self._export_runtime_snapshot_unlocked,
            load_session_snapshot=self._load_runtime_snapshot_unlocked,
            activate_context=lambda user_id, player_id: self._bind_save_context_unlocked(
                save_store=self.save_store,
                user_id=user_id,
                player_id=player_id,
            ),
            list_players_for_user=self._list_players_for_user_unlocked,
            save_checkpoint=lambda user_id, player_id, save_label: self._save_player_session_unlocked(
                user_id=user_id,
                player_id=player_id,
                save_kind="manual",
                save_label=save_label,
            ),
            load_checkpoint=lambda user_id, player_id: self._load_player_session_unlocked(
                user_id=user_id,
                player_id=player_id,
            ),
        )
        character_roster_tool_runtime = CharacterRosterToolRuntime(
            resolve_store=lambda: self.save_store,
            resolve_context=self._current_save_context_unlocked,
            resolve_profiles=lambda: self.deps.character_profiles,
        )
        for agent in (
            self.deps.playwright_agent,
            self.deps.actor_create_agent,
            self.deps.director_agent,
        ):
            if agent is not None and hasattr(agent, "bind_character_roster_tool_runtime"):
                agent.bind_character_roster_tool_runtime(character_roster_tool_runtime)
        if self.config.mode in {"agent-first", "live"} and self.deps.semantic_parser_agent is None:
            self.deps.semantic_parser_agent = self.deps.component_factory.build_semantic_parser_agent()
        if self.config.mode in {"agent-first", "live"} and self.deps.player_intent_planner_agent is None:
            self.deps.player_intent_planner_agent = self.deps.component_factory.build_player_intent_planner_agent()
        if self.config.mode in {"agent-first", "live"}:
            warm_model_clients(self.deps.player_intent_planner_agent, self.deps.semantic_parser_agent)

    def _initialize_story(self) -> None:
        if self.config.mode in {"agent-first", "live"}:
            self.state = prepare_story_setup(self.state, self.deps)
            self.state = self._prime_opening_player_turn(self.state)
            self.story_initialized = True
            self.last_handoff_reason = "开场交接完成，等待玩家定义第一步行动。"
            return
        self.state = initialize_story_session(self.state, self.deps)
        self.story_initialized = True
        self.last_handoff_reason = self._advance_until_player_turn()

    def _prime_opening_player_turn(self, state: dict[str, Any]) -> dict[str, Any]:
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

    def _ensure_prepared_turn(self) -> None:
        if self.story_initialized and not self.state["runtime"].get("scene_finished", False) and self.state["runtime"].get("next_act") is None:
            self.state = prepare_chapter_turn(self.state, self.deps)

    def _advance_until_player_turn(
        self,
        max_hops: int = 24,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> str:
        hops = 0
        npc_acted = False
        while hops < max_hops:
            hops += 1
            self._ensure_prepared_turn()
            if self.state["runtime"].get("scene_finished", False):
                reason = self.state["runtime"].get("scene_end_evaluation", {}).get("reason", "")
                return reason or "当前场景已经结束。"
            next_act = self.state["runtime"].get("next_act")
            if next_act is None:
                return "当前没有新的自动后续动作。"
            if is_player_turn(self.state):
                if npc_acted:
                    return "场景角色动作已结算，等待玩家回应。"
                eligible = [
                    actor_id
                    for actor_id in self.state["runtime"].get("eligible_actors", [])
                    if actor_id != self.state["player"].get("controlled_character")
                ]
                return (
                    "等待玩家行动。当前仍有可响应角色在场：" + "、".join(eligible) + "。"
                    if eligible
                    else "等待玩家定义下一步行动。"
                )
            self.state = resolve_story_turn(self.state, self.deps, on_event)
            npc_acted = True
        raise RuntimeError("自动推进超过安全跳数，仍未到达稳定交接点。")

    def serialize_state(self) -> dict[str, Any]:
        state = self.state
        plot, runtime, scene = state["plot"], state["runtime"], state["scene"]
        scene_plan, director_brief = state["scene_plan"], state["director_brief"]
        player_state, scene_memory = state["player"], state["memory"]["scene_memory"]
        player_character = player_state.get("controlled_character")
        profiles = self.deps.character_profiles
        player_profile = profiles.get(player_character or "", {})
        rival_profile = next((profile for cid, profile in profiles.items() if cid != player_character), None)
        next_act = runtime.get("next_act")
        latest_parsed_act = player_state.get("last_parsed_act")
        if latest_parsed_act is None and next_act is not None:
            latest_parsed_act = build_resolved_act_payload(
                actor=next_act.get("actor"),
                mode=next_act.get("mode", "speak"),
                target=next_act.get("target"),
                content="",
                next_intent=scene_plan.get("scene_goal", ""),
            )
        scene_end = runtime.get("scene_end_evaluation") or {}
        payload = {
            "mode": self.config.mode,
            "narration_style_preset": self.deps.gameplay_tuning.narration.style_preset,
            "available_narration_styles": _serialize_narration_style_options(),
            "story_initialized": self.story_initialized,
            "player_character": player_character,
            "player_name": _display_name(player_character, profiles),
            "player_profile": _serialize_profile(player_profile),
            "rival_profile": _serialize_profile(rival_profile),
            "story_premise": plot.get("story_premise", ""),
            "exploration_drive": plot.get("exploration_drive", ""),
            "cultivation_goal": plot.get("cultivation_goal", ""),
            "current_chapter_title": plot.get("current_chapter_title", ""),
            "current_chapter_overview": plot.get("current_chapter_overview", ""),
            "current_chapter_index": int(plot.get("current_chapter_index", 0) or 0),
            "current_chapter_realm": plot.get("current_chapter_realm", ""),
            "next_chapter_realm": plot.get("next_chapter_realm", ""),
            "chapter_transition_requirement": plot.get("chapter_transition_requirement", ""),
            "current_player_realm": plot.get("current_player_realm", ""),
            "current_scene_index": int(plot.get("current_scene_index", 0) or 0),
            "story_outline": list(plot.get("story_outline", [])),
            "completed_chapters": list(plot.get("completed_chapters", [])),
            "story_foundation_source": plot.get("story_foundation_source", ""),
            "chapter_focus_source": plot.get("chapter_focus_source", ""),
            "turn_index": runtime["turn_index"],
            "upcoming_round": runtime["turn_index"] + 1,
            "scene_finished": runtime.get("scene_finished", False),
            "chapter_finished": runtime.get("chapter_finished", False),
            "chapter_goal": plot.get("chapter_goal", ""),
            "scene_location": scene.get("location_id", ""),
            "scene_time": scene.get("time_tag", ""),
            "scene_beat": scene.get("beat", ""),
            "scene_goal": scene_plan.get("scene_goal", ""),
            "beat_goal": director_brief.get("beat_goal", ""),
            "memory_summary": scene_memory.get("summary", ""),
            "scene_end_reason": scene_end.get("reason", ""),
            "handoff_reason": self.last_handoff_reason,
            "tension_percent": int(float(scene.get("tension", 0.0)) * 100),
            "next_act": next_act,
            "eligible_actors": runtime.get("eligible_actors", []),
            "history": [_serialize_history_entry(item, player_character, profiles) for item in state["history"]],
            "player": {
                "enabled": player_state.get("enabled", False),
                "controlled_character": player_character,
                "last_input": player_state.get("last_input", ""),
                "last_parsed_act": latest_parsed_act,
            },
            "parser_status": _resolve_parser_status(self.story_initialized, state),
        }
        payload["prompt_templates"] = _build_prompt_templates(payload)
        return payload


__all__ = [
    "SessionConfig",
    "WebGameSession",
    "_build_prompt_templates",
    "_strip_trailing_sentence_marks",
]
