"""ActorCreateAgent 类拆分产物。

本文件是 `actor_create_agent.py` 拆分后的第 4 个模块，仅保留
`ActorCreateAgent` 类本体。配套模块分工如下：

- `Actor.ActorCreateSchema`：JSON Schema、容量常量 (MAX_L1_AGENTS/
  MAX_STORY_CHARACTERS) 及 BACKSTORY_RELATION_HINTS.
- `Actor.ActorCreatePrompt`：系统提示词 ACTOR_CREATE_SYSTEM_PROMPT。
- `Actor.ActorCreateHeuristics`：`_` 前缀的启发式辅助函数（分配层级、
  分配章节、构造 character_id 等）。

本模块只负责组织 Prompt、调用 LLM、并把返回结果归一化为
CharacterProfile 集合，方法体一字未改（仅追加中文 docstring）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from BaseAgent import AgentMessage, BaseAgent
from CharacterProfile import (
    DEFAULT_CURRENT_REALM,
    DEFAULT_MAIN_TECHNIQUE,
    DEFAULT_SPIRITUAL_ROOT,
    ensure_character_profile,
    normalize_l1_agent_profile,
    normalize_layer_assignment,
    normalize_relationship_mapping,
)
from CharacterRosterTools import CharacterRosterToolRuntime
from PromptUtils import render_json_instruction
from StoryStateUtils import (
    clean_str_list,
    clean_text,
    resolve_player_character_id,
    serialize_story_cast_member,
    story_outline_entries,
)
from StoryToolContext import build_story_tool_prompt_context

from Actor.ActorCreatePrompt import ACTOR_CREATE_SYSTEM_PROMPT
from Actor.ActorCreateSchema import (
    ACTOR_CREATE_RESPONSE_SCHEMA,
    CONTEXTUAL_ACTOR_RESPONSE_SCHEMA,
    MAX_L1_AGENTS,
    MAX_STORY_CHARACTERS,
)
from Actor.ActorCreateHeuristics import (
    _assign_chapter_ids,
    _build_character_id,
    _build_layer_assignment_seed,
    _resolve_effective_roster_counts,
    _resolve_story_agent_type,
    _respect_agent_layer_limits,
    _respect_player_bound_capacity,
)

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile
    from GameState import GameState
    from SceneConfig import SceneConfig


class ActorCreateAgent(BaseAgent):
    """负责生成/维护故事支线角色的 Agent。

    职责概览：

    - ``build_instruction``：构造"补齐故事支线阵容"的完整指令，
      作为主要 sync 路径的 Prompt。
    - ``build_contextual_actor_instruction``：场景 handoff 时，
      临场生成单个可立即上台的 ActorAgent 的 Prompt。
    - ``normalize_supporting_cast``：把 LLM 返回的 characters 列表
      归一化为 CharacterProfile 字典（含容量、层级、章节等约束）。
    - ``normalize_contextual_actor``：单角色版归一化，返回单个
      CharacterProfile 或 None。
    - ``sync_supporting_cast``：build_instruction → LLM → normalize
      的一站式入口。
    - ``create_contextual_actor``：build_contextual_actor_instruction
      → LLM → normalize_contextual_actor 的一站式入口。
    """

    def __init__(self, **kwargs: Any) -> None:
        # 初始化基础 Agent，并可选绑定 CharacterRosterToolRuntime。
        character_roster_tool_runtime = kwargs.pop("character_roster_tool_runtime", None)
        super().__init__(
            system_prompt=ACTOR_CREATE_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.45),
            max_tokens=kwargs.pop("max_tokens", 1800),
            **kwargs,
        )
        self.character_roster_tool_runtime: CharacterRosterToolRuntime | None = character_roster_tool_runtime

    def bind_character_roster_tool_runtime(
        self,
        tool_runtime: CharacterRosterToolRuntime | None,
    ) -> None:
        # 在运行时绑定/替换 CharacterRosterToolRuntime。
        self.character_roster_tool_runtime = tool_runtime

    def build_instruction(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: CharacterRosterToolRuntime | None = None,
        resolved_snapshots: dict[str, Any] | None = None,
    ) -> str:
        """构造 supporting_cast 主指令 Prompt。

        输入：当前 ``game_state``、``scene_config``、已有 ``character_profiles``、
        容量上限，以及可选的 roster 快照 / 工具运行时。

        四段构造：

        1. 玩家画像 + 背景（player_profile + background 字段）。
        2. ``outline_entries``：从 plot.story_outline 抽取章节骨架。
        3. ``character_roster_snapshot``：通过
           ``build_story_tool_prompt_context`` 注入角色花名册上下文。
        4. ``render_json_instruction``：包上 JSON 硬约束的最终指令。

        返回：拼装好的字符串指令（供 ``command`` 使用），本方法本身
        不直接产生 ``list[AgentMessage]``——历史消息由调用方拼接。
        """
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        existing_l1_count, existing_actor_count = _resolve_effective_roster_counts(
            character_profiles,
            character_roster_snapshot,
        )
        outline = [
            {
                "chapter_id": clean_text(chapter.get("chapter_id")),
                "title": clean_text(chapter.get("title")),
                "main_goal": clean_text(chapter.get("main_goal")),
                "summary": clean_text(chapter.get("summary")),
            }
            for chapter in game_state["plot"].get("story_outline", [])
            if isinstance(chapter, Mapping)
        ]
        existing_cast = [
            serialize_story_cast_member(character_id, profile)
            for character_id, profile in character_profiles.items()
        ]
        payload = {
            "creative_goal": (
                "Supplement the cast so the story outline and current/future chapters have concrete interactive agents "
                "with an intentional L1 layer assignment."
            ),
            "constraints": {
                "max_player_bound_characters": max_total_characters,
                "existing_player_bound_character_count": existing_l1_count,
                "max_new_player_bound_characters": max(
                    0,
                    max_total_characters - existing_l1_count,
                ),
                "base_actor_templates_are_unbounded": True,
                "has_story_outline": bool(outline),
                "instruction_when_no_outline": (
                    "Only return characters that the player's background clearly implies."
                ),
                "instruction_when_outline_exists": (
                    "Create or refine only the minimum supporting cast needed for the outlined chapters."
                ),
                "player_backstory_floor_rule": (
                    "Any role clearly mentioned in the player background must be assigned as L1, never treated as a discardable extra."
                ),
                "L1_rule": (
                    "Use L1 for long-term mainline roles, deep bonds, irreplaceable rivals, blood/fate ties, or characters expected to carry major turns."
                ),
                "actor_rule": (
                    "Use actor for functional or atmospheric roles that can be reused as a shared template and do not need long-horizon autonomy."
                ),
                "max_l1_agents": MAX_L1_AGENTS,
                "existing_l1_agents": existing_l1_count,
                "existing_actor_templates": existing_actor_count,
            },
            "player_character_id": player_id,
            "player_profile": {
                "name": clean_text(player_profile.get("name", player_id)),
                "background": clean_text(player_profile.get("background", "")),
                "race": clean_text(player_profile.get("race", "")),
                "spiritual_root": clean_text(
                    player_profile.get("spiritual_root", ""),
                    DEFAULT_SPIRITUAL_ROOT,
                ),
                "realm": clean_text(player_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                "main_technique": clean_text(
                    player_profile.get("main_technique", ""),
                    DEFAULT_MAIN_TECHNIQUE,
                ),
            },
            "story": {
                "story_premise": clean_text(game_state["plot"].get("story_premise", "")),
                "exploration_drive": clean_text(game_state["plot"].get("exploration_drive", "")),
                "current_chapter_id": clean_text(game_state["plot"].get("chapter_id", "")),
                "current_chapter_title": clean_text(game_state["plot"].get("current_chapter_title", "")),
                "current_chapter_overview": clean_text(
                    game_state["plot"].get("current_chapter_overview", "")
                ),
                "story_outline": outline,
            },
            "opening_scene_seed": {
                "scene_id": clean_text(game_state["plot"].get("scene_id", "")),
                "location_id": clean_text(game_state["scene"].get("location_id", "")),
                "time_tag": clean_text(game_state["scene"].get("time_tag", "")),
                "default_on_stage": clean_str_list(scene_config.get("default_on_stage", [])),
            },
            **build_story_tool_prompt_context(
                task="supporting_cast",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                resolved_snapshots=resolved_snapshots,
                cast_size=len(existing_cast),
                supporting_cast_count=max(0, len(existing_cast) - 1),
                outline_exists=bool(outline),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "existing_cast": existing_cast,
        }
        return render_json_instruction(
            "Return only supplemental character settings as strict JSON. "
            "Do not echo the full cast. Reuse existing supporting ids when refining already generated characters. "
            "Use lowercase ASCII snake_case ids whenever you create a new id. "
            "Every character must include `agent_type` and `layer_assignment`. "
            "If `agent_type` is `L1`, include a complete `l1_profile`. "
            "For reusable base actors, set `agent_type` to `actor` and include a practical `occupation`.",
            payload,
        )

    def build_contextual_actor_instruction(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        destination: str,
        objective: str,
        reward_item: str,
        player_intent: str,
        character_roster_snapshot: Mapping[str, Any] | None = None,
        character_roster_tool_runtime: CharacterRosterToolRuntime | None = None,
        resolved_snapshots: dict[str, Any] | None = None,
    ) -> str:
        """临场生成单个 ActorAgent 的指令构造路径。

        与 ``build_instruction`` 的差异在于这是"场景 handoff 时补角色"
        的通道：当玩家的下一步动作需要一个新面孔（守卫、向导、摊贩……）
        即时上台，本方法拼装一份只允许产出**恰好一个**角色的 Prompt，
        通过 ``immediate_scene_need``（destination/objective/reward_item/
        player_intent）把当下的场景压力显式告诉 LLM，同时仍然允许它选择
        actor / L1 两种档位，只不过默认应偏向可复用的 actor 模板。
        """
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        existing_cast = [
            serialize_story_cast_member(character_id, profile)
            for character_id, profile in character_profiles.items()
        ]
        payload = {
            "creative_goal": (
                "Create exactly one interactive profile who can be activated in the very next scene "
                "to respond to the player's immediate intent. This ActorAgent may be any fitting archetype: "
                "disciple, guard, attendant, elder, vendor, witness, gatekeeper, rival, guide, or another scene-appropriate role."
            ),
            "constraints": {
                "create_exactly_one_actor": True,
                "actor_must_not_be_player": True,
                "actor_should_be_usable_immediately": True,
                "actor_type_is_not_fixed": True,
                "choose_L1_only_when_the_scene_introduces_a_major_long_arc_role": True,
            },
            "player_character_id": player_id,
            "player_profile": {
                "name": clean_text(player_profile.get("name", player_id)),
                "background": clean_text(player_profile.get("background", "")),
                "spiritual_root": clean_text(
                    player_profile.get("spiritual_root", ""),
                    DEFAULT_SPIRITUAL_ROOT,
                ),
                "realm": clean_text(player_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                "main_technique": clean_text(
                    player_profile.get("main_technique", ""),
                    DEFAULT_MAIN_TECHNIQUE,
                ),
            },
            "immediate_scene_need": {
                "destination": clean_text(destination),
                "objective": clean_text(objective),
                "reward_item": clean_text(reward_item),
                "player_intent": clean_text(player_intent),
                "current_location": clean_text(game_state["scene"].get("location_id", "")),
            },
            "story": {
                "chapter_id": clean_text(game_state["plot"].get("chapter_id", "")),
                "chapter_title": clean_text(game_state["plot"].get("current_chapter_title", "")),
                "chapter_goal": clean_text(game_state["plot"].get("chapter_goal", "")),
                "story_premise": clean_text(game_state["plot"].get("story_premise", "")),
                "exploration_drive": clean_text(game_state["plot"].get("exploration_drive", "")),
            },
            "scene_config": {
                "scene_id": clean_text(scene_config.get("scene_id", "")),
                "default_location_id": clean_text(scene_config.get("default_location_id", "")),
            },
            **build_story_tool_prompt_context(
                task="contextual_actor",
                game_state=game_state,
                character_profiles=character_profiles,
                character_roster_snapshot=character_roster_snapshot,
                character_roster_tool_runtime=character_roster_tool_runtime,
                resolved_snapshots=resolved_snapshots,
                cast_size=len(existing_cast),
                supporting_cast_count=max(0, len(existing_cast) - 1),
                on_stage_count=len(game_state["scene"].get("on_stage", [])),
                history_count=len(game_state.get("history", [])),
                completed_chapter_count=len(game_state["plot"].get("completed_chapters", [])),
            ),
            "existing_cast": existing_cast,
        }
        return render_json_instruction(
            "Return exactly one contextual ActorAgent under the `actor` field as strict JSON. "
            "This actor should exist to make the next scene playable and interactive. "
            "Do not generate multiple characters, and do not write scene prose or dialogue. "
            "Choose between `actor` and `L1` using the same story-weight rules. "
            "Always include `layer_assignment`, plus the matching `l1_profile` when applicable.",
            payload,
        )

    def normalize_supporting_cast(
        self,
        output: Mapping[str, Any] | None,
        *,
        game_state: "GameState",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, "CharacterProfile"]:
        """把 LLM 返回的 characters 列表归一化为 CharacterProfile 字典。

        每个候选角色遵循下列 7 步流程：

        1. ``_build_character_id`` —— 由 raw_id / name / 现有 profile
           冲突集合决定最终 id（保证 lowercase snake_case & 唯一）。
        2. **跳过既有非本 agent 生成的角色** —— 若 ``character_id`` 已在
           ``character_profiles`` 中，且其 ``profile_source`` 不是
           ``"actor_create_agent"``，则本轮不覆盖它，直接 continue。
        3. ``_build_layer_assignment_seed`` —— 汇总 story_role / persona /
           planned_chapter 等信号，产出层级判定种子。
        4. ``_resolve_story_agent_type`` —— 根据种子 + 章节规划得出
           ``actor / L1`` 两档中的一档。
        5. ``_respect_agent_layer_limits`` + ``_respect_player_bound_capacity``
           —— 依次夹紧 L1 上限、以及 player-bound 总容量。
        6. ``_assign_chapter_ids`` —— outline 存在但角色未提供
           ``planned_chapter_ids`` 时，从当前章节顺推补齐。
        7. 按最终 agent_type 填充 ``l1_profile``，
           并写入 ``profile_source="actor_create_agent"`` 作为持久化标记。

        **注意：``"actor_create_agent"`` 字符串是持久化数据中的
        profile_source 标记值，读写两处必须保持原样，任何字面改动都会
        破坏后续 agent 判定"这条数据是否由我生成、可被覆盖"的语义。**
        """
        player_id = resolve_player_character_id(game_state, character_profiles)
        player_profile = character_profiles.get(player_id, {})
        player_background = clean_text(player_profile.get("background", ""))
        outline_ids = [
            clean_text(chapter.get("chapter_id"))
            for chapter in story_outline_entries(game_state)
            if clean_text(chapter.get("chapter_id"))
        ]
        current_chapter_id = clean_text(game_state["plot"].get("chapter_id"))
        start_index = outline_ids.index(current_chapter_id) if current_chapter_id in outline_ids else 0
        existing_l1_count, _ = _resolve_effective_roster_counts(
            character_profiles,
            character_roster_snapshot,
        )
        new_l1_count = 0
        normalized: dict[str, CharacterProfile] = {}
        used_ids: set[str] = set()

        for fallback_index, raw_character in enumerate(output.get("characters", []) if output else [], start=1):
            if not isinstance(raw_character, Mapping):
                continue

            raw_id = clean_text(raw_character.get("character_id", ""))
            name = clean_text(raw_character.get("name", ""))
            if not name:
                continue

            character_id = _build_character_id(
                raw_id=raw_id,
                name=name,
                character_profiles=character_profiles,
                used_ids=used_ids,
                fallback_index=fallback_index,
            )
            existing_profile = character_profiles.get(character_id, {})
            existing_source = clean_text(existing_profile.get("profile_source", ""))
            if character_id in character_profiles and existing_source != "actor_create_agent":
                continue

            story_role = clean_text(raw_character.get("story_role", "")) or clean_text(
                existing_profile.get("story_role", "")
            )
            persona = clean_str_list(raw_character.get("persona", [])) or clean_str_list(
                existing_profile.get("persona", [])
            )
            if not persona:
                persona = [story_role or "supporting cast", "watchful", "decisive"]

            base_style = clean_text(raw_character.get("base_style", "")) or clean_text(
                existing_profile.get("base_style", "")
            )
            if not base_style:
                base_style = story_role or "measured and vivid"

            background = clean_text(raw_character.get("background", "")) or clean_text(
                existing_profile.get("background", "")
            )
            if not background:
                background = f"{name} is a supporting figure in the current story arc."

            secrets = clean_str_list(raw_character.get("secrets", [])) or clean_str_list(
                existing_profile.get("secrets", [])
            )

            provided_chapter_ids = [
                chapter_id
                for chapter_id in clean_str_list(raw_character.get("planned_chapter_ids", []))
                if chapter_id in outline_ids
            ]
            planned_chapter_count = int(raw_character.get("planned_chapter_count", 0) or 0)
            if planned_chapter_count <= 0:
                planned_chapter_count = int(existing_profile.get("planned_chapter_count", 0) or 0)
            if planned_chapter_count <= 0:
                planned_chapter_count = max(1, len(provided_chapter_ids))
            if outline_ids and not provided_chapter_ids:
                provided_chapter_ids = _assign_chapter_ids(
                    outline_ids=outline_ids,
                    start_index=start_index,
                    planned_chapter_count=planned_chapter_count,
                )
            if provided_chapter_ids:
                planned_chapter_count = max(planned_chapter_count, len(provided_chapter_ids))

            layer_assignment_seed = _build_layer_assignment_seed(
                raw_character,
                existing_profile,
                player_background=player_background,
                planned_chapter_count=planned_chapter_count,
                planned_chapter_ids=provided_chapter_ids,
            )
            resolved_agent_type = _resolve_story_agent_type(
                raw_character,
                existing_profile,
                layer_assignment_seed=layer_assignment_seed,
                planned_chapter_count=planned_chapter_count,
                planned_chapter_ids=provided_chapter_ids,
            )
            layer_assignment = normalize_layer_assignment(
                layer_assignment_seed,
                agent_type=resolved_agent_type,  # type: ignore[arg-type]
                fallback_reason=clean_text(layer_assignment_seed.get("assignment_reason", "")),
            )
            resolved_agent_type = _respect_agent_layer_limits(
                resolved_agent_type=resolved_agent_type,
                layer_assignment=layer_assignment,
                existing_l1_count=existing_l1_count,
                new_l1_count=new_l1_count,
            )
            resolved_agent_type = _respect_player_bound_capacity(
                resolved_agent_type=resolved_agent_type,
                layer_assignment=layer_assignment,
                max_total_characters=max_total_characters,
                existing_l1_count=existing_l1_count,
                new_l1_count=new_l1_count,
            )
            layer_assignment = normalize_layer_assignment(
                layer_assignment,
                agent_type=resolved_agent_type,  # type: ignore[arg-type]
                fallback_reason=clean_text(layer_assignment.get("assignment_reason", "")),
            )

            normalized_profile = ensure_character_profile(
                {
                    "character_id": character_id,
                    "name": name,
                    "agent_type": resolved_agent_type,
                    "story_layer": resolved_agent_type if resolved_agent_type == "L1" else "actor",
                    "occupation": clean_text(raw_character.get("occupation", ""))
                    or clean_text(existing_profile.get("occupation", "")),
                    "persona": persona,
                    "base_style": base_style,
                    "base_relationship": normalize_relationship_mapping(raw_character.get("base_relationship", {}))
                    or dict(existing_profile.get("base_relationship", {})),
                    "secrets": secrets,
                    "background": background,
                    "story_role": story_role,
                    "introduction_hint": clean_text(raw_character.get("introduction_hint", ""))
                    or clean_text(existing_profile.get("introduction_hint", "")),
                    "planned_chapter_count": planned_chapter_count,
                    "planned_chapter_ids": provided_chapter_ids,
                    "profile_source": "actor_create_agent",
                    "layer_assignment": layer_assignment,
                    "spiritual_root": clean_text(
                        raw_character.get("spiritual_root", ""),
                        clean_text(existing_profile.get("spiritual_root", ""), DEFAULT_SPIRITUAL_ROOT),
                    ),
                    "realm": clean_text(
                        raw_character.get("realm", ""),
                        clean_text(existing_profile.get("realm", ""), DEFAULT_CURRENT_REALM),
                    ),
                    "main_technique": clean_text(
                        raw_character.get("main_technique", ""),
                        clean_text(existing_profile.get("main_technique", ""), DEFAULT_MAIN_TECHNIQUE),
                    ),
                    **(
                        {
                            "l1_profile": normalize_l1_agent_profile(
                                raw_character.get("l1_profile", existing_profile.get("l1_profile", {})),
                                fallback_story_role=story_role,
                                fallback_persona=persona,
                                fallback_background=background,
                            )
                        }
                        if resolved_agent_type == "L1"
                        else {}
                    ),
                },
                character_id=character_id,
            )

            for optional_field in ("gender", "race"):
                value = clean_text(raw_character.get(optional_field, "")) or clean_text(
                    existing_profile.get(optional_field, "")
                )
                if value:
                    normalized_profile[optional_field] = value

            normalized[character_id] = normalized_profile
            if resolved_agent_type == "L1":
                new_l1_count += 1
            used_ids.add(character_id)

        return normalized

    def normalize_contextual_actor(
        self,
        output: Mapping[str, Any] | None,
        *,
        game_state: "GameState",
        character_profiles: dict[str, "CharacterProfile"],
        max_total_characters: int = MAX_STORY_CHARACTERS,
        character_roster_snapshot: Mapping[str, Any] | None = None,
    ) -> "CharacterProfile | None":
        # 单角色归一化：把 output["actor"] 包成 characters 列表复用主流程。
        if not output or not isinstance(output.get("actor"), Mapping):
            return None

        normalized = self.normalize_supporting_cast(
            {"characters": [dict(output.get("actor", {}))]},
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=character_roster_snapshot,
        )
        return next(iter(normalized.values()), None) if normalized else None

    def sync_supporting_cast(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        history: list[AgentMessage] | None = None,
        max_total_characters: int = MAX_STORY_CHARACTERS,
    ) -> dict[str, "CharacterProfile"]:
        # 一站式：build_instruction → command → normalize_supporting_cast。
        resolved_snapshots: dict[str, Any] = {}
        instruction = self.build_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            resolved_snapshots=resolved_snapshots,
        )
        result = self.command(
            instruction=instruction,
            history=history,
            response_format=ACTOR_CREATE_RESPONSE_SCHEMA,
        )
        return self.normalize_supporting_cast(
            result,
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=resolved_snapshots.get("character_roster_snapshot"),
        )

    def create_contextual_actor(
        self,
        *,
        game_state: "GameState",
        scene_config: "SceneConfig",
        character_profiles: dict[str, "CharacterProfile"],
        destination: str,
        objective: str,
        reward_item: str,
        player_intent: str,
        history: list[AgentMessage] | None = None,
        max_total_characters: int = MAX_STORY_CHARACTERS,
    ) -> "CharacterProfile | None":
        # 一站式：临场生成单个 ActorAgent 并归一化。
        resolved_snapshots: dict[str, Any] = {}
        instruction = self.build_contextual_actor_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            destination=destination,
            objective=objective,
            reward_item=reward_item,
            player_intent=player_intent,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            resolved_snapshots=resolved_snapshots,
        )
        result = self.command(
            instruction=instruction,
            history=history,
            response_format=CONTEXTUAL_ACTOR_RESPONSE_SCHEMA,
        )
        return self.normalize_contextual_actor(
            result,
            game_state=game_state,
            character_profiles=character_profiles,
            max_total_characters=max_total_characters,
            character_roster_snapshot=resolved_snapshots.get("character_roster_snapshot"),
        )


__all__ = ["ActorCreateAgent", "MAX_L1_AGENTS", "MAX_STORY_CHARACTERS"]
