# 拆分 actor_create_agent.py 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将根目录 1112 行的 `actor_create_agent.py` 拆分为 `Actor/` 子包下的四个文件（Schema/Prompt/Heuristics/Agent），删除根目录原文件，并更新全部导入点，切断编排层向项目根目录的反向依赖。

**Architecture:** 保持所有对外符号名不变（`ActorCreateAgent`、`MAX_STORY_CHARACTERS`、`MAX_L1_AGENTS`、`MAX_L2_AGENTS`）。所有字符串字面量 `"actor_create_agent"`（用作 `profile_source` 标记和 `ComponentFactory` 组件键）**不改**，只改 Python 模块路径。分四文件：
- `Actor/ActorCreateSchema.py` — JSON schema 常量（L2_PROFILE_SCHEMA / L1_PROFILE_SCHEMA / LAYER_ASSIGNMENT_SCHEMA / SUPPORTING_CHARACTER_PROPERTIES / SUPPORTING_CHARACTER_REQUIRED / ACTOR_CREATE_RESPONSE_SCHEMA / CONTEXTUAL_ACTOR_RESPONSE_SCHEMA）+ 容量常量（MAX_L1_AGENTS / MAX_L2_AGENTS / MAX_STORY_CHARACTERS）+ BACKSTORY_RELATION_HINTS。
- `Actor/ActorCreatePrompt.py` — ACTOR_CREATE_SYSTEM_PROMPT。
- `Actor/ActorCreateHeuristics.py` — 9 个模块级私有函数（`_build_character_id` / `_assign_chapter_ids` / `_contains_backstory_signal` / `_infer_backstory_priority` / `_build_layer_assignment_seed` / `_resolve_story_agent_type` / `_count_story_layers` / `_resolve_effective_roster_counts` / `_respect_agent_layer_limits` / `_respect_player_bound_capacity`）。启发式函数保留 `_` 前缀但**在模块内暴露**给 `ActorCreateAgent` 使用，通过 `__all__` 明确导出集合。
- `Actor/ActorCreateAgent.py` — `ActorCreateAgent` 类本体。

**Tech Stack:** Python 3.10+，pytest（无 conftest.py，测试用 `python -m pytest tests/xxx.py`），无 build 系统。

**关键约束（不可违反）：**
1. 字符串 `"actor_create_agent"` 是持久化数据里的 `profile_source` 值和 `ComponentFactory` 的组件键，**只改 Python 模块路径，不改这些字符串字面量**。
2. `MAX_STORY_CHARACTERS` 在 `Graph/story_cast_nodes.py:9` 也被导入，必须继续可导出。
3. `CharacterProfile.py:156` 里的 `clean_text(source.get("profile_source", "")) == "actor_create_agent"` 是字符串比较，**不涉及本次修改**。
4. `Actor/__init__.py` 目前不导出 `ActorCreateAgent`，为保持向后兼容并让新导入路径统一，本次**主动**加入。
5. CLAUDE.md 规定：文件保持 <500 行；复杂函数加中文注释；先读后编辑。

---

## 现有导入点清单（拆完后必须全部更新）

- `ComponentFactory.py:14` — `from actor_create_agent import ActorCreateAgent`
- `session_bootstrap.py:41` — 组件名字面量 `"actor_create_agent"`（**不改**，只是登记项）
- `Graph/nodes.py:66` — `from actor_create_agent import ActorCreateAgent`
- `Graph/story_cast_nodes.py:9` — `from actor_create_agent import ActorCreateAgent, MAX_STORY_CHARACTERS`
- `Graph/contextual_scene_handoffs.py:11` — `from actor_create_agent import ActorCreateAgent`（在 TYPE_CHECKING 块内）
- `tests/test_agent_profile_layers.py:19` — `from actor_create_agent import ActorCreateAgent`
- `web_session.py:524` — 只访问 `self.deps.actor_create_agent` 属性名，**不改**

---

## Task 1: 建立基线 —— 先跑通现有测试

**Files:**
- Read: `actor_create_agent.py`, `Actor/__init__.py`
- Test: `tests/test_agent_profile_layers.py`

- [ ] **Step 1: 确认工作目录与文件存在**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && ls actor_create_agent.py Actor/__init__.py tests/test_agent_profile_layers.py
```
Expected: 三个文件均列出。

- [ ] **Step 2: 跑现有测试建立绿色基线**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_agent_profile_layers.py tests/test_story_authoring_subgraph.py tests/test_story_planning_fallbacks.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_persistence_save_load.py tests/test_session_bootstrap.py -q
```
Expected: 全部 PASS。如有失败，先记录失败列表（可能是既有环境问题），拆分完成后须与基线一致，不能新增失败。

- [ ] **Step 3: 记录基线（若无 git 提交，写入临时 baseline.txt）**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_agent_profile_layers.py tests/test_story_authoring_subgraph.py tests/test_story_planning_fallbacks.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_persistence_save_load.py tests/test_session_bootstrap.py -q 2>&1 | tail -5
```
把最后一行（如 `21 passed in 0.42s`）记住作为基线。

---

## Task 2: 创建 `Actor/ActorCreateSchema.py`

**Files:**
- Create: `Actor/ActorCreateSchema.py`

- [ ] **Step 1: 读原文件对应区段**

Read `actor_create_agent.py` lines 33–257（容量常量 + BACKSTORY_RELATION_HINTS + 5 个 schema 常量）。

- [ ] **Step 2: 写 `Actor/ActorCreateSchema.py`**

内容结构：
```python
"""ActorCreate 相关的 JSON schema 与容量常量。

拆自原 actor_create_agent.py（1112 行 God-file）。本模块只包含"数据形状"，
不含任何逻辑；ActorCreateAgent、启发式函数与外部调用方（如 story_cast_nodes）
应从这里导入常量，禁止就地重定义。
"""
from __future__ import annotations

# ---- 容量上限（player-bound）----
# 每局故事内可存在的 L1（长期主线）与 L2（阶段性）角色数量上限。
# actor 类角色（可复用的功能性 NPC）不受此限。
MAX_L1_AGENTS = 6
MAX_L2_AGENTS = 15
MAX_STORY_CHARACTERS = MAX_L1_AGENTS + MAX_L2_AGENTS

# ---- 玩家背景关系提示词 ----
# 用于 `_contains_backstory_signal` 中判断角色是否被玩家背景显式提及；
# 命中任一提示词即触发"背景保护"，避免被下调为 actor。
BACKSTORY_RELATION_HINTS = (
    "妹妹", "弟弟", "哥哥", "姐姐",
    "师父", "师尊", "师兄", "师姐", "师弟", "师妹",
    "父亲", "母亲", "爷爷", "奶奶", "外公", "外婆",
    "宿敌", "挚友", "青梅", "道侣", "同门", "族长",
)

# ---- Schema 定义 ----
L2_PROFILE_SCHEMA = { ... }  # 从原 actor_create_agent.py:62-97 逐字迁移
L1_PROFILE_SCHEMA = { ... }  # 原 :99-122
LAYER_ASSIGNMENT_SCHEMA = { ... }  # 原 :124-149
SUPPORTING_CHARACTER_PROPERTIES = { ... }  # 原 :151-192
SUPPORTING_CHARACTER_REQUIRED = [ ... ]  # 原 :194-212
ACTOR_CREATE_RESPONSE_SCHEMA = { ... }  # 原 :214-235（引用上面的 PROPERTIES/REQUIRED）
CONTEXTUAL_ACTOR_RESPONSE_SCHEMA = { ... }  # 原 :238-256

__all__ = [
    "MAX_L1_AGENTS", "MAX_L2_AGENTS", "MAX_STORY_CHARACTERS",
    "BACKSTORY_RELATION_HINTS",
    "L2_PROFILE_SCHEMA", "L1_PROFILE_SCHEMA", "LAYER_ASSIGNMENT_SCHEMA",
    "SUPPORTING_CHARACTER_PROPERTIES", "SUPPORTING_CHARACTER_REQUIRED",
    "ACTOR_CREATE_RESPONSE_SCHEMA", "CONTEXTUAL_ACTOR_RESPONSE_SCHEMA",
]
```

**注意：** 上面的 `{ ... }` 占位处必须从原文件对应行完整复制，不得省略、不得改字段顺序（字段顺序在 schema 校验里无语义影响，但保持一致便于 diff 审阅）。

- [ ] **Step 3: 语法自检**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "from Actor.ActorCreateSchema import ACTOR_CREATE_RESPONSE_SCHEMA, CONTEXTUAL_ACTOR_RESPONSE_SCHEMA, LAYER_ASSIGNMENT_SCHEMA, SUPPORTING_CHARACTER_PROPERTIES, SUPPORTING_CHARACTER_REQUIRED, L1_PROFILE_SCHEMA, L2_PROFILE_SCHEMA, MAX_L1_AGENTS, MAX_L2_AGENTS, MAX_STORY_CHARACTERS, BACKSTORY_RELATION_HINTS; print(MAX_STORY_CHARACTERS, len(BACKSTORY_RELATION_HINTS))"
```
Expected: `21 22`（MAX_STORY_CHARACTERS=21，BACKSTORY_RELATION_HINTS 有 22 项）。

- [ ] **Step 4: 与原文件字面比对**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
import actor_create_agent as old
from Actor import ActorCreateSchema as new
for k in ['MAX_L1_AGENTS','MAX_L2_AGENTS','MAX_STORY_CHARACTERS','BACKSTORY_RELATION_HINTS','L2_PROFILE_SCHEMA','L1_PROFILE_SCHEMA','LAYER_ASSIGNMENT_SCHEMA','SUPPORTING_CHARACTER_PROPERTIES','SUPPORTING_CHARACTER_REQUIRED','ACTOR_CREATE_RESPONSE_SCHEMA','CONTEXTUAL_ACTOR_RESPONSE_SCHEMA']:
    assert getattr(old, k) == getattr(new, k), k
print('schema OK')
"
```
Expected: `schema OK`。任何 mismatch 说明抄漏了字段，回到 Step 2 修正。

---

## Task 3: 创建 `Actor/ActorCreatePrompt.py`

**Files:**
- Create: `Actor/ActorCreatePrompt.py`

- [ ] **Step 1: 读原 system prompt**

Read `actor_create_agent.py` lines 259–289。

- [ ] **Step 2: 写 `Actor/ActorCreatePrompt.py`**

```python
"""ActorCreateAgent 的 system prompt。

单独成文件以便：
1) 与代码逻辑解耦，非工程师可修订文案；
2) 未来做 prompt A/B 测试时可加参数化包装函数；
3) 避免污染 Agent 类文件的可读性（原文件里 30 行 prompt 常量夹在类与启发式之间）。
"""
from __future__ import annotations

ACTOR_CREATE_SYSTEM_PROMPT = """
You are the Story Layer and Cast Architect for an open-world xianxia roleplay game.
...  # 原文逐字迁移（actor_create_agent.py:259-289）
"""

__all__ = ["ACTOR_CREATE_SYSTEM_PROMPT"]
```

- [ ] **Step 3: 与原文件比对**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
import actor_create_agent as old
from Actor.ActorCreatePrompt import ACTOR_CREATE_SYSTEM_PROMPT as new
assert old.ACTOR_CREATE_SYSTEM_PROMPT == new
print('prompt OK')
"
```
Expected: `prompt OK`。

---

## Task 4: 创建 `Actor/ActorCreateHeuristics.py`

**Files:**
- Create: `Actor/ActorCreateHeuristics.py`

- [ ] **Step 1: 读原启发式区段**

Read `actor_create_agent.py` lines 291–579（10 个模块级函数）。

- [ ] **Step 2: 写 `Actor/ActorCreateHeuristics.py`**

结构说明：
- 保留原 `_` 前缀命名（保持"包内私有"语义），但通过 `__all__` 显式导出给 `Actor.ActorCreateAgent` 使用。
- 每个函数顶部加中文 docstring 说明**做什么、什么时候被调用、返回值含义**。
- 从 `Actor.ActorCreateSchema` 导入常量，而不是重定义。
- 保留原逐字实现，不重写逻辑。

```python
"""ActorCreate 的启发式规则集。

这些函数在 LLM 返回结果后被 `ActorCreateAgent` 调用，用于：
- 归一化 character_id / 章节分配（Step: id/chapter 分配）
- 判定角色是否被玩家背景显式提及（Step: 背景保护）
- 推断 layer_assignment 与 agent_type（Step: 层级决策）
- 尊重 L1/L2 容量上限（Step: 容量守卫）

调用顺序参考 ActorCreateAgent.normalize_supporting_cast。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from Actor.ActorCreateSchema import (
    BACKSTORY_RELATION_HINTS,
    MAX_L1_AGENTS,
    MAX_L2_AGENTS,
)
from StoryStateUtils import clean_text

if TYPE_CHECKING:
    from CharacterProfile import CharacterProfile


def _build_character_id(
    *,
    raw_id: str,
    name: str,
    character_profiles: dict[str, "CharacterProfile"],
    used_ids: set[str],
    fallback_index: int,
) -> str:
    """为新生成的角色生成/复用 character_id。

    优先级：
    1. raw_id 已存在于当前 character_profiles → 直接复用；
    2. 通过 name 精确匹配已有角色 → 复用该角色的 id；
    3. 用 raw_id 规范化（小写+去非字母数字）作为候选；
    4. 若 raw_id 为空则用 name 规范化；
    5. 仍为空则用 f"supporting_{fallback_index}"；
    6. 若与已有 id 或本轮 used_ids 冲突，追加 _2/_3 后缀直至唯一。

    used_ids 由调用方维护，用于在同一轮内跟踪已分配的 id。
    """
    # 【原逐字迁移，行为不变】
    if raw_id and raw_id in character_profiles:
        return raw_id
    ...  # 从原文件复制


def _assign_chapter_ids(...) -> list[str]:
    """把一个角色分配到 planned_chapter_count 个章节里。

    从 outline_ids[start_index:] 顺序去重挑选；若尾部不够，则从头补齐（回环）。
    用于当 LLM 未指定 planned_chapter_ids 时提供确定性回退。
    """
    ...


def _contains_backstory_signal(player_background: str, candidate_text: str) -> bool:
    """判断 candidate_text 是否与玩家背景存在语义关联。

    命中条件（满足其一即为 True）：
    - candidate_text（>=2 字符）本身作为子串出现在 player_background 中；
    - candidate_text 与 player_background 同时含有 BACKSTORY_RELATION_HINTS 里的某一提示词
      （例如 "师妹" 同时出现，视为关系提及）。
    """
    ...


def _infer_backstory_priority(...) -> bool:
    """推断"是否被玩家背景显式提及"（layer_assignment.mentioned_in_player_backstory）。

    - 若 raw_character / existing_profile 已显式给出 bool 值，直接采用；
    - 否则逐一检查 name/story_role/introduction_hint 是否与 player_background 存在关联。
    """
    ...


def _build_layer_assignment_seed(
    raw_character: Mapping[str, Any],
    existing_profile: Mapping[str, Any],
    *,
    player_background: str,
    planned_chapter_count: int,
    planned_chapter_ids: list[str],
) -> dict[str, Any]:
    """构建 layer_assignment 的种子字典（供后续 normalize_layer_assignment 消费）。

    合并规则（explicit > existing > 推断默认）：
    - plot_significance ∈ {core, supporting, replaceable}，默认 supporting；
    - relationship_depth ∈ {deep, functional, unknown}，若 mentioned_in_player_backstory 则默认 functional，否则 unknown；
    - long_term_plot_significance：显式 bool 优先，否则以"跨章节数 >= 2"为默认；
    - assignment_reason：给出四种解释文案，供调试与日志；
    - can_promote_to_l1：默认对"背景提及/长期/supporting"角色开启升级通道。
    """
    ...


def _resolve_story_agent_type(...) -> str:
    """决定角色的 agent_type ∈ {actor, L1, L2}。

    核心规则（对应原 SYSTEM_PROMPT 中的层级规则，但作为 LLM 回退的确定性实现）：
    - 玩家背景提及 → 至少 L2；若显式为 L1/或 long-term/或 core/或 deep → L1；
    - 未提及且 explicit_agent_type 有效 → 采用显式；
    - 长期/多章/core → L1；
    - replaceable → actor；
    - 其余 → L2。
    """
    ...


def _count_story_layers(character_profiles: dict[str, "CharacterProfile"]) -> tuple[int, int]:
    """统计当前 profiles 中 L1/L2 已占用数量（player 与 actor 不计入）。返回 (l1, l2)。"""
    ...


def _resolve_effective_roster_counts(...) -> tuple[int, int, int]:
    """取 local 与 roster snapshot 中 L1/L2/actor 的较大值。

    因为 roster snapshot 可能领先于本地 profiles（并发或先落库），使用 max()
    以避免容量上限被绕过。返回 (l1_effective, l2_effective, actor_effective)。
    """
    ...


def _respect_agent_layer_limits(...) -> str:
    """在 L1/L2 容量已满时，将 agent_type 下调（L1→L2→actor）。

    例外：若 mentioned_in_player_backstory=True，则不下调（背景保护）。
    """
    ...


def _respect_player_bound_capacity(...) -> str:
    """在 player-bound 总容量已满时，将 L1/L2 下调为 actor。

    - max_total_characters <= 0：非法配置，除非有背景保护，否则直接返回 actor；
    - 未满 或 背景保护 → 保持；
    - 已满 且 非背景保护 → actor。
    """
    ...


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
```

**注意：** `...` 处必须从 `actor_create_agent.py:291-579` 逐字迁移函数体，不改任何行为。docstring 放在函数体最前面（`def` 冒号后第一行）。

- [ ] **Step 3: 与原实现行为对比（黑盒等价性）**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
import actor_create_agent as old
from Actor import ActorCreateHeuristics as new
# 采样比对
assert old._build_character_id.__code__.co_code == new._build_character_id.__code__.co_code, '_build_character_id bytecode diverged'
print('build_character_id bytecode identical')
# 行为采样
r1 = old._contains_backstory_signal('我有个师妹叫小青', '师妹')
r2 = new._contains_backstory_signal('我有个师妹叫小青', '师妹')
assert r1 == r2 == True
print('behavior sample OK')
"
```
Expected: `build_character_id bytecode identical` + `behavior sample OK`。

**若 bytecode 不同但行为等价** 可容忍（例如常量引用位置不同）；关键是行为采样必须一致。

- [ ] **Step 4: 用现有测试跑一遍（间接验证）**

`tests/test_agent_profile_layers.py` 会通过 `ActorCreateAgent` 间接调用这些启发式；本步骤在 Task 5 完成后统一跑。

---

## Task 5: 创建 `Actor/ActorCreateAgent.py`

**Files:**
- Create: `Actor/ActorCreateAgent.py`

- [ ] **Step 1: 读原类**

Read `actor_create_agent.py` lines 581–1112（`class ActorCreateAgent` 全体，含 8 个方法）。

- [ ] **Step 2: 写 `Actor/ActorCreateAgent.py`**

导入结构：
```python
"""ActorCreateAgent —— 剧情补充角色生成与层级分配。

原实现见根目录 actor_create_agent.py（已删除，本文件为其 Agent 类拆分产物）。
配套模块：
- Actor.ActorCreateSchema：JSON schema 与容量常量
- Actor.ActorCreatePrompt：system prompt
- Actor.ActorCreateHeuristics：LLM 后处理与回退启发式
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
    normalize_l2_agent_profile,
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
    MAX_L2_AGENTS,
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
    """故事补充角色生成 Agent。

    职责：
    - build_instruction：为"补充配角"路径构造 LLM 指令；
    - build_contextual_actor_instruction：为"临场生成单个 actor"路径构造 LLM 指令；
    - normalize_supporting_cast：归一化 LLM 返回的多角色 payload；
    - normalize_contextual_actor：归一化单角色 payload；
    - sync_supporting_cast：调用 LLM + 归一化 + 合并进 GameState；
    - create_contextual_actor：单角色版本的 sync。
    """

    def __init__(self, **kwargs: Any) -> None:
        # 从原 :582-590 迁移
        ...

    def bind_character_roster_tool_runtime(...) -> None:
        # 原 :592-596
        ...

    def build_instruction(...) -> list[AgentMessage]:
        """构造"补充配角"的 LLM 消息列表。

        输入：GameState 快照 + SceneConfig + character_profiles 现状；
        输出：AgentMessage 列表（system + user），user 里嵌入 JSON 指令。

        指令包含四段：
        1. 玩家画像与背景（用于识别背景保护角色）；
        2. 剧情大纲已有章节 outline_entries；
        3. 现有 character_roster_snapshot（提示 LLM 现有容量）；
        4. render_json_instruction 生成的 JSON 输出契约。
        """
        # 原 :598-722
        ...

    def build_contextual_actor_instruction(...) -> list[AgentMessage]:
        """构造"临场生成单个 actor"的 LLM 消息列表（用于场景 handoff 时补角色）。"""
        # 原 :724-811
        ...

    def normalize_supporting_cast(...) -> dict[str, "CharacterProfile"]:
        """将 LLM 返回的多角色 payload 归一化并合并到现有 character_profiles。

        步骤（对应原文件 :813-1022）：
        1. 拉取现有 L1/L2/actor 计数（含 roster snapshot 修正）；
        2. 逐角色：
           a) `_build_character_id` 分配/复用 id；
           b) 若已有 profile 且非本 Agent 生成，跳过（避免覆盖用户/其它来源）；
           c) `_build_layer_assignment_seed` + `_resolve_story_agent_type` 决出 agent_type；
           d) `_respect_agent_layer_limits` + `_respect_player_bound_capacity` 施加容量守卫；
           e) `_assign_chapter_ids` 若 LLM 未指定则回退；
           f) 依 agent_type 补齐 l1_profile / l2_profile；
           g) 写入 profile_source="actor_create_agent"（**字符串字面量，勿改**）。
        3. 返回合并后的 character_profiles。
        """
        # 原 :813-1022，逐字迁移
        ...

    def normalize_contextual_actor(...) -> "CharacterProfile":
        # 原 :1024-1043
        ...

    def sync_supporting_cast(...) -> dict[str, "CharacterProfile"]:
        # 原 :1045-1074
        ...

    def create_contextual_actor(...) -> "CharacterProfile":
        # 原 :1076-1112
        ...


__all__ = [
    "ActorCreateAgent",
    "MAX_L1_AGENTS",
    "MAX_L2_AGENTS",
    "MAX_STORY_CHARACTERS",
]
```

**关键点：**
- 类体逐字迁移；docstring 只在 `class` 和"复杂方法"（`build_instruction`, `build_contextual_actor_instruction`, `normalize_supporting_cast`）开头新增，其余方法只在 signature 下方保留原有代码。
- 保留 `profile_source="actor_create_agent"` 字符串常量不变（在 `normalize_supporting_cast` 内部）。
- `MAX_L1_AGENTS`/`MAX_L2_AGENTS`/`MAX_STORY_CHARACTERS` 通过 `__all__` 重新导出，使得 `from Actor.ActorCreateAgent import MAX_STORY_CHARACTERS` 与 `from Actor.ActorCreateSchema import MAX_STORY_CHARACTERS` 都能工作（`Graph/story_cast_nodes.py:9` 目前从原 module 一起导入，方便平滑迁移）。

- [ ] **Step 3: 语法与基本导入自检**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
from Actor.ActorCreateAgent import ActorCreateAgent, MAX_STORY_CHARACTERS, MAX_L1_AGENTS, MAX_L2_AGENTS
agent = ActorCreateAgent(client=object())
assert callable(agent.build_instruction)
assert callable(agent.normalize_supporting_cast)
assert MAX_STORY_CHARACTERS == 21
print('agent import OK')
"
```
Expected: `agent import OK`。

- [ ] **Step 4: 与旧类做属性/方法齐备性比对**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
import actor_create_agent as old
from Actor.ActorCreateAgent import ActorCreateAgent as New
old_methods = {m for m in dir(old.ActorCreateAgent) if not m.startswith('__')}
new_methods = {m for m in dir(New) if not m.startswith('__')}
missing = old_methods - new_methods
extra = new_methods - old_methods
assert not missing, f'missing: {missing}'
print(f'methods identical, count={len(new_methods)}, extras={extra}')
"
```
Expected: `methods identical`。

---

## Task 6: 让根目录 `actor_create_agent.py` 变为过渡 shim（仅本 Task 内存在）

**Files:**
- Modify: `actor_create_agent.py`（临时改造）

拆分完成前先把根文件改成"薄转发层"，这样在 Task 7 更新所有导入点期间，测试仍能一次一步地跑通。**这一步是过渡态，Task 8 会删除该文件。**

- [ ] **Step 1: 将原 `actor_create_agent.py` 完全替换为 shim**

新内容：
```python
"""过渡 shim —— 本文件即将删除。

原实现已拆分到 Actor/ActorCreate{Schema,Prompt,Heuristics,Agent}.py。
所有新代码请直接从 Actor 子包导入。本 shim 仅保证导入路径迁移期间兼容。
删除时机：Task 8。
"""
from Actor.ActorCreateAgent import (  # noqa: F401
    ActorCreateAgent,
    MAX_L1_AGENTS,
    MAX_L2_AGENTS,
    MAX_STORY_CHARACTERS,
)
from Actor.ActorCreateSchema import (  # noqa: F401
    ACTOR_CREATE_RESPONSE_SCHEMA,
    BACKSTORY_RELATION_HINTS,
    CONTEXTUAL_ACTOR_RESPONSE_SCHEMA,
    L1_PROFILE_SCHEMA,
    L2_PROFILE_SCHEMA,
    LAYER_ASSIGNMENT_SCHEMA,
    SUPPORTING_CHARACTER_PROPERTIES,
    SUPPORTING_CHARACTER_REQUIRED,
)
from Actor.ActorCreatePrompt import ACTOR_CREATE_SYSTEM_PROMPT  # noqa: F401

# 注意：不再从 shim 中重新导出私有启发式函数 `_*`；这些函数是 Actor 包内实现细节。
# 若某测试直接引用了 `_build_character_id` 等，需要在 Task 7 改为从 Actor.ActorCreateHeuristics 导入。
```

- [ ] **Step 2: 跑全套受影响测试**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_agent_profile_layers.py tests/test_story_authoring_subgraph.py tests/test_story_planning_fallbacks.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_persistence_save_load.py tests/test_session_bootstrap.py -q
```
Expected: 通过数 == 基线（Task 1 Step 3 记录的数值）。若有失败：
- `ImportError: cannot import name '_build_character_id' from 'actor_create_agent'` → 测试直接 import 了私有函数，回到 Step 1 在 shim 中补一条 `from Actor.ActorCreateHeuristics import _build_character_id  # noqa: F401`（先满足过渡，Task 7 再修正测试导入）。
- 其他错误 → 优先阅读堆栈，若是 schema 引用漂移，回 Task 2 检查抄漏字段。

---

## Task 7: 更新所有导入点

**Files:**
- Modify: `ComponentFactory.py:14`
- Modify: `Graph/nodes.py:66`
- Modify: `Graph/story_cast_nodes.py:9`
- Modify: `Graph/contextual_scene_handoffs.py:11`
- Modify: `tests/test_agent_profile_layers.py:19`

- [ ] **Step 1: 更新 `ComponentFactory.py:14`**

Old:
```python
    from actor_create_agent import ActorCreateAgent
```
New:
```python
    from Actor.ActorCreateAgent import ActorCreateAgent
```

组件字符串键 `"actor_create_agent"`（`ComponentFactory.py:69-70`）**不改**。

- [ ] **Step 2: 更新 `Graph/nodes.py:66`**

Old:
```python
from actor_create_agent import ActorCreateAgent
```
New:
```python
from Actor.ActorCreateAgent import ActorCreateAgent
```

- [ ] **Step 3: 更新 `Graph/story_cast_nodes.py:9`**

Old:
```python
from actor_create_agent import ActorCreateAgent, MAX_STORY_CHARACTERS
```
New:
```python
from Actor.ActorCreateAgent import ActorCreateAgent, MAX_STORY_CHARACTERS
```

- [ ] **Step 4: 更新 `Graph/contextual_scene_handoffs.py:11`**

Old:
```python
    from actor_create_agent import ActorCreateAgent
```
New:
```python
    from Actor.ActorCreateAgent import ActorCreateAgent
```

- [ ] **Step 5: 更新 `tests/test_agent_profile_layers.py:19`**

Old:
```python
from actor_create_agent import ActorCreateAgent
```
New:
```python
from Actor.ActorCreateAgent import ActorCreateAgent
```

- [ ] **Step 6: 扫一遍看是否遗漏**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && grep -rn "from actor_create_agent\|import actor_create_agent" --include="*.py" . | grep -v "^./actor_create_agent.py:" | grep -v ".git/"
```
Expected: **无任何输出**（即除根目录 shim 自身外，无其他文件仍从旧路径导入）。

- [ ] **Step 7: 跑受影响测试**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_agent_profile_layers.py tests/test_story_authoring_subgraph.py tests/test_story_planning_fallbacks.py tests/test_contextual_scene_handoffs.py tests/test_narrator_intro_flow.py tests/test_persistence_save_load.py tests/test_session_bootstrap.py -q
```
Expected: 通过数 == 基线。

---

## Task 8: 删除根目录 shim 并更新 `Actor/__init__.py`

**Files:**
- Delete: `actor_create_agent.py`
- Modify: `Actor/__init__.py`

- [ ] **Step 1: 更新 `Actor/__init__.py` 暴露 ActorCreateAgent**

Old:
```python
from Actor.ActorAgent import ActorAgent
from Actor.ActorHeuristics import build_heuristic_resolved_act
from Actor.L1ActorAgent import L1ActorAgent
from Actor.L2ActorAgent import L2ActorAgent
from Actor.ActorRuntime import apply_resolved_act

__all__ = [
    "ActorAgent",
    "L1ActorAgent",
    "L2ActorAgent",
    "apply_resolved_act",
    "build_heuristic_resolved_act",
]
```
New:
```python
from Actor.ActorAgent import ActorAgent
from Actor.ActorCreateAgent import ActorCreateAgent, MAX_STORY_CHARACTERS
from Actor.ActorHeuristics import build_heuristic_resolved_act
from Actor.L1ActorAgent import L1ActorAgent
from Actor.L2ActorAgent import L2ActorAgent
from Actor.ActorRuntime import apply_resolved_act

__all__ = [
    "ActorAgent",
    "ActorCreateAgent",
    "L1ActorAgent",
    "L2ActorAgent",
    "MAX_STORY_CHARACTERS",
    "apply_resolved_act",
    "build_heuristic_resolved_act",
]
```

- [ ] **Step 2: 删除根目录旧文件**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && rm actor_create_agent.py && ls actor_create_agent.py 2>&1 | grep "No such file"
```
Expected: `ls: actor_create_agent.py: No such file or directory` — 说明已删除。

- [ ] **Step 3: 确保没有残留引用**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && grep -rn "from actor_create_agent\|import actor_create_agent" --include="*.py" . | grep -v ".git/"
```
Expected: **完全无输出**。

- [ ] **Step 4: 全量测试**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/ -q 2>&1 | tail -20
```
Expected: 通过数 >= 基线（Task 1 记录的数值），无新失败。

- [ ] **Step 5: 冒烟：加载入口模块**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "
import ComponentFactory  # noqa
import session_bootstrap  # noqa
from Graph import nodes  # noqa
from Graph import story_cast_nodes  # noqa
from Graph import contextual_scene_handoffs  # noqa
print('all entry modules import OK')
"
```
Expected: `all entry modules import OK`。

---

## Task 9: 验收 & 收尾

**Files:** 无。

- [ ] **Step 1: 复核文件行数**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && wc -l Actor/ActorCreate*.py
```
Expected: 四个文件均 <500 行（符合 CLAUDE.md "文件保持 <500 行"）。
- Schema：约 130 行；
- Prompt：约 40 行；
- Heuristics：约 300 行；
- Agent：约 550 行（若 Agent >500 行则需进一步拆 build_instruction / normalize_supporting_cast，本次先记录到 followup）。

- [ ] **Step 2: 复核根目录不再有该文件**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && ls actor_create_agent.py 2>&1
```
Expected: `No such file or directory`。

- [ ] **Step 3: 验证 profile_source 字符串未被误改**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && grep -rn '"actor_create_agent"' --include="*.py" . | grep -v ".git/"
```
Expected: 至少在下列位置仍能看到（字符串字面量保持不变）：
- `Actor/ActorCreateAgent.py`（原 `:967` 附近，写 profile_source）
- `Actor/ActorCreateAgent.py`（原 `:859` 附近，读 profile_source）
- `CharacterProfile.py:156`
- `session_bootstrap.py:41`
- `Graph/story_cast_nodes.py:47`
- 多个测试文件

- [ ] **Step 4: 最终跑一次完整测试并对比基线**

Run:
```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: 通过数 == Task 1 Step 3 记录的基线数值（或更多，若基线里有原先环境失败被顺带修好）。**不接受任何新增失败。**

---

## 失败回退策略

若 Task 6/7/8 后测试大规模失败：
1. 若失败集中在"import 找不到私有函数" → 在根 shim 中临时补 `from Actor.ActorCreateHeuristics import _xxx  # noqa`，先绿再修测试。
2. 若失败集中在 schema 字段 mismatch → 回 Task 2 Step 4 对比字典结构，逐字段修正。
3. 若整体崩坏 → 恢复 `actor_create_agent.py` 原文件（本次未 git 提交前操作，用备份或 git checkout HEAD -- actor_create_agent.py 恢复），并回退 Actor/ActorCreate*.py。

## 遗留（followup，不在本次范围）

- 若 `Actor/ActorCreateAgent.py` 最终 >500 行，需要进一步把 `build_instruction` / `normalize_supporting_cast` 抽为独立函数或拆到 `ActorCreateFormatter.py`。
- 私有函数 `_build_character_id` 等以 `_` 前缀显式跨模块引用不够干净，将来可考虑改为 `build_character_id` 公共名并在 `__init__.py` 明确导出边界。
- 顶层字符串常量 `"actor_create_agent"` 作为 `profile_source` 值和 `ComponentFactory` 键存在双语义耦合，建议后续引入 `PROFILE_SOURCE_ACTOR_CREATE` 常量集中定义。
