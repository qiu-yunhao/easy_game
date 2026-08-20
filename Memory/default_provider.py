from __future__ import annotations

from typing import Any, Mapping, Optional

from CharacterProfile import CharacterProfile, ensure_character_profile
from GameState import GameState
from Memory.context import ActorMemoryContext
from Memory.scene_filter import PresenceGranularity, filter_history_by_presence


class DefaultActorMemoryProvider:
    """默认记忆工厂:读 state + 在场过滤 + 组装三层 DTO。只读,不写 state。

    可选注入 recall_service + 租户(user_id/player_id)后,角色说话时会按当前情景
    语义检索本局的相关过往,填入 retrieved。未注入或检索失败时优雅降级为空,
    绝不打断对话链路。租户随会话激活的存档变动,通过 set_tenant 热更新。
    """

    def __init__(
        self,
        *,
        character_profiles: Mapping[str, CharacterProfile],
        recent_rounds: int = 3,
        granularity: PresenceGranularity = "on_stage",
        recall_service: Any = None,
        user_id: Optional[int] = None,
        player_id: Optional[int] = None,
    ) -> None:
        # 注入角色人设表(只读引用)与在场过滤参数。
        self._character_profiles = character_profiles
        self._recent_rounds = recent_rounds
        self._granularity = granularity
        # 回忆检索:service 与租户均可选,缺任一即降级(不检索)。
        self.recall_service = recall_service
        self._user_id = user_id
        self._player_id = player_id

    def set_tenant(self, *, user_id: Optional[int], player_id: Optional[int]) -> None:
        # 会话切换存档时更新当前租户(provider 长生命周期,租户随激活玩家变)。
        self._user_id = user_id
        self._player_id = player_id

    def build(self, actor_id: str, state: GameState) -> ActorMemoryContext:
        # 人设:命中则复用现有 CharacterProfile;未命中给合法空壳兜底,
        # 保住下游 .get("memory_profile") / 播种 / agent_contract 字段访问。
        persona: CharacterProfile = self._character_profiles.get(actor_id) or ensure_character_profile(None)

        # 短期:按「角色当时是否在场」过滤 history,再取最近数轮。
        short_term = filter_history_by_presence(
            state["history"],
            actor_id=actor_id,
            current_location_id=state["scene"].get("location_id", ""),
            recent_rounds=self._recent_rounds,
            granularity=self._granularity,
        )

        # 检索词 = 当前 intent + 最近对话;失败/未启用降级为空。
        query = self._compose_recall_query(actor_id, state, short_term)

        return ActorMemoryContext(
            actor_id=actor_id,
            persona=persona,
            short_term=short_term,
            retrieved=self.retrieve(
                actor_id, query, user_id=self._user_id, player_id=self._player_id
            ),
        )

    def _compose_recall_query(
        self, actor_id: str, state: GameState, short_term: list[Any]
    ) -> str:
        # query = 该 actor 当前意图 + 最近 1~2 条对话/旁白文本,拼成一句检索词。
        parts: list[str] = []
        intent = state["characters"].get(actor_id, {}).get("intent", "")
        if isinstance(intent, str) and intent.strip():
            parts.append(intent.strip())
        for entry in short_term[-2:]:
            content = entry.get("content", "") if isinstance(entry, Mapping) else ""
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
        return " ".join(parts)

    def retrieve(
        self,
        actor_id: str,
        query: str,
        *,
        user_id: Optional[int],
        player_id: Optional[int],
        top_k: int = 5,
    ) -> list[Any]:
        # 未启用回忆 / 租户缺失 / query 为空 → 优雅降级,不调 service。
        if self.recall_service is None or user_id is None or player_id is None:
            return []
        if not query.strip():
            return []
        # 检索失败绝不能打断对话:整段兜底为空。
        try:
            return self.recall_service.query_recall(
                query, user_id=user_id, player_id=player_id, top_k=top_k
            )
        except Exception:  # noqa: BLE001 - 任何检索后端异常都降级为空
            return []
