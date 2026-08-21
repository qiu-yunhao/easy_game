"""ActorCreateHeuristics —— ActorCreate 的启发式规则集。

本模块集中了 `ActorCreateAgent` 在把 LLM 原始响应"落地"成
`CharacterProfile` 时使用的所有**纯函数级**启发式规则，覆盖四类：

1. **ID / 章节分配**：`_build_character_id`, `_assign_chapter_ids`。
2. **玩家背景保护判定**：`_contains_backstory_signal`,
   `_infer_backstory_priority`（触发容量守卫中的"背景保护"豁免）。
3. **layer_assignment 与 agent_type 推断**：
   `_build_layer_assignment_seed`（explicit > existing > 推断默认 合并），
   `_resolve_story_agent_type`（背景/显式/长期或多章 两路径），
   `_count_story_layers`, `_resolve_effective_roster_counts`。
4. **容量守卫（下调 agent_type 到当前预算内）**：
   `_respect_agent_layer_limits`（按 MAX_L1_AGENTS 下调
   L1→actor，背景保护豁免），
   `_respect_player_bound_capacity`（按 max_total_characters 再守卫）。

约定：函数都是包内私有（`_` 前缀），仅 `ActorCreateAgent` 经 `__all__`
导入使用；函数体一字未改，仅补充中文 docstring。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from Actor.ActorCreateSchema import (
    BACKSTORY_RELATION_HINTS,
    MAX_L1_AGENTS,
)
from StoryStateUtils import clean_text

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


__all__ = [
    "_build_character_id",
    "_assign_chapter_ids",
    "_contains_backstory_signal",
    "_infer_backstory_priority",
    "_build_layer_assignment_seed",
    "_resolve_story_agent_type",
    "_count_story_layers",
    "_resolve_effective_roster_counts",
    "_respect_agent_layer_limits",
    "_respect_player_bound_capacity",
]


def _build_character_id(
    *,
    raw_id: str,
    name: str,
    character_profiles: dict[str, "CharacterProfile"],
    used_ids: set[str],
    fallback_index: int,
) -> str:
    """为新角色决定一个稳定、不冲突的 character_id。

    调用时机：`ActorCreateAgent` 处理 LLM 返回的每个 raw_character 时，
    第一步就是通过本函数确定该角色最终使用的 id，避免生成期间和已有
    profile 表撞车。

    优先级（自上而下）：
        1. **raw_id 复用**：若 raw_id 已存在于 character_profiles，
           说明是"更新已有角色"，直接沿用。
        2. **姓名匹配**：若 raw_id 没命中但 name 已经出现在某个已有
           profile 的 name 字段（去空白后精确相等），复用那个已有 id。
        3. **raw_id 规范化**：把 raw_id 小写化，非 `[a-z0-9]` 全替换为
           `_`，去掉首尾 `_`，作为候选。
        4. **name 规范化**：raw_id 规范化后为空时，退化用 name 做同样处理。
        5. **fallback**：仍为空时，用 `supporting_{fallback_index}`。
        6. **去重后缀**：candidate 已被占用（character_profiles 或
           used_ids）时，追加 `_2 / _3 / ...` 直到唯一。

    返回：一个在当前 character_profiles ∪ used_ids 中唯一的字符串 id。
    """
    if raw_id and raw_id in character_profiles:
        return raw_id
    if name:
        for character_id, profile in character_profiles.items():
            if clean_text(profile.get("name", "")) == name:
                return character_id

    candidate = re.sub(r"[^a-z0-9]+", "_", raw_id.lower()).strip("_")
    if not candidate:
        candidate = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not candidate:
        candidate = f"supporting_{fallback_index}"

    resolved = candidate
    suffix = 2
    while resolved in character_profiles or resolved in used_ids:
        resolved = f"{candidate}_{suffix}"
        suffix += 1
    return resolved


def _assign_chapter_ids(
    *,
    outline_ids: list[str],
    start_index: int,
    planned_chapter_count: int,
) -> list[str]:
    """把"计划出场章节数"映射到具体的大纲章节 id 列表。

    调用时机：为角色计算 `planned_chapter_ids` 时使用；outline_ids 是
    章节 id 的有序列表，start_index 是首选起点。

    分配规则：从 `outline_ids[start_index:]` 按顺序取（去重），直到累计
    `planned_chapter_count` 个或 outline 耗尽；若不够则从头再扫一遍补齐。
    边界：outline_ids 为空或 count<=0 时返回 []；start_index 截断到
    `[0, len(outline_ids)-1]`。返回长度 <= count 的章节 id 列表（保序）。
    """
    if not outline_ids or planned_chapter_count <= 0:
        return []

    chapter_ids: list[str] = []
    bounded_start = max(0, min(start_index, len(outline_ids) - 1))
    for chapter_id in outline_ids[bounded_start:]:
        if chapter_id not in chapter_ids:
            chapter_ids.append(chapter_id)
        if len(chapter_ids) >= planned_chapter_count:
            break

    if len(chapter_ids) < planned_chapter_count:
        for chapter_id in outline_ids:
            if chapter_id not in chapter_ids:
                chapter_ids.append(chapter_id)
            if len(chapter_ids) >= planned_chapter_count:
                break

    return chapter_ids


def _contains_backstory_signal(player_background: str, candidate_text: str) -> bool:
    """粗匹配 candidate_text 是否与玩家背景 `player_background` 相关。

    调用时机：`_infer_backstory_priority` 内对角色 name/story_role/
    introduction_hint 等字段逐一探测时使用。

    匹配规则（任一为真即命中）：candidate 长度 >=2 且是 background 的
    子串；或 `BACKSTORY_RELATION_HINTS`（师妹/师父/母亲…）中某个 hint
    同时出现在 candidate 与 background 中。background 或 candidate
    清洗后为空则返回 False。返回 True 表示该 candidate 可视为玩家背景
    中提到的角色/关系。
    """
    background = clean_text(player_background)
    candidate = clean_text(candidate_text)
    if not background or not candidate:
        return False
    if len(candidate) >= 2 and candidate in background:
        return True
    return any(hint in candidate and hint in background for hint in BACKSTORY_RELATION_HINTS)


def _infer_backstory_priority(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    player_background: str,
) -> bool:
    """判定该角色是否属于"玩家背景保护"范畴。

    调用时机：`_build_layer_assignment_seed` 内合并 layer_assignment
    字段时首先调用，用于填充 `mentioned_in_player_backstory`，并影响
    后续 `_resolve_story_agent_type` 与两个容量守卫的豁免逻辑。

    判定：优先取 raw / existing 的 `layer_assignment.mentioned_in_player
    _backstory`（若为 bool，raw 优先）；否则对 raw/existing 的 name、
    story_role、introduction_hint 逐个调用 `_contains_backstory_signal`,
    任一命中即 True，都未命中则 False。
    """
    for source in (raw_character.get("layer_assignment"), existing_profile.get("layer_assignment")):
        if isinstance(source, Mapping) and isinstance(source.get("mentioned_in_player_backstory"), bool):
            return bool(source.get("mentioned_in_player_backstory"))

    for candidate_text in (
        raw_character.get("name", ""),
        raw_character.get("story_role", ""),
        raw_character.get("introduction_hint", ""),
        existing_profile.get("name", ""),
        existing_profile.get("story_role", ""),
        existing_profile.get("introduction_hint", ""),
    ):
        if _contains_backstory_signal(player_background, clean_text(candidate_text)):
            return True
    return False


def _build_layer_assignment_seed(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    player_background: str,
    planned_chapter_count: int,
    planned_chapter_ids: list[str],
) -> dict[str, Any]:
    """合并出角色的 `layer_assignment` 种子字典（供后续 schema 校验）。

    调用时机：`ActorCreateAgent` 为每个 raw_character 组装最终
    CharacterProfile 前，先用本函数得到一个字段齐全的 layer_assignment
    seed，再交给 `_resolve_story_agent_type` 决定 agent_type。

    合并规则（**explicit > existing > 推断默认**）：
        - `mentioned_in_player_backstory`：委托给 `_infer_backstory_priority`。
        - `plot_significance`：优先取 explicit，其次 existing，默认
          `"supporting"`；仅接受 `{core, supporting, replaceable}`，
          非法值统一回退为 `"supporting"`。
        - `relationship_depth`：优先 explicit，其次 existing，默认按
          是否被背景提及取 `functional` / `unknown`；仅接受
          `{deep, functional, unknown}`。
        - `long_term_plot_significance`：explicit / existing 若是 bool
          则直接采纳；否则由 `planned_chapter_count >= 2` 或
          `len(planned_chapter_ids) >= 2` 推断。
        - `assignment_reason`：优先 explicit，其次 existing；为空时按
          `(mentioned, long_term)` 组合派生（player_backstory_long_term /
          player_backstory_interactive_floor / core_plot_weight /
          supporting_plot_need）。
        - `can_promote_to_l1`：explicit / existing 若是 bool 则采纳；
          否则默认 True 的条件是（背景提及 or 长期戏份 or supporting）。

    返回：一个包含以上 6 个字段的 dict，字段类型固定。
    """
    explicit_assignment = raw_character.get("layer_assignment")
    explicit_assignment = explicit_assignment if isinstance(explicit_assignment, Mapping) else {}
    existing_assignment = existing_profile.get("layer_assignment")
    existing_assignment = existing_assignment if isinstance(existing_assignment, Mapping) else {}

    mentioned_in_player_backstory = _infer_backstory_priority(
        raw_character,
        existing_profile,
        player_background=player_background,
    )
    plot_significance = clean_text(
        explicit_assignment.get("plot_significance", ""),
        clean_text(existing_assignment.get("plot_significance", ""), "supporting"),
    ).lower()
    if plot_significance not in {"core", "supporting", "replaceable"}:
        plot_significance = "supporting"

    relationship_depth = clean_text(
        explicit_assignment.get("relationship_depth", ""),
        clean_text(existing_assignment.get("relationship_depth", ""), "unknown"),
    ).lower()
    if relationship_depth not in {"deep", "functional", "unknown"}:
        relationship_depth = "functional" if mentioned_in_player_backstory else "unknown"

    explicit_long_term = explicit_assignment.get("long_term_plot_significance")
    existing_long_term = existing_assignment.get("long_term_plot_significance")
    long_term_plot_significance = (
        bool(explicit_long_term)
        if isinstance(explicit_long_term, bool)
        else (
            bool(existing_long_term)
            if isinstance(existing_long_term, bool)
            else planned_chapter_count >= 2 or len(planned_chapter_ids) >= 2
        )
    )

    assignment_reason = clean_text(
        explicit_assignment.get("assignment_reason", ""),
        clean_text(existing_assignment.get("assignment_reason", "")),
    )
    if not assignment_reason:
        if mentioned_in_player_backstory and long_term_plot_significance:
            assignment_reason = "player_backstory_long_term"
        elif mentioned_in_player_backstory:
            assignment_reason = "player_backstory_interactive_floor"
        elif plot_significance == "core":
            assignment_reason = "core_plot_weight"
        else:
            assignment_reason = "supporting_plot_need"

    explicit_can_promote = explicit_assignment.get("can_promote_to_l1")
    existing_can_promote = existing_assignment.get("can_promote_to_l1")
    can_promote_to_l1 = (
        bool(explicit_can_promote)
        if isinstance(explicit_can_promote, bool)
        else (
            bool(existing_can_promote)
            if isinstance(existing_can_promote, bool)
            else bool(
                mentioned_in_player_backstory
                or long_term_plot_significance
                or plot_significance == "supporting"
            )
        )
    )

    return {
        "mentioned_in_player_backstory": mentioned_in_player_backstory,
        "plot_significance": plot_significance,
        "relationship_depth": relationship_depth,
        "long_term_plot_significance": long_term_plot_significance,
        "can_promote_to_l1": can_promote_to_l1,
        "assignment_reason": assignment_reason,
    }


def _resolve_story_agent_type(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    layer_assignment_seed: Mapping[str, Any],
    planned_chapter_count: int,
    planned_chapter_ids: list[str],
) -> str:
    """从 layer_assignment_seed + 显式声明中挑选最终 agent_type。

    调用时机：`_build_layer_assignment_seed` 之后紧接着调用，产出
    最终 agent_type（`actor` / `L1`），随后会被两个容量守卫
    再次可能下调。

    判定路径：
        - 先规范化 explicit_agent_type（raw > existing），仅接受
          `{actor, L1}`，其他视作空。

        **玩家背景提及规则**（`mentioned_in_player_backstory == True`）
        优先于显式，因为背景保护要求角色至少是可交互的 L1：
            - 一律升为 L1（**不允许背景提及的角色掉为 actor**）。

        **未被背景提及**：
            - explicit 非空 → 采纳 explicit。
            - `plot_significance == "replaceable"` → actor。
            - 其他默认 L1。

    返回：字符串 `"actor" | "L1"`。
    """
    explicit_agent_type = clean_text(
        raw_character.get("agent_type", ""),
        clean_text(existing_profile.get("agent_type", "")),
    )
    if explicit_agent_type not in {"actor", "L1"}:
        explicit_agent_type = ""

    mentioned_in_player_backstory = bool(layer_assignment_seed.get("mentioned_in_player_backstory", False))
    plot_significance = clean_text(layer_assignment_seed.get("plot_significance", ""), "supporting")

    if mentioned_in_player_backstory:
        return "L1"

    if explicit_agent_type:
        return explicit_agent_type
    if plot_significance == "replaceable":
        return "actor"
    return "L1"


def _count_story_layers(character_profiles: dict[str, "CharacterProfile"]) -> int:
    """统计当前本地 profiles 中 L1 的数量。

    调用时机：`_resolve_effective_roster_counts` 内部；也可直接在
    `ActorCreateAgent` 里做本地占用量即时检查。规则：按
    `profile.agent_type` 严格判 `"L1"`（clean 后默认视为 actor）。
    返回：`l1_count`。
    """
    l1_count = 0
    for profile in character_profiles.values():
        agent_type = clean_text(profile.get("agent_type", ""), "actor")
        if agent_type == "L1":
            l1_count += 1
    return l1_count


def _resolve_effective_roster_counts(
    character_profiles: dict[str, "CharacterProfile"],
    character_roster_snapshot: Mapping[str, Any] | None,
) -> tuple[int, int]:
    """得到"本地 profiles + 全局 roster 快照"合并后的有效计数。

    调用时机：容量守卫（`_respect_agent_layer_limits` /
    `_respect_player_bound_capacity`）在决策前需要一个**保守**的现有
    占用量估计；本函数取 local / roster 两侧 **max**，避免只看单侧
    低估占用。local 从 character_profiles 数出 L1/actor（player
    不计入 actor）；roster 从 `character_roster_snapshot["summary"]`
    读 `total_L1/total_ActorAgent`，缺省按 0 计。
    返回：`(effective_l1, effective_actor)`。
    """
    local_l1_count = _count_story_layers(character_profiles)
    local_actor_count = sum(
        1
        for character_id, profile in character_profiles.items()
        if character_id != "player" and clean_text(profile.get("agent_type", "actor"), "actor") == "actor"
    )
    summary = (
        character_roster_snapshot.get("summary", {})
        if isinstance(character_roster_snapshot, Mapping)
        else {}
    )
    roster_l1_count = int(summary.get("total_L1", 0) or 0) if isinstance(summary, Mapping) else 0
    roster_actor_count = int(summary.get("total_ActorAgent", 0) or 0) if isinstance(summary, Mapping) else 0
    return (
        max(local_l1_count, roster_l1_count),
        max(local_actor_count, roster_actor_count),
    )


def _respect_agent_layer_limits(
    *,
    resolved_agent_type: str,
    layer_assignment: Mapping[str, Any],
    existing_l1_count: int,
    new_l1_count: int,
) -> str:
    """按 L1 数量上限把 agent_type 下调到当前预算内。

    调用时机：`_resolve_story_agent_type` 得到"理想 agent_type"后，
    先由本函数按 `MAX_L1_AGENTS` 做第一次容量守卫。

    下调路径 **L1 → actor**：
        - 若 resolved == "L1"：
            - 当 `existing_l1 + new_l1 < MAX_L1_AGENTS` 或角色被玩家
              背景提及（**背景保护例外**）→ 保持 L1。
            - 否则下调为 actor。
        - 其他（原本就是 actor）：原样返回。

    **背景保护例外**：`layer_assignment.mentioned_in_player_backstory`
    为 True 的角色不参与下调，即便超额也保留原层级。

    返回：最终 agent_type（`"actor" | "L1"`）。
    """
    mentioned_in_player_backstory = bool(layer_assignment.get("mentioned_in_player_backstory", False))
    if resolved_agent_type == "L1":
        if existing_l1_count + new_l1_count < MAX_L1_AGENTS or mentioned_in_player_backstory:
            return "L1"
        return "actor"
    return resolved_agent_type


def _respect_player_bound_capacity(
    *,
    resolved_agent_type: str,
    layer_assignment: Mapping[str, Any],
    max_total_characters: int,
    existing_l1_count: int,
    new_l1_count: int,
) -> str:
    """按 max_total_characters（玩家绑定命名角色总额）做第二次容量守卫。

    调用时机：`_respect_agent_layer_limits` 之后再次守卫；仅对已经
    是 L1 的角色生效——纯 actor 不占用玩家绑定名额，直接放行。

    分支规则：
        - resolved 不是 `"L1"` → 原样返回。
        - `max_total_characters <= 0`：视为**关闭了玩家绑定名额**，
            - 背景提及 → 保留原层级；
            - 否则一律降为 `"actor"`。
        - 否则计 `current = existing_l1 + new_l1`：
            - `current < max_total_characters` 或背景提及 → 原样返回。
            - 已达/超额且非背景保护 → 降为 `"actor"`。

    返回：最终 agent_type（`"actor" | "L1"`）。
    """
    if resolved_agent_type != "L1":
        return resolved_agent_type
    if max_total_characters <= 0:
        return resolved_agent_type if bool(layer_assignment.get("mentioned_in_player_backstory", False)) else "actor"

    current_story_bound_count = existing_l1_count + new_l1_count
    if current_story_bound_count < max_total_characters or bool(
        layer_assignment.get("mentioned_in_player_backstory", False)
    ):
        return resolved_agent_type
    return "actor"
