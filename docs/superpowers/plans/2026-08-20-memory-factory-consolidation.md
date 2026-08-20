# Memory Factory Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the character memory model to two tiers (L1 main-character / NPC-Actor) with the memory factory producing exactly three parts (short-term, long-term-placeholder, player-impression), delete the per-character subjective long-term/consolidated/short-term queues and the `ActorRuntime` logic that maintains them, and slim `state.characters[id]` so it no longer carries those queues.

**Architecture:** Memory is assembled at Agent-build time by `DefaultActorMemoryProvider` (Pipeline A, read-only), never pre-stored in `state`. The subjective interpretation that used to be baked into each character's long-term events (hardcoded template strings) is dropped; the Director's existing scene-level `DirectorBrief` fields carry stance/direction instead. This plan is Step 1 of 4 — it removes the subjective write side, reshapes the Actor payload, and introduces the write-side `MemoryStore` (read/write separation per spec 4.6). Long-term becomes an empty list here (RAG recall is wired in Step 3); player-impression write logic is **moved into `MemoryStore.record_player_impression` as a pure function** `(memory_state, ...) -> memory_state`, gated to L1 only; `ActorRuntime` calls the store instead of hand-mutating.

**Tech Stack:** Python 3.12 (TypedDict, dataclasses), pytest. In-process LangGraph fallback engine. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-08-20-memory-architecture-consolidation-design.md` sections 4.0–4.3, 4.6, 5 (step 1), 6.

---

## File Structure

**Modified:**
- `CharacterMemory.py` — reduce `CharacterMemoryState` to `player_memory` only; drop L2 config; two-tier `memory_config_for_agent_type`; drop long/consolidated/short normalizers + profile seeding.
- `Actor/ActorRuntime.py` — delete short-term/long-term/consolidated write functions and their call sites in `_apply_memory_updates`; **delegate the player-impression write to `MemoryStore.record_player_impression`** (gated to L1).
- `Actor/ActorFormatter.py` — reshape `_build_actor_payload`: drop `actor_memory`, `recent_short_term_memory`; keep `recent_history` (short-term), `player_memory` (L1 only), `recalled_memories` (empty until Step 3).
- `Memory/context.py` — drop `LongTermView`; `ActorMemoryContext.long_term` removed (or kept as empty placeholder — see Task 6).
- `Memory/default_provider.py` — stop reading `state["characters"][id]["memory"]` for long_term; `build` returns short_term + persona + retrieved only.
- `session_bootstrap.py` — `AGENT_FIRST_COMPONENT_NAMES` drop `l2_actor_agent`; tier resolution helper.
- `Director/DirectorFormatter.py` — remove L2 branch in `_serialize_stage_character`, `_group_actor_ids_by_tier`, L2 rules in `tiered_directing_contract`.

**Created:**
- `Memory/store.py` — `MemoryStore` write-side manager (read/write separation per spec 4.6). This plan adds `record_player_impression(memory_state, *, player_id, relation_delta, event, limit, tuning) -> memory_state` (pure). Steps 2 & 4 extend the same class with `compact`/`derive_views` and `serialize_memory`/`deserialize_memory`.

**Test files (create):**
- `tests/test_character_memory_two_tier.py`
- `tests/test_memory_store_player_impression.py`
- `tests/test_actor_runtime_memory_slim.py`
- `tests/test_actor_formatter_payload_shape.py`
- `tests/test_default_provider_slim.py`
- `tests/test_director_formatter_two_tier.py`

**Ordering note:** Tasks 1→8 are ordered so tests stay green between commits. `CharacterMemoryState` shape change (Task 1) breaks `ActorRuntime`/`ActorFormatter` consumers. Task 2 creates `MemoryStore.record_player_impression` (pure, no consumers yet — lands green independently). Task 3 rewires `ActorRuntime` to delegate to it. Task 6 (drop `long_term` from `ActorMemoryContext`) must run before Task 4/5 assertions. Tasks 1–5 land together conceptually but each has its own failing-test → implement → commit cycle. Run the full suite after Task 5.

---

## Task 1: Two-tier CharacterMemory config + slim state

**Files:**
- Modify: `CharacterMemory.py`
- Test: `tests/test_character_memory_two_tier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_character_memory_two_tier.py
from CharacterMemory import (
    empty_character_memory_state,
    ensure_character_memory_state,
    memory_config_for_agent_type,
)


def test_state_holds_only_player_memory():
    state = empty_character_memory_state()
    assert set(state.keys()) == {"player_memory"}
    assert state["player_memory"] == {
        "overall_impression": "",
        "relation_state": {},
        "key_events": [],
    }


def test_two_tiers_only_l1_and_actor():
    l1 = memory_config_for_agent_type("L1")
    npc = memory_config_for_agent_type("actor")
    # L2 folds into actor tier
    assert memory_config_for_agent_type("L2") == npc
    assert l1["player_memory_limit"] == 8
    assert npc["player_memory_limit"] == 3
    assert set(l1.keys()) == {"player_memory_limit", "player_memory_depth"}


def test_ensure_state_drops_legacy_queues():
    legacy = {
        "long_term_memory": [{"event_summary": "x", "turn_recorded": 1}],
        "short_term_memory": [{"turn": 1, "summary": "y"}],
        "consolidated_memory": [{"turn_start": 0, "turn_end": 1, "event_summary": "z"}],
        "pinned_long_term_memory": [{"event_summary": "p", "turn_recorded": 2}],
        "player_memory": {"overall_impression": "wary", "relation_state": {"player": 1.0}, "key_events": []},
    }
    result = ensure_character_memory_state(legacy, actor_profile={"agent_type": "L1"})
    assert set(result.keys()) == {"player_memory"}
    assert result["player_memory"]["overall_impression"] == "wary"
    assert result["player_memory"]["relation_state"] == {"player": 1.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_character_memory_two_tier.py -v`
Expected: FAIL — `empty_character_memory_state` still returns 5 keys.

- [ ] **Step 3: Rewrite CharacterMemory.py to the slim two-tier model**

Replace the config typing and constants (lines 11–118) with:

```python
class CharacterMemoryConfig(TypedDict):
    player_memory_limit: int
    player_memory_depth: MemoryDepth


L1_MEMORY_CONFIG: CharacterMemoryConfig = {
    "player_memory_limit": 8,
    "player_memory_depth": "full",
}

ACTOR_MEMORY_CONFIG: CharacterMemoryConfig = {
    "player_memory_limit": 3,
    "player_memory_depth": "compact",
}


def memory_config_for_agent_type(agent_type: str) -> CharacterMemoryConfig:
    if agent_type == "L1":
        return dict(L1_MEMORY_CONFIG)
    return dict(ACTOR_MEMORY_CONFIG)


def normalize_character_memory_config(
    value: Any,
    *,
    agent_type: str = "actor",
) -> CharacterMemoryConfig:
    source = value if isinstance(value, Mapping) else {}
    normalized = memory_config_for_agent_type(agent_type)
    try:
        normalized["player_memory_limit"] = max(
            1, int(source.get("player_memory_limit", normalized["player_memory_limit"]) or normalized["player_memory_limit"])
        )
    except (TypeError, ValueError):
        pass
    depth = clean_text(source.get("player_memory_depth", ""), normalized["player_memory_depth"]).lower()
    if depth in {"full", "compact"}:
        normalized["player_memory_depth"] = depth
    return normalized  # type: ignore[return-value]
```

Replace `CharacterMemoryState` (lines 71–76) and remove `LongTermMemoryEvent`, `ConsolidatedMemoryBlock`, `ShortTermMemoryEvent` TypedDicts (lines 22–54):

```python
class CharacterMemoryState(TypedDict):
    player_memory: PlayerImpressionMemory
```

Replace `empty_character_memory_state` (159–167):

```python
def empty_character_memory_state(agent_type: str = "actor") -> CharacterMemoryState:
    del agent_type
    return {"player_memory": empty_player_impression_memory()}
```

Replace `ensure_character_memory_state` (466–508) — drop all queue normalization and profile seeding:

```python
def ensure_character_memory_state(
    value: Any,
    *,
    actor_profile: Mapping[str, Any] | None = None,
) -> CharacterMemoryState:
    agent_type = clean_text((actor_profile or {}).get("agent_type", "actor"), "actor")
    memory_profile = normalize_character_memory_config(
        (actor_profile or {}).get("memory_profile", {}),
        agent_type=agent_type,
    )
    source = value if isinstance(value, Mapping) else {}
    return {
        "player_memory": _normalize_player_impression_memory(
            source.get("player_memory", {}),
            limit=memory_profile["player_memory_limit"],
        ),
    }
```

Delete these now-unused functions entirely: `_normalize_long_term_memory_items`, `_normalize_short_term_memory_items`, `_normalize_consolidated_memory_items`, `_seed_long_term_memory_from_profile`. Keep `_normalize_player_impression_memory`, `_normalize_player_impression_events`, `empty_player_impression_memory`, `_truncate_text`, `PlayerImpressionEvent`, `PlayerImpressionMemory`, `MemoryDepth`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_character_memory_two_tier.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add CharacterMemory.py tests/test_character_memory_two_tier.py
git commit -m "refactor(memory): collapse CharacterMemoryState to player_memory + two tiers"
```

---

## Task 2: Create `MemoryStore` with `record_player_impression`

**Files:**
- Create: `Memory/store.py`
- Test: `tests/test_memory_store_player_impression.py`

**Context:** Per spec 4.6, the write side of memory is consolidated into a `MemoryStore` (read/write separation — `DefaultActorMemoryProvider` stays read-only). Write methods are pure: `(state/memory_state, ...) -> new fragment`. This task adds only `record_player_impression`, which is the player-impression write currently living in `ActorRuntime._append_player_memory`. Steps 2 & 4 of the project extend the same class. The logic is moved verbatim from `ActorRuntime._append_player_memory` (the current 450–475 pure function) so behavior is unchanged — only its home changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_store_player_impression.py
from Memory.store import MemoryStore
from GameplayTuning import RelationshipTuning


def test_record_player_impression_appends_event_and_clamps_relation():
    store = MemoryStore()
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    event = {"turn": 3, "summary": "helped", "impression": "trusting", "relation_delta": 2.0, "tags": ["trust"]}
    result = store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=2.0,
        event=event,
        limit=8,
        tuning=RelationshipTuning(),
    )
    pm = result["player_memory"]
    assert pm["overall_impression"] == "trusting"
    assert pm["relation_state"]["player"] == 2.0
    assert pm["key_events"] == [event]


def test_record_player_impression_is_pure():
    store = MemoryStore()
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    original = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": []}}
    store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=1.0,
        event={"turn": 1, "summary": "s", "impression": "observe", "relation_delta": 1.0, "tags": []},
        limit=8,
        tuning=RelationshipTuning(),
    )
    assert memory_state == original  # input untouched


def test_record_player_impression_trims_to_limit():
    store = MemoryStore()
    existing = [{"turn": i} for i in range(8)]
    memory_state = {"player_memory": {"overall_impression": "", "relation_state": {}, "key_events": existing}}
    event = {"turn": 99, "summary": "", "impression": "observe", "relation_delta": 0.0, "tags": []}
    result = store.record_player_impression(
        memory_state,
        player_id="player",
        relation_delta=0.0,
        event=event,
        limit=8,
        tuning=RelationshipTuning(),
    )
    assert len(result["player_memory"]["key_events"]) == 8
    assert result["player_memory"]["key_events"][-1] == event
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_store_player_impression.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Memory.store'`.

- [ ] **Step 3: Create `Memory/store.py`**

```python
from __future__ import annotations

from GameplayTuning import RelationshipTuning


def _clamp_relationship(value: float, tuning: RelationshipTuning) -> float:
    return max(tuning.min_value, min(tuning.max_value, value))


class MemoryStore:
    """Write-side memory manager (spec 4.6). Pure functions: take state/memory fragments, return new ones.

    Read side stays in DefaultActorMemoryProvider. This class never mutates its inputs and holds no memory state.
    """

    def record_player_impression(
        self,
        memory_state: dict[str, object],
        *,
        player_id: str,
        relation_delta: float,
        event: dict[str, object],
        limit: int,
        tuning: RelationshipTuning,
    ) -> dict[str, object]:
        player_memory = dict(memory_state.get("player_memory", {}))
        key_events = list(player_memory.get("key_events", []))
        key_events.append(event)
        relation_state = dict(player_memory.get("relation_state", {}))
        relation_state[player_id] = _clamp_relationship(
            float(relation_state.get(player_id, 0.0) or 0.0) + relation_delta,
            tuning,
        )
        return {
            **memory_state,
            "player_memory": {
                **player_memory,
                "overall_impression": event["impression"],
                "relation_state": relation_state,
                "key_events": key_events[-limit:],
            },
        }
```

Note: verify `RelationshipTuning`'s clamp attribute names (`min_value`/`max_value`) match the current `_clamp_relationship` in `ActorRuntime.py`. If ActorRuntime clamps differently, copy that exact logic — this must be behavior-identical to the code being moved.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_store_player_impression.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add Memory/store.py tests/test_memory_store_player_impression.py
git commit -m "feat(memory): add MemoryStore write-side manager with record_player_impression"
```

---

## Task 3: Strip subjective queue writes from ActorRuntime, delegate impression to MemoryStore

**Files:**
- Modify: `Actor/ActorRuntime.py`
- Test: `tests/test_actor_runtime_memory_slim.py`

**Context:** `_apply_memory_updates` (502–599) currently writes short-term, long-term, consolidated, and player-impression memory. Keep ONLY the player-impression write, gate it to L1, and **delegate the actual write to `MemoryStore.record_player_impression`** (Task 2) rather than the local `_append_player_memory`. Delete `_build_short_term_memory_event`, `_derive_long_term_belief`, `_should_record_long_term_memory`, `_build_long_term_memory_event`, `_append_short_term_memory`, `_append_long_term_memory`, `_select_consolidation_topic`, and `_append_player_memory` (moved to MemoryStore). Keep `_build_player_memory_event`, `_player_memory_targets`, `_relation_delta_toward_player`, `_clamp_relationship` in ActorRuntime (they compute the event + delta; the store only writes it).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actor_runtime_memory_slim.py
from Actor.ActorRuntime import apply_resolved_act
from GameplayTuning import RelationshipTuning


def _base_state(resolved_act):
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["player", "npc", "hero"]},
        "player": {"controlled_character": "player"},
        "characters": {
            "player": {"intent": "", "memory": {}},
            "npc": {"intent": "", "memory": {}},
            "hero": {"intent": "", "memory": {}},
        },
        "history": [],
        "runtime": {
            "turn_index": 5,
            "resolved_act": resolved_act,
            "pending_beat_actors": [],
            "beat_fallback_turns_remaining": 0,
        },
    }


def _act(**over):
    base = {
        "actor": "player", "mode": "speak", "target": "hero", "content": "hi",
        "spoken_text": "hi", "nonverbal_action": "", "next_intent": "",
        "emotion_update": {}, "relationship_update": {"hero": 2.0},
        "revealed_facts": [], "triggered_plot_flags": {},
        "should_end_scene": False, "should_end_chapter": False,
    }
    base.update(over)
    return base


def test_no_long_term_or_short_term_queues_written():
    profiles = {
        "hero": {"agent_type": "L1"},
        "npc": {"agent_type": "actor"},
        "player": {"agent_type": "actor"},
    }
    state = _base_state(_act())
    result = apply_resolved_act(state, RelationshipTuning(), character_profiles=profiles)
    for cid in ("player", "npc", "hero"):
        mem = result["characters"][cid]["memory"]
        assert set(mem.keys()) == {"player_memory"}


def test_player_impression_only_for_l1():
    profiles = {
        "hero": {"agent_type": "L1"},
        "npc": {"agent_type": "actor"},
        "player": {"agent_type": "actor"},
    }
    # player addresses both hero (L1) and npc (actor); reciprocal relationship updates
    state = _base_state(_act(actor="player", target="hero"))
    result = apply_resolved_act(state, RelationshipTuning(), character_profiles=profiles)
    # L1 hero records a player impression; NPC does not
    assert result["characters"]["hero"]["memory"]["player_memory"]["key_events"]
    assert result["characters"]["npc"]["memory"]["player_memory"]["key_events"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_actor_runtime_memory_slim.py -v`
Expected: FAIL — memory still has 5 keys / NPC still gets impression.

- [ ] **Step 3: Delete the subjective write functions**

In `Actor/ActorRuntime.py`, delete these function definitions entirely:
`_build_short_term_memory_event` (159–174), `_derive_long_term_belief` (177–196), `_should_record_long_term_memory` (199–207), `_build_long_term_memory_event` (210–286), `_append_short_term_memory` (332–343), `_append_long_term_memory` (346–421), `_select_consolidation_topic` (424–447), and `_append_player_memory` (450–475, now moved to `MemoryStore`). Also delete `_priority_rank` (60–65) which is now only used by consolidation. Keep `_build_player_memory_event`, `_player_memory_targets`, `_relation_delta_toward_player`, and `_clamp_relationship` — they still compute the event and delta that get handed to the store.

Add the store import + module-level instance near the top of the file:

```python
from Memory.store import MemoryStore

_MEMORY_STORE = MemoryStore()
```

- [ ] **Step 4: Rewrite `_apply_memory_updates` to player-impression-only, L1-gated**

Add a tier helper near the top (after `_resolve_memory_config`):

```python
def _is_l1(character_id: str, character_profiles: dict[str, CharacterProfile] | None) -> bool:
    profile = _resolve_character_profile(character_id, character_profiles)
    return str(profile.get("agent_type", "actor") or "actor") == "L1"
```

Replace `_apply_memory_updates` (502–599) with:

```python
def _apply_memory_updates(
    state: GameState,
    *,
    characters: dict[str, CharacterRuntimeState],
    actor_id: str,
    resolved_act: ResolvedAct,
    turn_index: int,
    character_profiles: dict[str, CharacterProfile] | None,
    reciprocal_updates: dict[str, dict[str, float]],
    relationship_tuning: RelationshipTuning,
) -> dict[str, CharacterRuntimeState]:
    updated = dict(characters)
    player_id = str(state["player"].get("controlled_character", "") or "player")
    player_targets = _dedupe_character_ids(
        [
            character_id
            for character_id in _player_memory_targets(
                state,
                resolved_act,
                actor_id=actor_id,
                player_id=player_id,
            )
            if character_id in updated
            and character_id != player_id
            and _is_l1(character_id, character_profiles)
        ]
    )

    for character_id in player_targets:
        runtime = updated.get(character_id)
        if runtime is None:
            continue
        memory_state = _resolve_memory_state(character_id, runtime, character_profiles)
        memory_config = _resolve_memory_config(character_id, character_profiles)
        relation_delta = _relation_delta_toward_player(
            character_id,
            player_id=player_id,
            actor_id=actor_id,
            resolved_act=resolved_act,
            reciprocal_updates=reciprocal_updates,
        )
        memory_state = _MEMORY_STORE.record_player_impression(
            memory_state,
            player_id=player_id,
            relation_delta=relation_delta,
            event=_build_player_memory_event(
                resolved_act,
                relation_delta=relation_delta,
                turn_index=turn_index,
            ),
            limit=int(memory_config["player_memory_limit"]),
            tuning=relationship_tuning,
        )
        updated[character_id] = {**runtime, "memory": memory_state}

    return updated
```

The module-level store instance is stateless (see Task 2) — declare it once near the top of `ActorRuntime.py` imports:

```python
from Memory.store import MemoryStore

_MEMORY_STORE = MemoryStore()
```

Note: the actor/other-runtime `memory_state=_resolve_memory_state(...)` calls in `apply_resolved_act` (644, 655) still work — they now produce `{"player_memory": ...}` only. Leave them; they seed a valid empty memory for characters not otherwise touched.

- [ ] **Step 5: Run test + full suite**

Run: `python -m pytest tests/test_actor_runtime_memory_slim.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add Actor/ActorRuntime.py tests/test_actor_runtime_memory_slim.py
git commit -m "refactor(actor): delegate player impression to MemoryStore, drop subjective writes"
```

---

## Task 4: Reshape Actor payload

**Files:**
- Modify: `Actor/ActorFormatter.py`
- Test: `tests/test_actor_formatter_payload_shape.py`

**Context:** `_build_actor_payload` (38–89) builds `actor_memory` (pinned/consolidated/long_term), `recent_short_term_memory`, and `player_memory` from the now-deleted queues. Drop `actor_memory` and `recent_short_term_memory`. Keep `recent_history` (= `memory_ctx.short_term`), `player_memory` (L1 only), and `recalled_memories` (= `memory_ctx.retrieved`, empty until Step 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actor_formatter_payload_shape.py
from Actor.ActorFormatter import _build_actor_payload
from Memory.context import ActorMemoryContext


def _state(agent_type):
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "g", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "focus_character": "hero"},
        "scene_plan": {"must_happen": [], "character_objectives": {}},
        "director_brief": {"beat_goal": "", "who_should_respond": []},
        "characters": {
            "hero": {"intent": "fight", "memory": {"player_memory": {"overall_impression": "wary", "relation_state": {}, "key_events": []}}},
        },
        "runtime": {"next_act": None},
    }


def _ctx(agent_type):
    return ActorMemoryContext(
        actor_id="hero",
        persona={"agent_type": agent_type, "memory_profile": {}},
        short_term=[{"turn": 1, "content": "hi", "actor": "hero"}],
        retrieved=[],
    )


def test_payload_drops_legacy_memory_keys():
    payload = _build_actor_payload(_state("L1"), _ctx("L1"))
    assert "actor_memory" not in payload
    assert "recent_short_term_memory" not in payload
    assert payload["recent_history"] == [{"turn": 1, "content": "hi", "actor": "hero"}]
    assert payload["recalled_memories"] == []


def test_player_memory_present_for_l1_absent_for_npc():
    l1_payload = _build_actor_payload(_state("L1"), _ctx("L1"))
    assert l1_payload["player_memory"]["overall_impression"] == "wary"
    npc_payload = _build_actor_payload(_state("actor"), _ctx("actor"))
    assert "player_memory" not in npc_payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_actor_formatter_payload_shape.py -v`
Expected: FAIL — `_build_actor_payload` still emits `actor_memory` and always includes `player_memory`; also the `ActorMemoryContext` no longer has `long_term` (see Task 6) — if Task 6 not yet done, this test fails on construction. Implement Task 6 first if you hit that; the plan orders Task 6 before running this. (See ordering note.)

- [ ] **Step 3: Rewrite `_build_actor_payload`**

Replace `_build_actor_payload` (38–89):

```python
def _build_actor_payload(
    state: GameState,
    memory_ctx: ActorMemoryContext,
) -> dict[str, Any]:
    planned_act = state["runtime"].get("next_act")
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
```

Note: `l2_profile` dropped from `agent_contract` (two-tier). Import stays: `normalize_character_memory_config`, `ensure_character_memory_state` are still used.

- [ ] **Step 4: Run test + full suite**

Run: `python -m pytest tests/test_actor_formatter_payload_shape.py tests/test_actor_runtime_memory_slim.py tests/test_character_memory_two_tier.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Actor/ActorFormatter.py tests/test_actor_formatter_payload_shape.py
git commit -m "refactor(actor): reshape payload — drop subjective queues, L1-only player memory"
```

---

## Task 5: Slim the memory provider (Pipeline A)

**Files:**
- Modify: `Memory/default_provider.py`
- Test: `tests/test_default_provider_slim.py`

**Context:** `build` (43–77) reads `state["characters"][id]["memory"]` into a `LongTermView`. Since the queues are gone, drop that read. The provider now returns short_term + persona + retrieved.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_default_provider_slim.py
from Memory.default_provider import DefaultActorMemoryProvider


def _state():
    return {
        "scene": {"location_id": "loc", "on_stage": ["hero"]},
        "characters": {"hero": {"intent": "explore", "memory": {"player_memory": {}}}},
        "history": [
            {"turn": 1, "actor": "hero", "content": "line", "on_stage": ["hero"], "location_id": "loc"},
        ],
    }


def test_build_returns_short_term_persona_retrieved_no_long_term():
    provider = DefaultActorMemoryProvider(
        character_profiles={"hero": {"agent_type": "L1", "memory_profile": {}}},
        recent_rounds=3,
    )
    ctx = provider.build("hero", _state())
    assert ctx.actor_id == "hero"
    assert ctx.short_term  # presence-filtered history
    assert ctx.retrieved == []  # no recall service wired
    assert not hasattr(ctx, "long_term")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_default_provider_slim.py -v`
Expected: FAIL — `ctx` still has `long_term`.

- [ ] **Step 3: Remove the long_term read**

In `Memory/default_provider.py`, delete the `LongTermView` import (line 7 becomes `from Memory.context import ActorMemoryContext`), and delete the `memory = ...` / `long_term = LongTermView(...)` block (58–64). Update the return (69–77):

```python
        return ActorMemoryContext(
            actor_id=actor_id,
            persona=persona,
            short_term=short_term,
            retrieved=self.retrieve(
                actor_id, query, user_id=self._user_id, player_id=self._player_id
            ),
        )
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_default_provider_slim.py -v`
Expected: PASS (depends on Task 6 removing `long_term` from the dataclass; if not yet done, do Task 6 first).

- [ ] **Step 5: Commit**

```bash
git add Memory/default_provider.py tests/test_default_provider_slim.py
git commit -m "refactor(memory): provider stops reading per-character long-term queues"
```

---

## Task 6: Drop `LongTermView` and `long_term` from ActorMemoryContext

**Files:**
- Modify: `Memory/context.py`
- Test: covered by Tasks 3 & 4 tests (`not hasattr(ctx, "long_term")`).

**Ordering:** Do this task BEFORE running Task 4 Step 4 and Task 5 Step 4 (the dataclass field removal is what those assertions depend on). It is listed here because it is the smallest unit; execute it right after Task 3.

- [ ] **Step 1: Rewrite `Memory/context.py`**

Replace the whole file:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from CharacterProfile import CharacterProfile
from History.GameMemory import HistoryItem


@dataclass(frozen=True)
class ActorMemoryContext:
    """喂给 agent 的收窄只读视图。

    - persona:沿用现有 CharacterProfile(人设 + memory_profile 配置)。
    - short_term:在场过滤后的最近数轮 history 明细。
    - retrieved:长期 RAG 召回(仅 L1;Step 3 接实,此前恒空)。
    """
    actor_id: str
    persona: CharacterProfile
    short_term: list[HistoryItem]
    retrieved: list[Any]
```

- [ ] **Step 2: Grep for other `LongTermView` / `.long_term` consumers**

Run: `grep -rn "LongTermView\|\.long_term\b" --include='*.py' . | grep -v tests/`
Expected: no matches outside files already edited. If any remain, fix them (they are dead reads of the removed field).

- [ ] **Step 3: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (fix any straggler import of removed symbols).

- [ ] **Step 4: Commit**

```bash
git add Memory/context.py
git commit -m "refactor(memory): drop LongTermView + long_term field from ActorMemoryContext"
```

---

## Task 7: Remove L2 tier from bootstrap + Director formatter

**Files:**
- Modify: `session_bootstrap.py`, `Director/DirectorFormatter.py`
- Test: `tests/test_director_formatter_two_tier.py`

**Context:** Two-tier means the `l2_actor_agent` component and DirectorFormatter's L2 branches are dead. `DirectorBrief` already provides scene-level directing (spec 4.3) — no new fields. Just remove L2 handling; unknown/L2 agent types fall into the NPC-Actor path.

- [ ] **Step 1: Inspect the L2 branches (read before editing)**

Run: `grep -n "L2\|l2_\|_group_actor_ids_by_tier\|tiered_directing_contract\|scene_support_bias" Director/DirectorFormatter.py`
Read each hit; the L2 branch in `_serialize_stage_character` and the L2 key in `_group_actor_ids_by_tier` / `tiered_directing_contract` are the removal targets. L1 and actor/NPC paths stay.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_director_formatter_two_tier.py
from Director.DirectorFormatter import _group_actor_ids_by_tier


def test_l2_folds_into_actor_tier():
    profiles = {
        "hero": {"agent_type": "L1"},
        "old_l2": {"agent_type": "L2"},
        "npc": {"agent_type": "actor"},
    }
    grouped = _group_actor_ids_by_tier(["hero", "old_l2", "npc"], profiles)
    assert "L2" not in grouped
    assert "hero" in grouped["L1"]
    assert set(grouped["actor"]) == {"old_l2", "npc"}
```

Adjust the expected dict keys to match the actual return shape you observe in Step 1 (the test's job is to prove L2 no longer produces a distinct bucket).

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_director_formatter_two_tier.py -v`
Expected: FAIL — `L2` still a separate bucket.

- [ ] **Step 4: Remove L2 branches**

In `Director/DirectorFormatter.py`:
- `_group_actor_ids_by_tier`: map `agent_type == "L1"` → L1 bucket, everything else (including `"L2"`) → actor bucket. Delete the dedicated L2 branch.
- `_serialize_stage_character`: delete the `elif agent_type == "L2":` branch; L2 falls through to the default/NPC serialization.
- `tiered_directing_contract`: delete L2-specific rule entries; keep L1 + actor rules.
- Remove now-dead `scene_support_bias` helper if it is only referenced by removed L2 code (grep to confirm before deleting).

In `session_bootstrap.py`:
- Remove `"l2_actor_agent"` from `AGENT_FIRST_COMPONENT_NAMES` (line 46).

- [ ] **Step 5: Grep for orphaned l2_actor_agent references**

Run: `grep -rn "l2_actor_agent\|build_l2_actor\|build_l2_actor_instruction" --include='*.py' . | grep -v tests/`
For each hit outside a test, either route it to the NPC-Actor agent or remove it. Note `Actor/ActorFormatter.py:build_l2_actor_instruction` may still exist — leave the function (harmless) unless a caller is removed; if `l2_actor_agent` was its only consumer via the scheduler, confirm the scheduler no longer selects an L2 path.

- [ ] **Step 6: Run test + full suite**

Run: `python -m pytest tests/test_director_formatter_two_tier.py tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add session_bootstrap.py Director/DirectorFormatter.py tests/test_director_formatter_two_tier.py
git commit -m "refactor(director): two-tier — fold L2 into NPC-Actor, drop L2 directing branches"
```

---

## Task 8: Integration smoke — one player action end-to-end

**Files:**
- Test: `tests/test_memory_consolidation_smoke.py`

**Context:** Verify a full player action still resolves with the slimmed memory model and no `KeyError` on removed fields, using the mock (non-agent) path so no LLM is called.

- [ ] **Step 1: Write the smoke test**

```python
# tests/test_memory_consolidation_smoke.py
from session_bootstrap import build_graph_dependencies, build_default_state


def test_slim_memory_action_smoke():
    deps = build_graph_dependencies(mode="mock", interactive=False)
    state = build_default_state()
    # provider builds an actor context without touching removed queues
    provider = deps.actor_memory_provider
    ctx = provider.build("player", state)
    assert ctx.short_term is not None
    assert not hasattr(ctx, "long_term")
    # ensure state.characters carries no legacy memory queues
    mem = state["characters"]["player"].get("memory", {})
    assert "long_term_memory" not in mem
    assert "short_term_memory" not in mem
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_memory_consolidation_smoke.py -v`
Expected: PASS. If `mode="mock"` is not a valid mode, use the mode used elsewhere in the suite for non-agent runs (grep `build_graph_dependencies(` in existing tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_memory_consolidation_smoke.py
git commit -m "test(memory): end-to-end smoke for slimmed two-tier memory model"
```

---

## Self-Review Checklist (run before handoff)

1. **Spec coverage:** 4.0 (factory-managed, state slim) → Tasks 1,5,6,8. 4.1 (two tiers) → Tasks 1,7. 4.2 (three parts; NPC = short-term only, L1 = +player impression, long-term placeholder) → Tasks 1,3,4. 4.3 (delete subjective queues + ActorRuntime logic; director takes over) → Tasks 3,7. 4.6 (read/write separation; player impression via MemoryStore) → Tasks 2,3. Section 6 item 2 (player_memory L1-only) → Task 3. Item 3 (payload shape impact) → Task 4. Item 4 (L2 cleanup in DirectorFormatter) → Task 7.
2. **Placeholder scan:** Task 7 test keys marked "adjust to actual return shape" — this is a deliberate read-first instruction, not a placeholder; the implementer confirms shape in Step 1. Task 2's `RelationshipTuning` clamp attribute note is a verify-then-copy instruction, not a placeholder.
3. **Type consistency:** `CharacterMemoryConfig` reduced to 2 keys used identically in `memory_config_for_agent_type`/`normalize_character_memory_config` (Task 1) and read via `["player_memory_limit"]` in ActorRuntime (Task 3) and ActorFormatter (Task 4). `MemoryStore.record_player_impression` signature (Task 2) matches the call site in `_apply_memory_updates` (Task 3). `ActorMemoryContext` fields (actor_id/persona/short_term/retrieved) match provider return (Task 5) and formatter reads (Task 4).
4. **Long-term = empty here:** `recalled_memories` stays `_format_recalled(retrieved)` which is empty until Step 3 wires the recall service — consistent with spec 4.4 (RAG in Step 3).
