# Persistence Serialization Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route MySQL 存档 memory read/write through `MemoryStore.serialize_memory` / `deserialize_memory` so the persistence layer no longer reaches into memory internals, and normalize old saves that still carry the deleted subjective queues.

**Architecture:** `MemoryStore` (Memory 模块的写侧, pure functional) grows two methods: `serialize_memory(state) -> dict` extracts the canonical memory fragment (`state["memory"]` + each character's `memory` sub-dict); `deserialize_memory(fragment) -> dict` normalizes it on load — filling missing keys via `empty_memory_state()` and dropping the deleted per-character subjective queues (`long_term_memory` / `consolidated_memory` / `short_term_memory` / `pinned_long_term_memory`), keeping only `player_memory`. `Persistence` (`build_world_state_payload`, `Store.load_player_session`) obtains/normalizes the memory fragment through `MemoryStore` instead of `clone_json`-ing `state["memory"]`/`state["characters"]` blindly. Separately, `_resolve_story_layer` drops the stale `L2` tier for the two-tier (L1 / actor) model.

**Tech Stack:** Python 3.12, pytest, SQLAlchemy models (`PlayerSaveSnapshot`, `PlayerWorldState`), `clone_json` deepcopy isolation.

**Dependency note:** This is Step 4 of 4. It builds on `Memory/store.py` created in Step 1 (`docs/superpowers/plans/2026-08-20-memory-factory-consolidation.md`) and extended in Step 2 (`docs/superpowers/plans/2026-08-20-async-memory-compaction.md`). If for some reason `Memory/store.py` does not yet exist, create the minimal `MemoryStore` class (from Step 1 Task 2) before Task 1 here. This plan assumes the subjective queues have already been removed from `ActorRuntime` write logic (Step 1) — the `deserialize_memory` normalization exists to clean up *saves written before that change*.

---

## File Structure

- Modify: `Memory/store.py` — add `serialize_memory` + `deserialize_memory` pure methods (and a module-level `_PLAYER_MEMORY_ONLY` constant listing kept character-memory keys).
- Modify: `Persistence/store_snapshot.py`
  - `build_world_state_payload` (51-63) — obtain the `memory`/`characters` portions via `MemoryStore.serialize_memory`.
  - `_resolve_story_layer` (101-108) — drop stale `L2`.
- Modify: `Persistence/Store.py` — `load_player_session` (234-257) normalizes the loaded `state`'s memory fragment via `MemoryStore.deserialize_memory` before returning.
- Test: `tests/test_memory_store_serialization.py` — serialize/deserialize unit + round-trip + old-save normalization.
- Test: `tests/test_store_snapshot_story_layer.py` — `_resolve_story_layer` two-tier behavior.

---

### Task 1: MemoryStore.serialize_memory

**Files:**
- Modify: `Memory/store.py`
- Test: `tests/test_memory_store_serialization.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_store_serialization.py`:

```python
from Memory.store import MemoryStore


def _state_with_memory():
    return {
        "memory": {
            "last_compressed_turn": 7,
            "scene_memory": {"summary": "s", "key_events": [], "compressed_blocks": []},
            "playwright_memory": {"beats": []},
            "director_memory": {"notes": []},
            "scheduler_memory": {"pressure": []},
        },
        "characters": {
            "lin": {
                "id": "lin",
                "emotion": "calm",
                "memory": {
                    "player_memory": {
                        "overall_impression": "ally",
                        "relation_state": {"player": 1.5},
                        "key_events": [{"impression": "helped me"}],
                    },
                    "short_term_memory": [{"summary": "old queue"}],
                    "long_term_memory": [{"belief_formed": "stale"}],
                },
            },
            "npc": {"id": "npc", "emotion": "neutral"},
        },
    }


def test_serialize_extracts_global_memory_and_per_character_player_memory():
    store = MemoryStore()
    fragment = store.serialize_memory(_state_with_memory())

    assert fragment["memory"]["last_compressed_turn"] == 7
    assert fragment["memory"]["scene_memory"]["summary"] == "s"
    # per-character memory keeps ONLY player_memory
    assert fragment["character_memory"]["lin"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 1.5},
            "key_events": [{"impression": "helped me"}],
        }
    }
    # character with no memory sub-dict produces no entry
    assert "npc" not in fragment["character_memory"]


def test_serialize_is_pure_no_mutation():
    store = MemoryStore()
    state = _state_with_memory()
    store.serialize_memory(state)
    # subjective queue still present in the source state (not stripped in place)
    assert state["characters"]["lin"]["memory"]["short_term_memory"] == [{"summary": "old queue"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store_serialization.py::test_serialize_extracts_global_memory_and_per_character_player_memory -v`
Expected: FAIL with `AttributeError: 'MemoryStore' object has no attribute 'serialize_memory'`

- [ ] **Step 3: Write minimal implementation**

In `Memory/store.py`, add near the top (after existing imports):

```python
from History.GameMemory import empty_memory_state

_KEPT_CHARACTER_MEMORY_KEYS = ("player_memory",)
```

Add to the `MemoryStore` class:

```python
    def serialize_memory(self, state: dict) -> dict:
        raw_memory = state.get("memory") or {}
        memory_fragment = {
            key: deepcopy(raw_memory[key])
            for key in raw_memory
        }
        character_memory: dict = {}
        for character_id, character in (state.get("characters") or {}).items():
            if not isinstance(character, dict):
                continue
            char_mem = character.get("memory")
            if not isinstance(char_mem, dict):
                continue
            kept = {
                key: deepcopy(char_mem[key])
                for key in _KEPT_CHARACTER_MEMORY_KEYS
                if key in char_mem
            }
            if kept:
                character_memory[character_id] = kept
        return {"memory": memory_fragment, "character_memory": character_memory}
```

Ensure `from copy import deepcopy` is imported at the top of `Memory/store.py` (add it if missing).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_store_serialization.py -v`
Expected: both serialize tests PASS

- [ ] **Step 5: Commit**

```bash
git add Memory/store.py tests/test_memory_store_serialization.py
git commit -m "feat(memory): MemoryStore.serialize_memory extracts canonical memory fragment"
```

---

### Task 2: MemoryStore.deserialize_memory (normalize + drop stale queues)

**Files:**
- Modify: `Memory/store.py`
- Test: `tests/test_memory_store_serialization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory_store_serialization.py`:

```python
from History.GameMemory import empty_memory_state


def test_deserialize_fills_missing_global_memory_keys():
    store = MemoryStore()
    fragment = {"memory": {"last_compressed_turn": 3}, "character_memory": {}}
    result = store.deserialize_memory(fragment)

    base = empty_memory_state()
    assert result["memory"]["last_compressed_turn"] == 3
    # missing keys backfilled from empty_memory_state
    assert result["memory"]["scene_memory"] == base["scene_memory"]
    assert result["memory"]["playwright_memory"] == base["playwright_memory"]
    assert result["character_memory"] == {}


def test_deserialize_drops_stale_subjective_queues_from_old_saves():
    store = MemoryStore()
    fragment = {
        "memory": {},
        "character_memory": {
            "lin": {
                "player_memory": {"overall_impression": "ally"},
                "short_term_memory": [{"summary": "stale"}],
                "long_term_memory": [{"belief_formed": "stale"}],
                "consolidated_memory": [{"x": 1}],
                "pinned_long_term_memory": [{"y": 2}],
            }
        },
    }
    result = store.deserialize_memory(fragment)

    assert result["character_memory"]["lin"] == {"player_memory": {"overall_impression": "ally"}}


def test_deserialize_handles_none_fragment():
    store = MemoryStore()
    result = store.deserialize_memory(None)
    assert result["memory"] == empty_memory_state()
    assert result["character_memory"] == {}


def test_serialize_deserialize_round_trip_is_stable():
    store = MemoryStore()
    fragment = store.serialize_memory(_state_with_memory())
    first = store.deserialize_memory(fragment)
    # re-serializing the normalized character_memory and deserializing again is idempotent
    second = store.deserialize_memory({
        "memory": first["memory"],
        "character_memory": first["character_memory"],
    })
    assert first["character_memory"] == second["character_memory"]
    assert first["character_memory"]["lin"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 1.5},
            "key_events": [{"impression": "helped me"}],
        }
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store_serialization.py::test_deserialize_drops_stale_subjective_queues_from_old_saves -v`
Expected: FAIL with `AttributeError: 'MemoryStore' object has no attribute 'deserialize_memory'`

- [ ] **Step 3: Write minimal implementation**

Add to the `MemoryStore` class in `Memory/store.py`:

```python
    def deserialize_memory(self, fragment: dict | None) -> dict:
        fragment = fragment or {}
        base = empty_memory_state()
        raw_memory = fragment.get("memory") or {}
        memory = {**base, **{key: deepcopy(raw_memory[key]) for key in raw_memory if key in base}}
        character_memory: dict = {}
        for character_id, kept in (fragment.get("character_memory") or {}).items():
            if not isinstance(kept, dict):
                continue
            normalized = {
                key: deepcopy(kept[key])
                for key in _KEPT_CHARACTER_MEMORY_KEYS
                if key in kept
            }
            if normalized:
                character_memory[character_id] = normalized
        return {"memory": memory, "character_memory": character_memory}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_store_serialization.py -v`
Expected: all serialize + deserialize tests PASS

- [ ] **Step 5: Commit**

```bash
git add Memory/store.py tests/test_memory_store_serialization.py
git commit -m "feat(memory): MemoryStore.deserialize_memory normalizes fragment and drops stale queues"
```

---

### Task 3: Route build_world_state_payload memory extraction through MemoryStore

**Files:**
- Modify: `Persistence/store_snapshot.py:51-63`
- Test: `tests/test_memory_store_serialization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory_store_serialization.py`:

```python
from Persistence.store_snapshot import build_world_state_payload


def test_world_state_payload_strips_stale_character_queues():
    snapshot = {
        "state": {
            "plot": {}, "scene": {}, "runtime": {}, "scene_plan": {},
            "director_brief": {}, "history": [], "player": {},
            "memory": {"last_compressed_turn": 4},
            "characters": {
                "lin": {
                    "id": "lin",
                    "emotion": "calm",
                    "memory": {
                        "player_memory": {"overall_impression": "ally"},
                        "short_term_memory": [{"summary": "stale"}],
                    },
                }
            },
        }
    }
    payload = build_world_state_payload(snapshot)

    # non-memory keys unchanged
    assert payload["plot"] == {}
    assert payload["history"] == []
    # character retains identity + runtime, but subjective queue is gone
    assert payload["characters"]["lin"]["emotion"] == "calm"
    assert payload["characters"]["lin"]["memory"] == {"player_memory": {"overall_impression": "ally"}}
    # global memory backfilled to full shape
    assert payload["memory"]["last_compressed_turn"] == 4
    assert "scene_memory" in payload["memory"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_store_serialization.py::test_world_state_payload_strips_stale_character_queues -v`
Expected: FAIL — `payload["characters"]["lin"]["memory"]` still contains `short_term_memory` (current code clone_json's the whole character verbatim).

- [ ] **Step 3: Write minimal implementation**

In `Persistence/store_snapshot.py`, add import near the top:

```python
from Memory.store import MemoryStore
```

Add a module-level singleton after the imports:

```python
_MEMORY_STORE = MemoryStore()
```

Replace `build_world_state_payload` (51-63) with:

```python
def build_world_state_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = require_snapshot_value(snapshot, "state", dict)
    memory_fragment = _MEMORY_STORE.deserialize_memory(_MEMORY_STORE.serialize_memory(state))
    payload = {key: clone_json(state.get(key, default)) for key, default in (
        ("plot", {}),
        ("scene", {}),
        ("runtime", {}),
        ("scene_plan", {}),
        ("director_brief", {}),
        ("history", []),
        ("player", {}),
    )}
    payload["memory"] = memory_fragment["memory"]
    payload["characters"] = _merge_character_memory(
        clone_json(state.get("characters", {})),
        memory_fragment["character_memory"],
    )
    return payload
```

Add a helper above `build_world_state_payload`:

```python
def _merge_character_memory(
    characters: dict[str, Any], character_memory: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for character_id, character in characters.items():
        if not isinstance(character, dict):
            result[character_id] = character
            continue
        merged = {key: value for key, value in character.items() if key != "memory"}
        kept = character_memory.get(character_id)
        if kept:
            merged["memory"] = kept
        result[character_id] = merged
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_store_serialization.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add Persistence/store_snapshot.py tests/test_memory_store_serialization.py
git commit -m "refactor(persistence): route world_state memory extraction through MemoryStore"
```

---

### Task 4: Normalize loaded memory in Store.load_player_session

**Files:**
- Modify: `Persistence/Store.py:234-257`
- Test: `tests/test_store_load_normalizes_memory.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_load_normalizes_memory.py`. This is a unit test on the extracted normalization helper (not a full DB round-trip — the DB round-trip is exercised by Task 6 integration). First we extract the state-normalization into a helper so it is unit-testable:

```python
from Persistence.Store import normalize_loaded_state


def test_normalize_loaded_state_drops_stale_character_queues():
    state = {
        "memory": {"last_compressed_turn": 2},
        "characters": {
            "lin": {
                "id": "lin",
                "emotion": "calm",
                "memory": {
                    "player_memory": {"overall_impression": "ally"},
                    "long_term_memory": [{"belief_formed": "stale"}],
                },
            }
        },
        "history": [{"turn": 1}],
    }
    result = normalize_loaded_state(state)

    assert result["characters"]["lin"]["emotion"] == "calm"
    assert result["characters"]["lin"]["memory"] == {"player_memory": {"overall_impression": "ally"}}
    assert "scene_memory" in result["memory"]
    # non-memory state untouched
    assert result["history"] == [{"turn": 1}]


def test_normalize_loaded_state_handles_missing_memory():
    state = {"characters": {}, "history": []}
    result = normalize_loaded_state(state)
    assert "scene_memory" in result["memory"]
    assert result["characters"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store_load_normalizes_memory.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_loaded_state'`

- [ ] **Step 3: Write minimal implementation**

In `Persistence/Store.py`, add import near the top (with the other imports):

```python
from Memory.store import MemoryStore
from Persistence.store_snapshot import _merge_character_memory
```

Add a module-level singleton and a normalization function (place above the `GameSaveStore` class):

```python
_MEMORY_STORE = MemoryStore()


def normalize_loaded_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    fragment = _MEMORY_STORE.deserialize_memory(_MEMORY_STORE.serialize_memory(state))
    normalized = dict(state)
    normalized["memory"] = fragment["memory"]
    normalized["characters"] = _merge_character_memory(
        dict(state.get("characters", {})),
        fragment["character_memory"],
    )
    return normalized
```

Then in `load_player_session` (234-257), change the `("state", snapshot_row.game_state_json)` line so the loaded state is normalized. Replace:

```python
                        ("state", snapshot_row.game_state_json),
```

with:

```python
                        ("state", normalize_loaded_state(clone_json(snapshot_row.game_state_json))),
```

(Note: the surrounding dict comprehension already `clone_json`s each value; wrapping the state in `normalize_loaded_state(clone_json(...))` then re-cloning is redundant but harmless. To avoid the double clone, if the comprehension applies `clone_json(value)`, the inner `clone_json` here can be dropped — but keep it if the comprehension only clones for other keys. Verify the exact comprehension form before editing: the current code is `key: clone_json(value) for key, value in (...)`, so drop the inner `clone_json` and write `("state", normalize_loaded_state(snapshot_row.game_state_json))` — `normalize_loaded_state` copies via `dict(...)` + fragment deepcopy for the memory portion, and non-memory keys are then `clone_json`'d by the comprehension.)

Final form of that tuple entry:

```python
                        ("state", normalize_loaded_state(snapshot_row.game_state_json)),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store_load_normalizes_memory.py -v`
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add Persistence/Store.py tests/test_store_load_normalizes_memory.py
git commit -m "refactor(persistence): normalize loaded state memory via MemoryStore on load"
```

---

### Task 5: Drop stale L2 tier from _resolve_story_layer

**Files:**
- Modify: `Persistence/store_snapshot.py:101-108`
- Test: `tests/test_store_snapshot_story_layer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_snapshot_story_layer.py`:

```python
from Persistence.store_snapshot import _resolve_story_layer


def test_player_layer_preserved():
    assert _resolve_story_layer({"story_layer": "player"}) == "player"


def test_l1_layer_preserved():
    assert _resolve_story_layer({"story_layer": "L1"}) == "L1"


def test_actor_is_default():
    assert _resolve_story_layer({"story_layer": ""}) == "actor"
    assert _resolve_story_layer({}) == "actor"


def test_stale_l2_story_layer_collapses_to_actor():
    # old saves may still carry story_layer="L2"; two-tier model has no L2
    assert _resolve_story_layer({"story_layer": "L2"}) == "actor"


def test_stale_l2_agent_type_collapses_to_actor():
    assert _resolve_story_layer({"agent_type": "L2"}) == "actor"


def test_l1_agent_type_resolves_to_l1():
    assert _resolve_story_layer({"agent_type": "L1"}) == "L1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store_snapshot_story_layer.py::test_stale_l2_story_layer_collapses_to_actor -v`
Expected: FAIL — current code returns `"L2"` because `"L2"` is in the accepted set.

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_story_layer` (101-108) with:

```python
def _resolve_story_layer(profile: dict[str, Any]) -> str:
    story_layer = clean_text(profile.get("story_layer", ""))
    if story_layer in {"player", "actor", "L1"}:
        return story_layer
    agent_type = clean_text(profile.get("agent_type", "actor"), "actor")
    if agent_type == "L1":
        return agent_type
    return "actor"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store_snapshot_story_layer.py -v`
Expected: all PASS

Then fix the one caller that branches on the old two-value set. In `build_story_character_records` there is a filter (currently `store_snapshot.py:157`):

```python
        if _resolve_story_layer(profile) not in {"L1", "L2"}:
```

Since L2 is no longer produced, change it to:

```python
        if _resolve_story_layer(profile) != "L1":
```

`build_actor_interaction_records` (`store_snapshot.py:197`) already filters `!= "actor"` and needs no change. Verify no other `L2` literals remain:

```bash
grep -n '"L2"\|'"'"'L2'"'"'' Persistence/store_snapshot.py
```

Expected: no matches after the edits.

Add a test covering the story-character filter before editing it. Append to `tests/test_store_snapshot_story_layer.py`:

```python
def test_l1_profile_classified_as_story_character():
    # profiles resolving to L1 are story characters; actor/player are not
    assert _resolve_story_layer({"story_layer": "L1"}) == "L1"
    assert _resolve_story_layer({"story_layer": "actor"}) != "L1"
    assert _resolve_story_layer({"story_layer": "player"}) != "L1"
```

- [ ] **Step 5: Commit**

```bash
git add Persistence/store_snapshot.py tests/test_store_snapshot_story_layer.py
git commit -m "refactor(persistence): drop stale L2 tier from story-layer resolution"
```

---

### Task 6: Integration round-trip test (serialize → deserialize preserves game-facing state)

**Files:**
- Test: `tests/test_memory_persistence_roundtrip.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_persistence_roundtrip.py`:

```python
from Memory.store import MemoryStore
from Persistence.store_snapshot import build_world_state_payload
from Persistence.Store import normalize_loaded_state


def _snapshot_with_old_save():
    return {
        "state": {
            "plot": {"scene_id": "s1"},
            "scene": {"on_stage": ["lin"]},
            "runtime": {"turn_index": 5},
            "scene_plan": {},
            "director_brief": {},
            "history": [{"turn": 5, "actor": "lin"}],
            "player": {"controlled_character": "player"},
            "memory": {"last_compressed_turn": 4},
            "characters": {
                "lin": {
                    "id": "lin",
                    "emotion": "wary",
                    "intent": "test",
                    "memory": {
                        "player_memory": {
                            "overall_impression": "ally",
                            "relation_state": {"player": 2.0},
                            "key_events": [{"impression": "saved me"}],
                        },
                        "short_term_memory": [{"summary": "STALE"}],
                        "long_term_memory": [{"belief_formed": "STALE"}],
                        "consolidated_memory": [{"x": 1}],
                        "pinned_long_term_memory": [{"y": 2}],
                    },
                }
            },
        }
    }


def test_world_state_payload_then_load_preserves_player_impression_and_drops_queues():
    snapshot = _snapshot_with_old_save()

    # save side: world_state payload
    world_state = build_world_state_payload(snapshot)
    lin_saved = world_state["characters"]["lin"]
    assert lin_saved["emotion"] == "wary"
    assert lin_saved["intent"] == "test"
    assert lin_saved["memory"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 2.0},
            "key_events": [{"impression": "saved me"}],
        }
    }

    # load side: normalize the raw game_state_json (which still has stale queues)
    loaded = normalize_loaded_state(snapshot["state"])
    lin_loaded = loaded["characters"]["lin"]
    assert lin_loaded["emotion"] == "wary"
    assert lin_loaded["memory"] == {
        "player_memory": {
            "overall_impression": "ally",
            "relation_state": {"player": 2.0},
            "key_events": [{"impression": "saved me"}],
        }
    }
    # non-memory state fully preserved
    assert loaded["plot"] == {"scene_id": "s1"}
    assert loaded["history"] == [{"turn": 5, "actor": "lin"}]
    # global memory backfilled to canonical shape
    assert "scene_memory" in loaded["memory"]
    assert loaded["memory"]["last_compressed_turn"] == 4


def test_original_state_not_mutated_by_save_or_load():
    snapshot = _snapshot_with_old_save()
    build_world_state_payload(snapshot)
    normalize_loaded_state(snapshot["state"])
    # source still carries the stale queues (pure functions did not mutate)
    assert snapshot["state"]["characters"]["lin"]["memory"]["short_term_memory"] == [{"summary": "STALE"}]
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_memory_persistence_roundtrip.py -v`
Expected: PASS if Tasks 1-4 are complete (this is a composition test — it should pass once the units are wired). If it fails, the failure pinpoints a wiring gap between save and load paths.

- [ ] **Step 3: Run the full persistence + memory suite**

Run:

```bash
pytest tests/test_memory_store_serialization.py tests/test_store_load_normalizes_memory.py tests/test_store_snapshot_story_layer.py tests/test_memory_persistence_roundtrip.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_persistence_roundtrip.py
git commit -m "test(persistence): round-trip preserves player impression, drops stale queues, no mutation"
```

---

## Self-Review

- **Spec coverage (Step 4 of spec §五):** "`MemoryStore.serialize_memory`/`deserialize_memory` 定义记忆片段形状，`Persistence` 存档层改调 MemoryStore 存取记忆片段，不再直接理解记忆内部结构" — covered by Tasks 1-4. The stale-L2 cleanup (spec §六 point 4) — covered by Task 5.
- **Not in scope (per user):** RAG vector write stays in AsyncMemoryCompactor — this plan touches only MySQL 存档 serialization. Confirmed no vector/pgvector code here.
- **Type consistency:** `serialize_memory` returns `{"memory", "character_memory"}`; `deserialize_memory` consumes the same two keys; `build_world_state_payload` and `normalize_loaded_state` both consume `fragment["memory"]` + `fragment["character_memory"]` and both call `_merge_character_memory(characters, character_memory)`. `_KEPT_CHARACTER_MEMORY_KEYS = ("player_memory",)` is the single source of which per-character keys survive.
- **Placeholder scan:** no TBD/TODO; all steps carry concrete code and commands.
- **Dependency ordering:** `_merge_character_memory` is defined in `store_snapshot.py` (Task 3) and imported by `Store.py` (Task 4). Task 3 precedes Task 4 — order is correct.
- **Pure-functional guarantee:** every `MemoryStore` method deepcopies on extract and never mutates its argument; `normalize_loaded_state` builds a new dict. Verified by `test_serialize_is_pure_no_mutation` and `test_original_state_not_mutated_by_save_or_load`.
