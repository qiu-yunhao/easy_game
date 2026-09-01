<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **easy_game** (3337 symbols, 7156 relationships, 291 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/easy_game/context` | Codebase overview, check index freshness |
| `gitnexus://repo/easy_game/clusters` | All functional areas |
| `gitnexus://repo/easy_game/processes` | All execution flows |
| `gitnexus://repo/easy_game/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Easy Game — Project Memory

## Evidence and working state

- Treat implementation and tests as the source of truth. README files and historical design documents provide background only.
- Before editing, inspect `git status --short` and the focused diff. This worktree may contain unfinished, uncommitted features.
- Never expose or copy values from `.env`, credentials, or database URLs.
- Use Chinese for git commit messages, keeping a concise `type: subject` format.

## Architectural map

- `GameState.py` defines the shared runtime-state contract. A state-field change must be audited through: initializer, graph producers and consumers, persistence snapshot, web serialization, and focused tests.
- `session_bootstrap.py` owns runtime composition. Graph code must receive collaborators through `GraphDependencies`; do not construct concrete agents ad hoc inside graph nodes.
- Primary runtime flow: story authoring -> chapter preparation -> director/scheduler -> beat resolution -> scene/chapter transitions. `Graph/builder.py` is the composition map.
- Keep business rules in their domain packages. `Graph/` orchestrates those rules rather than becoming their home.

## Semantic invariants

- Default `actor.after` hook order is history commit, then contextual scene progression. Default `narration.after` runs asynchronous memory refresh.
- Memory reads are provided by `Memory/default_provider.py`; writes and persistence shaping belong in `Memory/store.py`.
- Persisted character memory intentionally retains only `player_memory`. Any new character-memory field requires an explicit save/load policy and round-trip coverage.
- Long-term recall is optional. Without a recall database URL, the recall stack must not initialize embedding, vector, or sparse-retrieval infrastructure.
- World configuration must move through `WorldSetting` schema, validation, and applier. Do not embed genre or progression policy directly in `Graph/`.
- `web_session.py` owns session behavior; `web_server.py` owns HTTP and SSE transport; frontend code consumes the API rather than reaching into runtime internals.

## Change routing

- Story state machine or turn sequencing: `Graph/`, `GameState.py`, and `session_bootstrap.py`.
- Agent prompting, output schema, or formatting: the owning Agent package; preserve formatter/runtime separation.
- Memory, compaction, recall, or save/load: `Memory/`, `History/`, `Recall/`, and `Persistence/`. Verify both behavior and persistence boundaries.
- World authoring and presets: `WorldSetting/`; validate at the boundary and apply through its applier.
- Browser-facing behavior: `web_session.py` first, then `web_server.py`, then `frontend/` if the API contract changes.

## Verification

- Add or update the nearest `tests/test_<area>.py` for behavior changes; prefer focused tests before broader regression runs.
- Run `python -m pytest -q` for cross-cutting changes when the local environment supports the full suite.
- Use GitNexus impact analysis and change detection when its MCP tools are available. If unavailable, explicitly trace direct callers and run the affected tests; never fabricate GitNexus results.

## Keeping this file useful

- Add only facts that are stable, costly to rediscover, and capable of changing an engineering decision.
- Do not add transient implementation notes, feature status, full API inventories, README-style product narrative, or secrets.
- When a rule changes, update or delete its memory entry in the same change set.
