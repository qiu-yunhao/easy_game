# 对话延迟优化实现计划（A: fallback 降级 + B: Director 编组并行）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 减少一轮对话的等待时间——让互不回应的角色并行行动（B，主要收益），并让 LLM fallback 降级到 json_object 而非放弃格式约束（A，提可靠性、减少 repair 二次调用）。

**Architecture:** 组内并行已由 `Graph/beat_group.py` 的 ThreadPoolExecutor 实现，触发靠 Director 产出的 `response_groups`。但 Director 的 prompt/schema 从未说明该字段，导致 LLM 填不对、归一化退化成全串行（每人一组）。B 只改 Director 的 prompt 段落 + schema description 教它编组；A 改 `BaseAgent._run_fallback` 把删除 response_format 改成降级 `{"type":"json_object"}`。均不碰叙事逻辑、不碰前端、不碰流式。

**Tech Stack:** Python, pytest, OpenAI 兼容客户端（DeepSeek，仅支持 json_object，不支持 json_schema）。

---

## 背景数据（实测，2026-08-26 live 一轮）

- 整轮 91.8s，20 次 LLM 调用，全部串行、全部 `+fallback`。
- 3 个 L1 角色串行：46.281→49.283→49.658，各 ~3s，合计 ~9s；编组后可并行到 ~3s。
- fallback 单趟（非双倍）：`_run_fallback` 现 `pop("response_format")`，退回纯文字求 JSON，未用 DeepSeek 支持的 json_object。

## 文件结构

- 修改 `BaseAgent.py:144-154`（`_run_fallback`）——A。
- 修改 `Director/DirectorAgent.py:17-55`（`DIRECTOR_SYSTEM_PROMPT`）——B。
- 修改 `Director/DirectorSchema.py:21-27`（`response_groups` 加 description）——B。
- 测试 `tests/test_base_agent_response_format_cache.py`（扩展 A 断言）。
- 测试 `tests/test_director_response_groups.py`（新建，B 归一化行为回归护栏）。

---

### Task 1: A —— fallback 降级到 json_object

**Files:**
- Modify: `BaseAgent.py:144-154`
- Test: `tests/test_base_agent_response_format_cache.py`

- [ ] **Step 1: 写失败测试**——断言 fallback 请求带 `response_format={"type":"json_object"}`

把 `tests/test_base_agent_response_format_cache.py` 的 `_RecordingClient` 改为记录完整 format：
```python
class _RecordingClient:
    def __init__(self) -> None:
        self.requests: list[bool] = []
        self.formats: list = []
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **params):
        rf = params.get("response_format")
        self.formats.append(rf)
        self.requests.append(rf is not None)
        if rf and rf.get("type") == "json_schema":
            raise RuntimeError("response_format json_schema is unavailable on this endpoint")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"ok": True})))]
        )
```
新增测试：
```python
def test_fallback_uses_json_object_not_bare():
    client = _RecordingClient()
    agent = _make_agent(client)
    agent.command("hi", response_format=SCHEMA)
    assert client.formats == [
        {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}},
        {"type": "json_object"},
    ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_base_agent_response_format_cache.py::test_fallback_uses_json_object_not_bare -v`
Expected: FAIL——fallback 那趟当前 `response_format` 为 None（被 pop），不等于 `{"type":"json_object"}`。

- [ ] **Step 3: 改 `_run_fallback` 降级为 json_object**

`BaseAgent.py:144-154`，把 `fallback_params.pop("response_format", None)` 替换为降级：
```python
        def _run_fallback() -> Any:
            perf_flags["fallback"] = True
            fallback_params = dict(params)
            # endpoint 不支持 json_schema，但支持 json_object：降级而非放弃格式约束，减少 malformed→repair。
            fallback_params["response_format"] = {"type": "json_object"}
            fallback_messages = list(messages)
            fallback_messages[-1] = {
                "role": "user",
                "content": self._build_json_fallback_instruction(instruction, response_format),
            }
            fallback_params["messages"] = fallback_messages
            return client.chat.completions.create(**fallback_params)
```

- [ ] **Step 4: 跑测试确认通过 + base agent 全量无回归**

Run: `python -m pytest tests/test_base_agent_response_format_cache.py tests/test_base_agent_streaming.py -v`
Expected: PASS。注意既有的 cache 测试断言 `client.requests`（布尔序列）——fallback 那趟由 None 变 json_object，`rf is not None` 仍为 True，既有布尔断言不受影响。若某既有测试直接断言 fallback 那趟无 response_format，则同步更新并在提交信息说明语义变更。

- [ ] **Step 5: 提交**

```bash
git add BaseAgent.py tests/test_base_agent_response_format_cache.py
git commit -m "fix(agent): fallback degrades to json_object instead of dropping response_format"
```

---

### Task 2: B —— schema 给 response_groups 加 description

**Files:**
- Modify: `Director/DirectorSchema.py:21-27`

- [ ] **Step 1: 加 description**

把 `Director/DirectorSchema.py:21-27` 的 `response_groups` 定义改为带说明：
```python
                "response_groups": {
                    "type": "array",
                    "description": (
                        "Partition of who_should_respond into ordered sub-lists. "
                        "Characters in the SAME sub-list react independently to the player's "
                        "latest action and act simultaneously (parallel). Put characters into "
                        "DIFFERENT sub-lists when one must speak before another reacts (a causal "
                        "chain, serial). Prefer merging characters who do not answer each other "
                        "into one sub-list to reduce turn latency. Must cover every id in "
                        "who_should_respond exactly once."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
```

- [ ] **Step 2: 语法自检**

Run: `python -c "import Director.DirectorSchema as s; print(s.DIRECTOR_RESPONSE_SCHEMA['json_schema']['schema']['properties']['response_groups']['description'][:20])"`
Expected: 打印 `Partition of who_sho`（无 import 错误）。

- [ ] **Step 3: 提交**

```bash
git add Director/DirectorSchema.py
git commit -m "feat(director): document response_groups so the LLM can group parallel responders"
```

---

### Task 3: B —— prompt 教 Director 编组

**Files:**
- Modify: `Director/DirectorAgent.py:17-55`（`DIRECTOR_SYSTEM_PROMPT`）

- [ ] **Step 1: 在 who_should_respond 约束之后插入 response_groups 说明**

在 `DIRECTOR_SYSTEM_PROMPT` 中 `who_should_respond` 那条约束（`DirectorAgent.py:34-38`）之后插入：
```
- `response_groups` partitions `who_should_respond` into ordered sub-lists that control turn parallelism.
  Characters in the SAME sub-list react independently to the player's latest action and act at the same
  time; characters in DIFFERENT sub-lists act one sub-list after another, so a later sub-list can see what
  earlier ones said. Default to merging characters who are NOT answering each other into a single sub-list
  (they each react to the player, not to one another) so the turn resolves faster. Only split into separate
  sub-lists when one character must speak before another can react to them (a genuine causal chain), or when
  a focus character interrupts. Every id in `who_should_respond` must appear exactly once across the groups.
```

- [ ] **Step 2: 语法自检**

Run: `python -c "import Director.DirectorAgent as a; assert 'response_groups' in a.DIRECTOR_SYSTEM_PROMPT; print('ok')"`
Expected: 打印 `ok`。

- [ ] **Step 3: 提交**

```bash
git add Director/DirectorAgent.py
git commit -m "feat(director): prompt guidance to group independent responders for parallel turns"
```

---

### Task 4: B —— 归一化行为回归测试（护栏）

**Files:**
- Create: `tests/test_director_response_groups.py`

说明：`_normalize_response_groups`（`Director/DirectorRuntime.py:309`）已存在且本计划不改；本测试是护栏，锁定"合法分组保留、非法退化全串行"的契约，防止后续改动破坏并行触发。

- [ ] **Step 1: 写测试**

```python
from Director.DirectorRuntime import _normalize_response_groups


def test_valid_parallel_group_is_preserved():
    who = ["a", "b", "c"]
    assert _normalize_response_groups([["a"], ["b", "c"]], who) == [["a"], ["b", "c"]]


def test_missing_coverage_degrades_to_serial():
    who = ["a", "b", "c"]
    assert _normalize_response_groups([["a", "b"]], who) == [["a"], ["b"], ["c"]]


def test_non_list_degrades_to_serial():
    who = ["a", "b"]
    assert _normalize_response_groups("nonsense", who) == [["a"], ["b"]]
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_director_response_groups.py -v`
Expected: PASS（逻辑未改，测试即通过，作为护栏）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_director_response_groups.py
git commit -m "test(director): lock response_groups normalization contract"
```

---

### Task 5: 端到端验证（人工 + 相关测试）

**Files:** 无（仅运行验证）

- [ ] **Step 1: 跑相关既有测试无回归**

Run: `python -m pytest tests/ -k "director or base_agent or beat or narrat" -q`
Expected: PASS（无回归）。

- [ ] **Step 2: live 一轮抓 llm.perf，确认角色并行**

在项目根建临时脚本 `_perf_probe_tmp.py`（跑完删除），开 llm.perf 时间戳日志，跑 `demo_run.py --mode live --rounds 1`：
```python
import logging, sys
h = logging.StreamHandler(sys.stderr)
h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d perf %(message)s", datefmt="%H:%M:%S"))
lg = logging.getLogger("llm.perf"); lg.setLevel(logging.INFO); lg.addHandler(h); lg.propagate = False
import demo_run; sys.argv = ["demo_run.py", "--mode", "live", "--rounds", "1"]; demo_run.main()
```
Run: `python _perf_probe_tmp.py 2>&1 | grep -E "perf LLM"`
Expected: 多个 `L1ActorAgent` / `ActorAgent` 行的时间戳**重叠**（几乎同一秒开始），而非首尾相接；对比基线 3 个 L1 从 ~9s 串行降到 ~3s。若 Director 仍每人一组（无重叠），说明 LLM 未采纳编组，回到 Task 3 强化 prompt 后重跑。

- [ ] **Step 3: 清理临时脚本**

Run: `rm -f _perf_probe_tmp.py`

---

## 自检

- **Spec 覆盖**：A（fallback 降级）= Task 1；B（编组并行）= Task 2+3（schema+prompt）、Task 4（护栏）；验证 = Task 5。流式打字机（原 #5-#7）按决策搁置，不在本计划。
- **占位符**：无 TBD/TODO；每个改动步骤含完整代码。
- **类型/命名一致**：`_run_fallback` / `_normalize_response_groups` / `response_groups` / `who_should_respond` 全程一致，与实际代码符号一致。
- **风险点**：Task 1 Step 4 已标注既有测试布尔断言不受影响、若有直断则同步更新；Task 5 Step 2 已标注 LLM 可能不采纳编组的兜底处理。
