from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, TypedDict

from StoryStateUtils import matches_lookup, normalize_lookup_text
from ToolSkillRegistry import (
    load_tool_skill_prompt_context,
    match_tool_definition,
    render_tool_schemas_for_prompt as render_registry_tool_schemas,
    tool_definitions_for_audience,
)

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


class PlayerToolCall(TypedDict):
    should_call: bool
    name: str
    arguments: dict[str, Any]
    reason: str


class PlayerToolContext(TypedDict):
    user_id: int | None
    player_id: int | None


class PlayerToolResult(TypedDict):
    success: bool
    tool_name: str
    text: str
    payload: dict[str, Any]


PLAYER_TOOL_NAMES = tuple(tool.name for tool in tool_definitions_for_audience("player"))


def build_tool_call(
    name: str,
    *,
    arguments: dict[str, Any] | None = None,
    reason: str = "",
) -> PlayerToolCall:
    return {
        "should_call": name in PLAYER_TOOL_NAMES,
        "name": name if name in PLAYER_TOOL_NAMES else "",
        "arguments": dict(arguments or {}),
        "reason": str(reason or "").strip(),
    }


def empty_tool_call() -> PlayerToolCall:
    return {
        "should_call": False,
        "name": "",
        "arguments": {},
        "reason": "",
    }


def normalize_tool_call(tool_call: dict[str, Any] | None) -> PlayerToolCall:
    if not isinstance(tool_call, dict):
        return empty_tool_call()
    normalized = build_tool_call(
        str(tool_call.get("name", "") or "").strip(),
        arguments=tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {},
        reason=str(tool_call.get("reason", "") or "").strip(),
    )
    normalized["should_call"] = bool(tool_call.get("should_call", False)) and bool(normalized["name"])
    return normalized


def _match_player_tool(raw_input: str) -> tuple[str, str]:
    tool, _skill = match_tool_definition(raw_input, audience="player")
    if tool is None:
        return "", ""
    return tool.name, tool.reason


def looks_like_tool_request(raw_input: str) -> bool:
    return bool(_match_player_tool(raw_input)[0])


def _guess_relation_target(
    raw_input: str,
    character_profiles: dict[str, "CharacterProfile"] | None,
) -> str:
    normalized_input = normalize_lookup_text(raw_input)
    for character_id, profile in (character_profiles or {}).items():
        if character_id == "player":
            continue
        candidate_names = {
            str(character_id or "").strip(),
            str(profile.get("name", "") or "").strip(),
        }
        for candidate in candidate_names:
            if matches_lookup(normalized_input, candidate):
                return candidate
    return ""


def infer_player_tool_call(
    raw_input: str,
    *,
    character_profiles: dict[str, "CharacterProfile"] | None = None,
) -> PlayerToolCall | None:
    tool_name, reason = _match_player_tool(raw_input)
    if not tool_name:
        return None
    if tool_name == "query_relation":
        target_name = _guess_relation_target(raw_input, character_profiles)
        return build_tool_call(
            tool_name,
            arguments={"target_name": target_name} if target_name else {},
            reason=reason,
        )
    return build_tool_call(tool_name, reason=reason)


def render_tool_schemas_for_prompt(raw_input: str | None = None) -> list[dict[str, Any]]:
    return render_registry_tool_schemas(raw_input, audience="player")


def load_tool_skills_for_prompt(raw_input: str) -> list[dict[str, Any]]:
    return load_tool_skill_prompt_context(raw_input, audience="player")


def _join_fragments(values: list[str], *, delimiter: str = "，") -> str:
    return delimiter.join(fragment for fragment in values if fragment)


@dataclass(slots=True)
class PlayerCommandToolRuntime:
    resolve_store: Callable[[], Any | None]
    resolve_context: Callable[[], PlayerToolContext]
    export_session_snapshot: Callable[[], dict[str, Any]]
    load_session_snapshot: Callable[[dict[str, Any]], dict[str, Any]]
    activate_context: Callable[[int | None, int | None], None]
    list_players_for_user: Callable[[int], list[dict[str, Any]]] | None = None
    save_checkpoint: Callable[[int, int, str | None], dict[str, Any]] | None = None
    load_checkpoint: Callable[[int, int], dict[str, Any]] | None = None

    def execute(self, tool_call: dict[str, Any] | None) -> PlayerToolResult:
        normalized_call = normalize_tool_call(tool_call)
        tool_name = normalized_call["name"]
        if not normalized_call["should_call"] or tool_name not in PLAYER_TOOL_NAMES:
            return self._result(False, tool_name or "unknown", "没有匹配到可用的玩家工具。")
        method = getattr(self, f"_{tool_name}", None)
        if not callable(method):
            return self._result(False, tool_name, f"工具 `{tool_name}` 尚未接入运行时。")
        try:
            return method(normalized_call["arguments"])
        except (ValueError, RuntimeError) as exc:
            return self._result(False, tool_name, str(exc))

    def _result(
        self,
        success: bool,
        tool_name: str,
        text: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> PlayerToolResult:
        return {
            "success": bool(success),
            "tool_name": tool_name,
            "text": str(text or "").strip(),
            "payload": dict(payload or {}),
        }

    def _require_store_and_context(self) -> tuple[Any, PlayerToolContext]:
        store = self.resolve_store()
        if store is None:
            raise RuntimeError("当前未绑定存档存储，无法执行数据库工具。")
        context = self.resolve_context()
        if context.get("user_id") is None:
            raise RuntimeError("当前没有可用的用户上下文。")
        return store, context

    def _require_active_player(self) -> tuple[Any, int, int]:
        store, context = self._require_store_and_context()
        user_id = context.get("user_id")
        player_id = context.get("player_id")
        if user_id is None or player_id is None:
            raise RuntimeError("当前没有激活的存档槽位。")
        return store, int(user_id), int(player_id)

    def _query_inventory(self, arguments: dict[str, Any]) -> PlayerToolResult:
        del arguments
        store, user_id, player_id = self._require_active_player()
        payload = store.query_inventory(user_id=user_id, player_id=player_id)
        items = list(payload.get("items", []))
        text = (
            "当前背包为空。"
            if not items
            else "当前背包：" + _join_fragments(
                [
                    f"{item.get('item_name', '未知物品')} x{int(item.get('quantity', 0) or 0)}"
                    for item in items
                ]
            )
        )
        return self._result(True, "query_inventory", text, payload=payload)

    def _query_player_status(self, arguments: dict[str, Any]) -> PlayerToolResult:
        del arguments
        store, user_id, player_id = self._require_active_player()
        payload = store.query_player_status(user_id=user_id, player_id=player_id)
        attributes = dict(payload.get("attributes", {}))
        fragments: list[str] = []
        for label, key in (
            ("HP", "hp"),
            ("MP", "mp"),
            ("金钱", "money"),
            ("体力", "stamina"),
            ("气运", "luck"),
            ("攻击", "attack"),
            ("防御", "defense"),
            ("境界", "realm"),
        ):
            value = attributes.get(key)
            if value not in (None, ""):
                fragments.append(f"{label} {value}")
        scene_location = str(payload.get("scene", {}).get("location_id", "") or "").strip()
        if scene_location:
            fragments.append(f"地点 {scene_location}")
        text = "当前状态：" + _join_fragments(fragments) if fragments else "当前没有可展示的状态信息。"
        return self._result(True, "query_player_status", text, payload=payload)

    def _query_relation(self, arguments: dict[str, Any]) -> PlayerToolResult:
        store, user_id, player_id = self._require_active_player()
        target_name = str(arguments.get("target_name", "") or "").strip()
        if not target_name:
            raise ValueError("查询关系时必须提供目标角色。")
        payload = store.query_relation(user_id=user_id, player_id=player_id, target_name=target_name)
        matched_name = str(payload.get("display_name", target_name) or target_name)
        score = payload.get("score")
        fragments: list[str] = []
        life_status = str(payload.get("life_status", "") or "").strip()
        if life_status:
            fragments.append(f"状态 {life_status}")
        if payload.get("is_on_stage"):
            fragments.append("当前在场")
        flags = list(payload.get("dialogue_flags", []))
        if flags:
            fragments.append(f"对话标记 {len(flags)} 项")
        suffix = f"（{_join_fragments(fragments)}）" if fragments else ""
        return self._result(
            True,
            "query_relation",
            f"{matched_name} 与玩家的关系分数为 {score}{suffix}。",
            payload=payload,
        )

    def _query_quests(self, arguments: dict[str, Any]) -> PlayerToolResult:
        del arguments
        store, user_id, player_id = self._require_active_player()
        payload = store.query_quests(user_id=user_id, player_id=player_id)
        quests = list(payload.get("quests", []))
        text = (
            "当前没有进行中的任务。"
            if not quests
            else "当前任务：" + _join_fragments(
                [
                    f"{quest.get('title', '未命名任务')} - {quest.get('description', '')}".strip(" -")
                    for quest in quests
                ]
            )
        )
        return self._result(True, "query_quests", text, payload=payload)

    def _save_checkpoint(self, arguments: dict[str, Any]) -> PlayerToolResult:
        store, user_id, player_id = self._require_active_player()
        save_label = str(arguments.get("save_label", "") or "").strip() or None
        payload = (
            self.save_checkpoint(user_id, player_id, save_label)
            if self.save_checkpoint is not None
            else store.save_player_session(
                user_id=user_id,
                player_id=player_id,
                session_snapshot=self.export_session_snapshot(),
                save_kind="manual",
                save_label=save_label,
            )
        )
        player = payload.get("player", {})
        slot_name = str(player.get("slot_name", "") or "").strip() or f"#{player_id}"
        suffix = f"（{save_label}）" if save_label else ""
        return self._result(
            True,
            "save_checkpoint",
            f"已保存到存档 {slot_name}{suffix}。",
            payload=payload,
        )

    def _load_checkpoint(self, arguments: dict[str, Any]) -> PlayerToolResult:
        store, context = self._require_store_and_context()
        user_id = context.get("user_id")
        if user_id is None:
            raise RuntimeError("当前没有可用的用户上下文。")

        player_id_value = arguments.get("player_id")
        slot_name = str(arguments.get("slot_name", "") or "").strip()
        if player_id_value is None and slot_name:
            players = (
                self.list_players_for_user(int(user_id))
                if self.list_players_for_user is not None
                else store.list_players_for_user(int(user_id))
            )
            matched = next(
                (player for player in players if matches_lookup(slot_name, player.get("slot_name", ""))),
                None,
            )
            if matched is None:
                raise ValueError(f"未找到名为 `{slot_name}` 的存档。")
            player_id_value = matched["id"]

        if player_id_value is None:
            player_id_value = context.get("player_id")
        if player_id_value is None:
            raise RuntimeError("当前没有可加载的目标存档。")

        player_id = int(player_id_value)
        if self.load_checkpoint is not None:
            payload = self.load_checkpoint(int(user_id), player_id)
        else:
            payload = store.load_player_session(user_id=int(user_id), player_id=player_id)
            self.load_session_snapshot(payload["snapshot"])
            self.activate_context(int(user_id), player_id)
        loaded_slot_name = str(payload.get("player", {}).get("slot_name", "") or "").strip() or f"#{player_id}"
        return self._result(
            True,
            "load_checkpoint",
            f"已读取存档 {loaded_slot_name}。",
            payload=payload,
        )
