from __future__ import annotations

from typing import Any, Mapping

from CharacterProfile import CharacterProfile, ensure_character_profile
from GameState import GameState
from Memory.context import ActorMemoryContext, LongTermView
from Memory.scene_filter import PresenceGranularity, filter_history_by_presence


class DefaultActorMemoryProvider:
    """默认记忆工厂:读 state + 在场过滤 + 组装三层 DTO。只读,不写 state。"""

    def __init__(
        self,
        *,
        character_profiles: Mapping[str, CharacterProfile],
        recent_rounds: int = 3,
        granularity: PresenceGranularity = "on_stage",
    ) -> None:
        # 注入角色人设表(只读引用)与在场过滤参数。
        self._character_profiles = character_profiles
        self._recent_rounds = recent_rounds
        self._granularity = granularity

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

        # 长期:直接复用角色已压缩的记忆字段(不重新压缩)。
        # 拷成新 list 只是隔离外层增删,元素仍是原引用(只读投影)。
        memory = state["characters"].get(actor_id, {}).get("memory", {})
        long_term = LongTermView(
            consolidated=list(memory.get("consolidated_memory", [])),
            long_term=list(memory.get("long_term_memory", [])),
            pinned=list(memory.get("pinned_long_term_memory", [])),
        )

        return ActorMemoryContext(
            actor_id=actor_id,
            persona=persona,
            short_term=short_term,
            long_term=long_term,
            retrieved=self.retrieve(actor_id, "", user_id="", player_id=""),
        )

    def retrieve(
        self,
        actor_id: str,
        query: str,
        *,
        user_id: str,
        player_id: str,
        top_k: int = 5,
    ) -> list[Any]:
        # 本轮占位:Recall 检索层做好后填实(带 u{user}:p{player}: 租户前缀,失败降级为空)。
        return []
