# 记忆工厂读侧接入 Actor(E2)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Actor 回合的短期对话(在场过滤)与人设改由记忆工厂产出的 `ActorMemoryContext` 强制注入,兑现「不在场则无短期记忆」。

**Architecture:** 方案 B 强制注入,无双源分支。工厂 `DefaultActorMemoryProvider.build(actor_id, state)` 组装收窄只读 DTO;沿调用链 `dialogue_nodes → actor_paths/beat_group → 三个 agent.perform_turn → 三个 instruction builder → _build_actor_payload` 把原来透传的 `character_profiles: dict` 换成 `memory_ctx: ActorMemoryContext`。本轮只切短期语义(`recent_history`)与人设来源(`ctx.persona`);长期三层 / player_memory / `recent_short_term_memory` 的读取逻辑不动,仅 profile 来源随 ctx 走。写入(`ActorRuntime._apply_memory_updates`)不动。

**Tech Stack:** Python 3;`typing.Protocol` / frozen dataclass;`unittest` + `pytest -q`;基线 169 全绿。

**依据 spec:** `docs/superpowers/specs/2026-08-14-actor-memory-injection-e2-wiring-design.md`

---

## 文件结构(改动地图)

**生产代码:**
- `Memory/default_provider.py` — 修 persona 兜底(`{}` → `ensure_character_profile(None)`),去 type:ignore。
- `Actor/ActorFormatter.py` — `_build_actor_payload` + 三个 instruction builder 签名收窄(`character_profiles` → `memory_ctx`);`recent_history` 切 `ctx.short_term`;`actor_profile` 全指向 `ctx.persona`。
- `Actor/ActorAgent.py` / `Actor/L1ActorAgent.py` / `Actor/L2ActorAgent.py` — `perform_turn` 签名收窄;L2 的 `supporting_scene_intent_policy.decide` 用 `ctx.persona`。
- `Graph/dependencies.py` — `GraphDependencies` 加 `actor_memory_provider` 字段。
- `Graph/actor_paths.py` — 串行 NPC 路径 build ctx 后 perform_turn。
- `Graph/beat_group.py` — `run_actor_group` / `_perform_with_retry` 把 `character_profiles` 换成 `provider`,worker 内 per-actor build。
- `Graph/dialogue_nodes.py` — `_group_step` 里 `run_actor_group(..., provider=deps.actor_memory_provider)`。
- `session_bootstrap.py` — `build_runtime_dependencies` 默认构建 `DefaultActorMemoryProvider`。

**测试代码:**
- `tests/test_actor_formatter_payload.py` — 造 ctx 传入(改 `_build_actor_payload` 调用)。
- `tests/test_beat_group_parallel.py` — Fake agent `perform_turn(state, memory_ctx)`;`run_actor_group(..., provider=...)`。
- `tests/test_beat_resolution.py` — Fake agent 签名 + `GraphDependencies` 传 provider。
- `tests/test_actor_memory_e2_wiring.py`(新建) — 工厂兜底 + 在场过滤集成验证。

---

## Task 1: 工厂 persona 合法兜底

**Files:**
- Modify: `Memory/default_provider.py:26-28`
- Test: `tests/test_actor_memory_e2_wiring.py`(新建)

- [ ] **Step 1: 写失败测试(未命中角色 persona 是合法空壳)**

新建 `tests/test_actor_memory_e2_wiring.py`:

```python
import unittest

from CharacterProfile import ensure_character_profile
from GameState import empty_game_state
from Memory.default_provider import DefaultActorMemoryProvider


def _state_with_history(history):
    state = empty_game_state()
    state["history"] = history
    state["scene"] = {"location_id": "room", "on_stage": []}
    state["characters"] = {}
    return state


class ProviderPersonaFallbackTest(unittest.TestCase):
    def test_persona_falls_back_to_legal_shell(self):
        provider = DefaultActorMemoryProvider(character_profiles={})
        ctx = provider.build("ghost", _state_with_history([]))
        expected = ensure_character_profile(None)
        # 未命中角色时 persona 是合法空壳(含全部必填键),而非空 dict。
        self.assertEqual(set(ctx.persona.keys()), set(expected.keys()))
        self.assertEqual(ctx.persona.get("agent_type"), expected.get("agent_type"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_memory_e2_wiring.py::ProviderPersonaFallbackTest -q`
Expected: FAIL(persona 为 `{}`,keys 集合与合法空壳不等)

- [ ] **Step 3: 修工厂兜底**

`Memory/default_provider.py`:顶部 import 加 `ensure_character_profile`,`build` 里 persona 兜底改为合法空壳。

import 区(第 5 行附近,`from CharacterProfile import CharacterProfile` 改为):

```python
from CharacterProfile import CharacterProfile, ensure_character_profile
```

`build` 内第 27-28 行(persona 那两行)替换为:

```python
        # 人设:命中则复用现有 CharacterProfile;未命中给合法空壳兜底,
        # 保住下游 .get("memory_profile") / 播种 / agent_contract 字段访问。
        persona: CharacterProfile = self._character_profiles.get(actor_id) or ensure_character_profile(None)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_memory_e2_wiring.py::ProviderPersonaFallbackTest -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Memory/default_provider.py tests/test_actor_memory_e2_wiring.py
git commit -m "$(cat <<'EOF'
fix(memory): persona 未命中兜底为合法空壳而非空 dict

未命中角色时 build 出的 persona 从 {} 改为 ensure_character_profile(None),
保住下游 memory_profile / 播种 / agent_contract 字段访问;去掉 type:ignore。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: formatter 收窄(签名 + 短期语义切换)

**Files:**
- Modify: `Actor/ActorFormatter.py:24-73`(`_build_actor_payload`)、`:214-249`(三个 instruction builder)
- Test: `tests/test_actor_formatter_payload.py:192`

- [ ] **Step 1: 改单测调用为造 ctx 传入,并加短期/人设断言**

先读 `tests/test_actor_formatter_payload.py` 全文,理解 `state` / `profiles` 的构造。然后:

顶部 import 区加:

```python
from Memory.default_provider import DefaultActorMemoryProvider
```

把第 192 行:

```python
        payload = _build_actor_payload(state, profiles)
```

改为(在其之前构建 ctx,并把 next_act 的 actor 作为 build 目标):

```python
        actor_id = state["runtime"]["next_act"]["actor"]
        ctx = DefaultActorMemoryProvider(character_profiles=profiles).build(actor_id, state)
        payload = _build_actor_payload(state, ctx)
```

在该测试方法末尾(已有断言之后)追加两条:

```python
        # recent_history 改用工厂在场过滤后的短期(ctx.short_term),而非 history[-8:]。
        self.assertEqual(payload["recent_history"], list(ctx.short_term))
        # actor_profile 改由 ctx.persona 供给(等价替换)。
        self.assertEqual(payload["actor_profile"], ctx.persona)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_formatter_payload.py -q`
Expected: FAIL(`_build_actor_payload` 仍是旧签名 `(state, character_profiles)`,传 ctx 类型不符 / 缺 next_act 取用不一致)

- [ ] **Step 3: 收窄 `_build_actor_payload` 签名与函数体**

`Actor/ActorFormatter.py` 顶部 import 区,把:

```python
from CharacterProfile import CharacterProfile
```

改为(不再需要 CharacterProfile 作参数类型,改引 ctx 类型):

```python
from Memory.context import ActorMemoryContext
```

> 注:若文件内其它函数仍用到 `CharacterProfile`,保留原 import 并**追加** `ActorMemoryContext` import;实施时按实际引用决定(builder 签名本任务也会去掉 `CharacterProfile` 形参)。

把第 24-39 行(签名 + 前几行取值)替换为:

```python
def _build_actor_payload(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> dict[str, Any]:
    planned_act = state["runtime"].get("next_act")
    # actor_id 以工厂 build 的 actor 为准,保证与 ctx.short_term 过滤对象一致。
    actor_id = memory_ctx.actor_id
    actor_profile = memory_ctx.persona
    actor_runtime = state["characters"].get(actor_id or "", {})
    actor_memory_profile = normalize_character_memory_config(
        actor_profile.get("memory_profile", {}),
        agent_type=str(actor_profile.get("agent_type", "actor") or "actor"),
    )
    actor_memory = ensure_character_memory_state(
        actor_runtime.get("memory", {}),
        actor_profile=actor_profile,
    )
```

把第 71 行:

```python
        "recent_history": state["history"][-8:],
```

改为(唯一语义切换):

```python
        "recent_history": list(memory_ctx.short_term),
```

其余行(:52 `actor_profile`、:53-59 agent_contract、:60-64 actor_memory 三层、:68 player_memory、:72 recent_short_term_memory、:70 next_act)**保持不动**。

- [ ] **Step 4: 收窄三个 instruction builder 签名**

`Actor/ActorFormatter.py:214-249`,三处 `character_profiles: dict[str, CharacterProfile]` 形参改为 `memory_ctx: ActorMemoryContext`,并把 `_build_actor_payload(state, character_profiles)` 改为 `_build_actor_payload(state, memory_ctx)`。

`build_actor_instruction`:

```python
def build_actor_instruction(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> str:
    payload = _build_actor_payload(state, memory_ctx)
    return render_json_instruction(
        "Use the following scene context to produce one role-faithful turn as strict JSON.",
        payload,
    )
```

`build_l2_actor_instruction`:

```python
def build_l2_actor_instruction(
    state: GameState,
    memory_ctx: ActorMemoryContext,
    *,
    policy_decision: Mapping[str, Any],
) -> str:
    payload = _build_actor_payload(state, memory_ctx)
    payload["supporting_scene_intent"] = dict(policy_decision)
    return render_json_instruction(
        "Use the following scene context to produce one L2 supporting turn as strict JSON. "
        "Support the scene through the suggested supporting function without stealing narrative dominance.",
        payload,
    )
```

`build_l1_actor_instruction`:

```python
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_formatter_payload.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Actor/ActorFormatter.py tests/test_actor_formatter_payload.py
git commit -m "$(cat <<'EOF'
refactor(actor): formatter 收窄为 memory_ctx,短期切在场过滤

_build_actor_payload 与三个 instruction builder 的 character_profiles 参数
换成 memory_ctx: ActorMemoryContext;recent_history 改用 ctx.short_term(在场过滤);
actor_profile 改由 ctx.persona 供给。长期三层/player/recent_short_term_memory 逻辑不动。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 三个 agent perform_turn 收窄

**Files:**
- Modify: `Actor/ActorAgent.py:49-65`、`Actor/L1ActorAgent.py:35-52`、`Actor/L2ActorAgent.py:44-70`
- Test: `tests/test_beat_resolution.py`(Fake agent 签名)

- [ ] **Step 1: 改 test_beat_resolution 的 Fake agent 签名 + actor_node 调用链**

先读 `tests/test_beat_resolution.py` 全文,定位三处 `FakeActor` / `FakeTierActor` 的 `perform_turn(self, state, character_profiles)`(:40、:59、:651)与 `GraphDependencies(...)` 构造块(如 :220)。

把每个 `def perform_turn(self, state, character_profiles):` 改为:

```python
    def perform_turn(self, state, memory_ctx):
```

方法体内若用到 `character_profiles`,改用 `memory_ctx`(通常只是忽略;若有 `del character_profiles` 改 `del memory_ctx`)。

每个 `GraphDependencies(...)` 构造块加一行(在 `character_profiles=profiles,` 之后):

```python
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
```

顶部 import 区加:

```python
from Memory.default_provider import DefaultActorMemoryProvider
```

> 注:Task 5 才给 `GraphDependencies` 加该字段;本步先写入调用,Step 2 预期因缺字段/签名而失败,Task 5 补齐后回归。若单跑本任务想先绿,可在 Task 5 完成后再回归本文件。实施顺序建议:Task 3 与 Task 5 连做,或本步暂只改 Fake agent 签名、构造块留到 Task 5。**推荐:本任务只改 agent 生产代码 + Fake agent 签名两处,构造块 provider 注入放到 Task 5。** 下面 Step 按此推荐执行。

**本步(推荐)只改 Fake agent 的 `perform_turn` 签名**(三处 `character_profiles` → `memory_ctx`),不动构造块。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_beat_resolution.py -q`
Expected: FAIL(生产 agent 仍是旧签名,`actor_node` 走 `resolve_npc_turn_state` 时按新 Fake 签名调用不匹配 / 或反之)

- [ ] **Step 3: 收窄 ActorAgent.perform_turn**

`Actor/ActorAgent.py:49-65` 替换为:

```python
    def perform_turn(
        self,
        state: GameState,
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_actor_instruction(
                    state=state,
                    memory_ctx=memory_ctx,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=state["runtime"].get("next_act"),
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
```

顶部 import 区把 `from CharacterProfile import CharacterProfile`(若仅用于此签名)替换/追加为:

```python
from Memory.context import ActorMemoryContext
```

- [ ] **Step 4: 收窄 L1ActorAgent.perform_turn**

`Actor/L1ActorAgent.py:35-52` 替换为:

```python
    def perform_turn(
        self,
        state: GameState,
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        planned_act = state["runtime"].get("next_act")
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_l1_actor_instruction(
                    state=state,
                    memory_ctx=memory_ctx,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=planned_act,
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
```

顶部 import 同样引入 `ActorMemoryContext`(按实际现有 import 追加)。

- [ ] **Step 5: 收窄 L2ActorAgent.perform_turn(含 policy.decide 用 ctx.persona)**

`Actor/L2ActorAgent.py:44-70` 替换为:

```python
    def perform_turn(
        self,
        state: GameState,
        memory_ctx: ActorMemoryContext,
    ) -> ResolvedAct:
        planned_act = state["runtime"].get("next_act") or {}
        actor_profile = memory_ctx.persona
        policy_decision = self.supporting_scene_intent_policy.decide(
            actor_profile=actor_profile,
            scene_need_detected=True,
            player_action_text=str(state["player"].get("last_input", "") or "").strip(),
            scene_goal=str(state["scene_plan"].get("scene_goal", "") or "").strip(),
            beat_goal=str(state["director_brief"].get("beat_goal", "") or "").strip(),
        )
        return normalize_resolved_act(
            raw_result=self.command(
                instruction=build_l2_actor_instruction(
                    state=state,
                    memory_ctx=memory_ctx,
                    policy_decision=policy_decision,
                ),
                response_format=ACTOR_TURN_RESPONSE_SCHEMA,
            ),
            planned_act=planned_act,
            scene_plan=state["scene_plan"],
            on_stage=state["scene"].get("on_stage", []),
        )
```

顶部 import 引入 `ActorMemoryContext`(按实际现有 import 追加)。

> 注:`actor_id`(原 :50)不再单独取用,已删。

- [ ] **Step 6: 跑测试(本任务只到 agent 生产代码 + Fake 签名)**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -c "import Actor.ActorAgent, Actor.L1ActorAgent, Actor.L2ActorAgent, Actor.ActorFormatter"`
Expected: 无 ImportError(签名一致、无残留 `character_profiles` 引用)

> 完整回归留到 Task 4/5 接线后(此时 `resolve_npc_turn_state` 仍传旧参,`test_beat_resolution` 尚不全绿,属预期中间态)。

- [ ] **Step 7: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Actor/ActorAgent.py Actor/L1ActorAgent.py Actor/L2ActorAgent.py tests/test_beat_resolution.py
git commit -m "$(cat <<'EOF'
refactor(actor): 三个 agent perform_turn 收窄为 memory_ctx

perform_turn(state, character_profiles) → (state, memory_ctx: ActorMemoryContext);
L2 的 supporting_scene_intent_policy.decide 改用 memory_ctx.persona。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 依赖注入字段 + 串行路径接线 + 并行路径接线

**Files:**
- Modify: `Graph/dependencies.py:30-55`(加字段)
- Modify: `Graph/actor_paths.py:72-76`(串行 build ctx)
- Modify: `Graph/beat_group.py:54-126`(`_perform_with_retry` / `run_actor_group` 换 provider)
- Modify: `Graph/dialogue_nodes.py:102-107`(`_group_step` 传 provider)
- Test: `tests/test_beat_group_parallel.py`

- [ ] **Step 1: 给 GraphDependencies 加 actor_memory_provider 字段**

`Graph/dependencies.py`,TYPE_CHECKING 块(:24-27)内加:

```python
    from Memory.provider import ActorMemoryProvider
```

`GraphDependencies` 字段区(:54 `beat_execution_subgraph` 之后)加:

```python
    actor_memory_provider: "ActorMemoryProvider | None" = None
```

- [ ] **Step 2: 改 test_beat_group_parallel 的 Fake agent 签名 + run_actor_group 调用**

先读 `tests/test_beat_group_parallel.py` 全文。

顶部 import 区加:

```python
from Memory.default_provider import DefaultActorMemoryProvider
```

第 86 行 `def perform_turn(self, state, character_profiles):` 改为:

```python
    def perform_turn(self, state, memory_ctx):
```

方法体 `del character_profiles` 改为 `del memory_ctx`。第 193 行的内联 Fake `perform_turn(self, state, character_profiles)` 同样改 `memory_ctx`。

所有 `run_actor_group(...)` 调用(:143、:157、:167、:179、:201)里的 `character_profiles={}` 改为:

```python
            provider=DefaultActorMemoryProvider(character_profiles={}),
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_beat_group_parallel.py -q`
Expected: FAIL(`run_actor_group` 仍收 `character_profiles`,不认 `provider` 关键字)

- [ ] **Step 4: 改 beat_group 的 _perform_with_retry / run_actor_group 为 provider 线程**

`Graph/beat_group.py`,`_perform_with_retry`(:54-86)签名与体替换为:

```python
def _perform_with_retry(
    group_start_state: dict[str, Any],
    actor_id: str,
    resolve_agent: Callable[[str], Any],
    provider: Any,
    max_retries: int,
) -> dict[str, Any]:
    # 每个 actor 各自基于其 actor_state build 记忆上下文(与串行路径一致)。
    actor_state = {
        **group_start_state,
        "runtime": {
            **group_start_state["runtime"],
            "next_act": {
                **(group_start_state["runtime"].get("next_act") or {}),
                "actor": actor_id,
            },
        },
    }
    memory_ctx = provider.build(actor_id, actor_state)
    last_error: Exception | None = None
    for _attempt in range(max_retries + 1):
        try:
            agent = resolve_agent(actor_id)
            return agent.perform_turn(state=actor_state, memory_ctx=memory_ctx)
        except _PROGRAMMING_ERRORS:
            # A code bug, not a transient generation failure — surface it.
            logger.exception("actor %s raised a programming error; not retrying", actor_id)
            raise
        except Exception as exc:  # noqa: BLE001 - retry transient generation failures
            last_error = exc
            logger.warning(
                "actor %s generation attempt %d failed: %s", actor_id, _attempt + 1, exc
            )
    raise last_error if last_error is not None else RuntimeError("unknown actor failure")
```

`run_actor_group`(:89-126)签名把 `character_profiles: dict[str, Any]` 改为 `provider: Any`,`executor.submit` 传参把 `character_profiles` 换成 `provider`:

```python
def run_actor_group(
    group_start_state: dict[str, Any],
    *,
    group: list[str],
    resolve_agent: Callable[[str], Any],
    provider: Any,
    max_retries: int = 3,
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str]]]:
    if not group:
        return [], []

    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(group)) as executor:
        future_map = {
            executor.submit(
                _perform_with_retry,
                group_start_state,
                actor_id,
                resolve_agent,
                provider,
                max_retries,
            ): actor_id
            for actor_id in group
        }
        for future, actor_id in future_map.items():
            try:
                results[actor_id] = future.result()
            except _PROGRAMMING_ERRORS:
                # Let a code bug from any worker fail the whole beat loudly.
                raise
            except Exception as exc:  # noqa: BLE001 - transient failure → skip this actor
                errors[actor_id] = str(exc)

    successes = [(aid, results[aid]) for aid in group if aid in results]
    failures = [(aid, errors[aid]) for aid in group if aid in errors]
    return successes, failures
```

- [ ] **Step 5: 改串行路径 resolve_npc_turn_state build ctx**

`Graph/actor_paths.py:72-76`,把:

```python
    if actor_agent is not None:
        resolved_act = actor_agent.perform_turn(
            state=state,
            character_profiles=deps.character_profiles,
        )
```

改为:

```python
    if actor_agent is not None:
        planned_act = state["runtime"].get("next_act") or {}
        actor_id = str(planned_act.get("actor", "") or "").strip()
        memory_ctx = deps.actor_memory_provider.build(actor_id, state)
        resolved_act = actor_agent.perform_turn(
            state=state,
            memory_ctx=memory_ctx,
        )
```

- [ ] **Step 6: 改 dialogue_nodes 的 _group_step 传 provider**

`Graph/dialogue_nodes.py:102-107`,把:

```python
        successes, failures = run_actor_group(
            current,
            group=group,
            resolve_agent=lambda actor_id: _resolve_agent_for_actor(deps, actor_id),
            character_profiles=deps.character_profiles,
        )
```

改为:

```python
        successes, failures = run_actor_group(
            current,
            group=group,
            resolve_agent=lambda actor_id: _resolve_agent_for_actor(deps, actor_id),
            provider=deps.actor_memory_provider,
        )
```

- [ ] **Step 7: 给 test_beat_resolution 的 GraphDependencies 注入 provider**

先读 `tests/test_beat_resolution.py`,定位所有 `GraphDependencies(...)` 构造块(含 :220 及其它)。顶部 import 加:

```python
from Memory.default_provider import DefaultActorMemoryProvider
```

每个构造块在 `character_profiles=profiles,` 之后加:

```python
            actor_memory_provider=DefaultActorMemoryProvider(character_profiles=profiles),
```

- [ ] **Step 8: 跑相关测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_beat_group_parallel.py tests/test_beat_resolution.py -q`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add Graph/dependencies.py Graph/actor_paths.py Graph/beat_group.py Graph/dialogue_nodes.py tests/test_beat_group_parallel.py tests/test_beat_resolution.py
git commit -m "$(cat <<'EOF'
refactor(graph): Actor 串/并行路径改由记忆工厂注入 memory_ctx

GraphDependencies 加 actor_memory_provider;串行 resolve_npc_turn_state 与
并行 run_actor_group/_perform_with_retry 各自 build(actor_id, state) 后 perform_turn,
不再透传 character_profiles。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: bootstrap 默认构建 provider

**Files:**
- Modify: `session_bootstrap.py:378-386`(`build_runtime_dependencies`)
- Test: 全量回归

- [ ] **Step 1: 写失败测试(bootstrap 出的 deps 恒有 provider)**

在 `tests/test_actor_memory_e2_wiring.py` 追加:

```python
from Memory.provider import ActorMemoryProvider
from session_bootstrap import build_runtime_dependencies


class BootstrapProviderTest(unittest.TestCase):
    def test_runtime_deps_has_provider(self):
        deps = build_runtime_dependencies(
            mode="heuristic",
            interactive=False,
            character_profiles={},
            scene_config=None,
            default_scene_config_builder=lambda: {
                "scene_id": "s1",
                "default_location_id": "room",
                "default_on_stage": [],
            },
        )
        self.assertIsInstance(deps.actor_memory_provider, ActorMemoryProvider)
```

> 注:`mode` 取非 agent-first 值(如 `"heuristic"`)避免触发 LLM 组件挂载;若该 mode 名不被接受,读 `build_runtime_dependencies` 上方常量确认可用的非 live mode 字符串。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_memory_e2_wiring.py::BootstrapProviderTest -q`
Expected: FAIL(`deps.actor_memory_provider` 为 None)

- [ ] **Step 3: bootstrap 默认构建 provider**

`session_bootstrap.py` 顶部 import 区加:

```python
from Memory.default_provider import DefaultActorMemoryProvider
```

`build_runtime_dependencies` 的 `GraphDependencies(...)` 构造(:378-386),在 `character_profiles=character_profiles,` 之后加一行:

```python
        actor_memory_provider=DefaultActorMemoryProvider(
            character_profiles=character_profiles,
            recent_rounds=3,
            granularity="on_stage",
        ),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_memory_e2_wiring.py::BootstrapProviderTest -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add session_bootstrap.py tests/test_actor_memory_e2_wiring.py
git commit -m "$(cat <<'EOF'
feat(bootstrap): 默认构建 DefaultActorMemoryProvider 注入 deps

build_runtime_dependencies 默认挂 recent_rounds=3 / granularity=on_stage 的工厂,
保证生产链路恒有 provider(本轮强制注入,不做静默降级)。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 集成测试 — 不在场期间对话不进短期

**Files:**
- Test: `tests/test_actor_memory_e2_wiring.py`(追加)

- [ ] **Step 1: 写集成测试(在场过滤真正生效)**

先读 `History/GameMemory.py:6` 的 `HistoryItem` 字段(确认 `on_stage`/`location_id` 快照字段名),再在 `tests/test_actor_memory_e2_wiring.py` 追加:

```python
class PresenceFilterIntegrationTest(unittest.TestCase):
    def test_recent_history_excludes_offstage_turns(self):
        # 角色 npc_a 在 turn 0 在场、turn 1 下场、turn 2 再上场。
        history = [
            {"turn": 0, "actor": "player", "mode": "say", "content": "hi",
             "on_stage": ["player", "npc_a"], "location_id": "room"},
            {"turn": 1, "actor": "npc_b", "mode": "say", "content": "secret while a is gone",
             "on_stage": ["player", "npc_b"], "location_id": "room"},
            {"turn": 2, "actor": "player", "mode": "say", "content": "welcome back",
             "on_stage": ["player", "npc_a"], "location_id": "room"},
        ]
        state = _state_with_history(history)
        state["scene"] = {"location_id": "room", "on_stage": ["player", "npc_a"]}
        provider = DefaultActorMemoryProvider(character_profiles={}, recent_rounds=5, granularity="on_stage")
        ctx = provider.build("npc_a", state)
        contents = [item.get("content") for item in ctx.short_term]
        # npc_a 下场期间(turn 1)的对话不可见。
        self.assertNotIn("secret while a is gone", contents)
        self.assertIn("hi", contents)
        self.assertIn("welcome back", contents)
```

- [ ] **Step 2: 跑测试确认通过(过滤已在 Phase 4 实现)**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest tests/test_actor_memory_e2_wiring.py::PresenceFilterIntegrationTest -q`
Expected: PASS

> 若 FAIL,读 `Memory/scene_filter.py` 确认 `filter_history_by_presence` 判定用的字段名(`on_stage` / `location_id`)与测试构造一致,对齐后再跑。

- [ ] **Step 3: 全量回归**

Run: `cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game" && python -m pytest -q`
Expected: PASS(基线 169 + 本轮新增,全绿)

- [ ] **Step 4: 提交**

```bash
cd "/Users/qiuyunhao.1/Desktop/claude coding/easy_game"
git add tests/test_actor_memory_e2_wiring.py
git commit -m "$(cat <<'EOF'
test(memory): 集成验证不在场角色短期记忆不含离场期间对话

构造角色下场→再上场的 history,断言其回合 recent_history 剔除离场期间条目;
全量回归守住 169 全绿。

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>
EOF
)"
```

---

## 自检清单(计划作者已核)

- **Spec 覆盖**:§3.1 兜底 → Task 1;§3.2 formatter → Task 2;§3.3 三 agent → Task 3;§3.4 接线 → Task 4;§3.5 依赖注入/bootstrap → Task 4+5;§4 测试(formatter/agent/兜底/集成/回归)→ Task 1/2/3/4/6。
- **Placeholder 扫描**:无 TBD/TODO;每个改码步给出完整代码块与确切路径/命令/预期。
- **类型一致**:全链路统一 `memory_ctx: ActorMemoryContext`;`run_actor_group`/`_perform_with_retry` 统一 `provider`;`GraphDependencies.actor_memory_provider: ActorMemoryProvider | None`;工厂 `.build(actor_id, state)` 签名各处一致。
- **超出 spec 但符合意图的扩展**:spec §3.3/§3.4 未点名的两个中间层(三个 instruction builder、`run_actor_group`/`_perform_with_retry`)也随链路收窄——因它们正是 `character_profiles` 的透传通道,不改则签名断裂。
- **不在本轮**:写侧迁移、长期/`recent_short_term_memory` 走 ctx、检索层填实、E3 推广(见 spec §6)。
