# Web UI 重排 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Stagebound 前端重排为「入口→登录→选择→工作区」四页 SPA，并补齐模板导入/列表/详情/选择的后端链路与情节注入。

**Architecture:** 后端先补 `TemplateRepository.list_templates` + `StoryTemplateService.list_templates`，再把 `StoryTemplateService` 接进 `WebGameSession`（延迟构造），新增会话方法与 3 个 HTTP 端点，并在 `reset` 时用 `suggest_plot_beats` 注入情节。前端把 62KB 单文件 `app.js` 拆成原生 ES Module 多模块（无构建），逐块迁移现有对话/存档逻辑，新增模板工作区与两个弹窗。

**Tech Stack:** Python 3（stdlib http.server、SQLAlchemy、unittest）、原生 ES Module 前端（无打包器）、真实 MySQL/PG（测试依赖 `.env` 的 `MYSQL_URL`/`PG_URL`）。

**测试前置:** 后端模板相关测试需要 `.env` 提供 `MYSQL_URL` 与 `PG_URL`（见 `tests/test_template_repository.py`、`tests/test_template_service.py`）。运行前确认数据库可达。

---

## 阶段一：后端模板列表能力

### Task 1: TemplateRepository.list_templates

**Files:**
- Modify: `StoryTemplate/TemplateRepository.py`（新增方法，末尾 `get_skeleton` 之后）
- Test: `tests/test_template_repository.py`（新增用例）

- [ ] **Step 1: 写失败测试**

在 `tests/test_template_repository.py` 的 `RepositoryRealMysqlTests` 类内新增（`_sample()` 已存在，返回 `(user_id, source_title, sb, chars, beats, skeleton)` 结构见文件；此处复用其保存后验证 list）：

```python
    def test_list_templates_returns_saved_with_beat_count(self):
        user_id, source_title, sb, chars, beats, skeleton = self._sample()
        tid = self.repo.save_template(
            user_id=user_id, source_title=source_title,
            style_bible=sb, characters=chars, beats=beats, skeleton=skeleton,
        )
        rows = self.repo.list_templates()
        match = [r for r in rows if r["template_id"] == tid]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["source_title"], source_title)
        self.assertEqual(match[0]["beat_count"], len(beats))
        self.assertIn("created_at", match[0])
```

> 注：确认 `_sample()` 的返回签名，若它只返回部分字段，按文件实际签名调整解包。已知 `save_template` 需要 `user_id/source_title/style_bible/characters/beats/skeleton`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_template_repository.py::RepositoryRealMysqlTests::test_list_templates_returns_saved_with_beat_count -v`
Expected: FAIL，`AttributeError: 'TemplateRepository' object has no attribute 'list_templates'`

- [ ] **Step 3: 实现 list_templates**

在 `StoryTemplate/TemplateRepository.py`，`get_skeleton` 方法之后新增。顶部已 `from sqlalchemy import (... func ...)`? 当前没有 `func`，需在现有 sqlalchemy import 里补 `func`：

把第 6-9 行的 import 增加 `func`：

```python
from sqlalchemy import (
    BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text,
    func, insert, select,
)
```

新增方法：

```python
    def list_templates(self) -> list[dict]:
        beat_count = (
            select(
                template_plot_beat.c.template_id.label("tid"),
                func.count().label("beat_count"),
            )
            .group_by(template_plot_beat.c.template_id)
            .subquery()
        )
        with self._database.session() as db:
            rows = db.execute(
                select(
                    story_template.c.template_id,
                    story_template.c.source_title,
                    story_template.c.created_at,
                    func.coalesce(beat_count.c.beat_count, 0).label("beat_count"),
                )
                .select_from(
                    story_template.join(
                        beat_count,
                        story_template.c.template_id == beat_count.c.tid,
                        isouter=True,
                    )
                )
                .order_by(story_template.c.template_id.desc())
            ).mappings().all()
        return [
            {
                "template_id": int(r["template_id"]),
                "source_title": r["source_title"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "beat_count": int(r["beat_count"]),
            }
            for r in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_template_repository.py::RepositoryRealMysqlTests::test_list_templates_returns_saved_with_beat_count -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/TemplateRepository.py tests/test_template_repository.py
git commit -m "feat(template): add TemplateRepository.list_templates with beat counts"
```

### Task 2: StoryTemplateService.list_templates + get_template_detail

**Files:**
- Modify: `StoryTemplate/StoryTemplateService.py`
- Test: `tests/test_template_service.py`（新增用例，复用 `_ScriptedClient`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_template_service.py` 的 `ServiceEndToEndTests` 内新增：

```python
    def test_list_templates_and_detail(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        tid = service.import_novel(
            source_title="列表用例", text="第一回 甲\n甲混入皇宫。",
        )
        rows = service.list_templates()
        self.assertTrue(any(r["template_id"] == tid for r in rows))

        detail = service.get_template_detail(tid)
        self.assertIn("style_bible", detail)
        self.assertIn("beats", detail)
        self.assertIn("skeleton", detail)
        self.assertIn("古雅", detail["style_bible"]["tone_tags"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_template_service.py::ServiceEndToEndTests::test_list_templates_and_detail -v`
Expected: FAIL，`AttributeError: ... has no attribute 'list_templates'`

- [ ] **Step 3: 实现两个透传方法**

在 `StoryTemplate/StoryTemplateService.py`，`get_style_bible` 之后新增：

```python
    def list_templates(self) -> list[dict]:
        return self._repo.list_templates()

    def get_template_detail(self, template_id: int) -> dict:
        return {
            "template_id": template_id,
            "style_bible": self._repo.get_style_bible(template_id),
            "characters": self._repo.get_characters(template_id),
            "beats": self._repo.get_beats(template_id),
            "skeleton": self._repo.get_skeleton(template_id),
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_template_service.py::ServiceEndToEndTests::test_list_templates_and_detail -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/StoryTemplateService.py tests/test_template_service.py
git commit -m "feat(template): add service list_templates + get_template_detail passthroughs"
```

---

## 阶段二：把 StoryTemplateService 接进会话

### Task 3: WebGameSession 持有模板服务 + selected_template_id 状态

**Files:**
- Modify: `web_session.py`（`SessionConfig` 增字段、`__init__`、新增会话方法）
- Test: `tests/test_web_session_templates.py`（新建）

- [ ] **Step 1: 写失败测试（选择/清除模板状态）**

新建 `tests/test_web_session_templates.py`。用 fake 模板服务注入，避免真实 LLM/DB：

```python
import unittest

from web_session import SessionConfig, WebGameSession


class _FakeTemplateService:
    def __init__(self):
        self.imported = []
    def list_templates(self):
        return [{"template_id": 1, "source_title": "鹿鼎记", "beat_count": 3, "created_at": ""}]
    def get_template_detail(self, template_id):
        return {"template_id": template_id, "style_bible": {"tone_tags": ["古雅"]},
                "characters": [], "beats": [{"beat_id": "b1", "label": "闯宫",
                "tags": [], "summary": "s", "dramatic_function": "", "reusable_conflict": ""}],
                "skeleton": []}
    def import_novel(self, *, source_title, text, user_id=0):
        self.imported.append((source_title, user_id))
        return 42
    def suggest_plot_beats(self, template_id, *, query, top_k=5):
        return [{"beat_id": "b1", "label": "闯宫", "tags": [], "summary": "s",
                 "dramatic_function": "", "reusable_conflict": ""}]


def _session_with_fake():
    session = WebGameSession(SessionConfig(mode="heuristic"))
    session.bind_story_template_service(_FakeTemplateService())
    session.reset(player_profile={"name": "测试玩家"})
    return session


class SelectedTemplateStateTest(unittest.TestCase):
    def test_set_and_clear_selected_template(self):
        session = _session_with_fake()
        self.assertIsNone(session.selected_template_id)
        session.set_selected_template(1)
        self.assertEqual(session.selected_template_id, 1)
        session.set_selected_template(None)
        self.assertIsNone(session.selected_template_id)

    def test_list_and_detail_and_import_delegate(self):
        session = _session_with_fake()
        self.assertEqual(session.list_templates()[0]["template_id"], 1)
        self.assertEqual(session.get_template_detail(1)["template_id"], 1)
        self.assertEqual(session.import_template(source_title="t", text="x", user_id=0), 42)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web_session_templates.py -v`
Expected: FAIL，`AttributeError: 'WebGameSession' object has no attribute 'bind_story_template_service'`

- [ ] **Step 3: 实现字段、绑定与会话方法**

在 `web_session.py` 的 `SessionConfig`（第 184 行附近）增字段：

```python
@dataclass(slots=True)
class SessionConfig:
    mode: str = "agent-first"
    player_character: str = PLAYER_CHARACTER_ID
    player_profile: dict[str, Any] | None = None
    narration_style_preset: str = DEFAULT_NARRATION_STYLE_PRESET
    selected_template_id: int | None = None
```

在 `WebGameSession.__init__`（第 192 行附近）内、`self._lock` 定义之后，增加持有引用与状态（放在其它实例属性附近）：

```python
        self._story_template_service = None
        self.selected_template_id: int | None = self.config.selected_template_id
```

在类中新增方法（放在 `list_players_for_user` 附近，保持公开方法聚集）：

```python
    def bind_story_template_service(self, service) -> None:
        with self._lock:
            self._story_template_service = service

    def _require_template_service_unlocked(self):
        if self._story_template_service is None:
            raise RuntimeError("情节模板服务未配置，请检查数据库与向量库连接。")
        return self._story_template_service

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._require_template_service_unlocked().list_templates()

    def get_template_detail(self, template_id: int) -> dict[str, Any]:
        with self._lock:
            return self._require_template_service_unlocked().get_template_detail(template_id)

    def import_template(self, *, source_title: str, text: str, user_id: int = 0) -> int:
        with self._lock:
            return self._require_template_service_unlocked().import_novel(
                source_title=source_title, text=text, user_id=user_id,
            )

    def set_selected_template(self, template_id: int | None) -> dict[str, Any]:
        with self._lock:
            self.selected_template_id = int(template_id) if template_id is not None else None
            self.config.selected_template_id = self.selected_template_id
            return self.serialize_state()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web_session_templates.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web_session.py tests/test_web_session_templates.py
git commit -m "feat(session): hold StoryTemplateService + selected_template state and delegates"
```

### Task 4: reset 透传 selected_template_id + serialize_state 暴露 + 快照持久化

**Files:**
- Modify: `web_session.py`（`reset`、`serialize_state`、`_export_runtime_snapshot_unlocked`、`_load_runtime_snapshot_unlocked`）
- Test: `tests/test_web_session_templates.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_session_templates.py` 追加：

```python
class ResetAndSnapshotTemplateTest(unittest.TestCase):
    def test_reset_accepts_selected_template_id(self):
        session = _session_with_fake()
        session.reset(player_profile={"name": "玩家"}, selected_template_id=1)
        self.assertEqual(session.selected_template_id, 1)
        state = session.get_state()
        self.assertEqual(state["selected_template_id"], 1)

    def test_snapshot_roundtrips_selected_template(self):
        session = _session_with_fake()
        session.set_selected_template(1)
        snap = session.export_runtime_snapshot()
        self.assertEqual(snap["selected_template_id"], 1)
        session.set_selected_template(None)
        session.load_runtime_snapshot(snap)
        self.assertEqual(session.selected_template_id, 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web_session_templates.py::ResetAndSnapshotTemplateTest -v`
Expected: FAIL，`reset() got an unexpected keyword argument 'selected_template_id'`

- [ ] **Step 3: 实现**

修改 `reset`（第 211 行）签名与体：增加参数并在设置 config 时纳入：

```python
    def reset(
        self,
        *,
        mode: str | None = None,
        player_character: str | None = None,
        player_profile: dict[str, Any] | None = None,
        narration_style_preset: str | None = None,
        selected_template_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            for field, value in (
                ("mode", mode),
                ("player_character", player_character),
                ("player_profile", player_profile),
            ):
                if value is not None:
                    setattr(self.config, field, value)
            if narration_style_preset is not None:
                self.config.narration_style_preset = resolve_narration_style_preset(narration_style_preset)
            if selected_template_id is not None:
                self.selected_template_id = int(selected_template_id)
                self.config.selected_template_id = self.selected_template_id
            self.last_handoff_reason = "设定已更新，正在重建开场场景。"
            self._rebuild_session(initialize_story=True)
            return self.serialize_state()
```

在 `serialize_state`（第 743 行附近）返回的 dict 里追加一个键（找到该方法 `return { ... }` 的构造处，在合适位置加）：

```python
            "selected_template_id": self.selected_template_id,
```

> 若 `serialize_state` 是逐步构造 `state` dict 后 return，则在 return 前加 `state["selected_template_id"] = self.selected_template_id`。以文件实际写法为准。

在 `_export_runtime_snapshot_unlocked`（第 368 行附近）返回 dict 追加：

```python
            "selected_template_id": self.selected_template_id,
```

在 `_load_runtime_snapshot_unlocked`（第 398 行附近）体内追加读取：

```python
        self.selected_template_id = snapshot.get("selected_template_id")
        self.config.selected_template_id = self.selected_template_id
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web_session_templates.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add web_session.py tests/test_web_session_templates.py
git commit -m "feat(session): thread selected_template_id through reset/state/snapshot"
```

### Task 5: 开局时用 suggest_plot_beats 注入情节

**Files:**
- Modify: `web_session.py`（`_initialize_story` 或 `_rebuild_session` 内，故事初始化后注入）
- Test: `tests/test_web_session_templates.py`（追加）

- [ ] **Step 1: 写失败测试**

`_FakeTemplateService.suggest_plot_beats` 已在 Task 3 定义。追加断言：注入后 `state["plot"]` 里出现模板情节线索键。约定注入到 `state["plot"]["template_plot_beats"]`（新键，仅存 label/summary 列表）：

```python
class TemplateInjectionTest(unittest.TestCase):
    def test_selected_template_injects_plot_beats_on_reset(self):
        session = _session_with_fake()
        session.reset(player_profile={"name": "玩家"}, selected_template_id=1)
        beats = session.state["plot"].get("template_plot_beats")
        self.assertTrue(beats)
        self.assertEqual(beats[0]["label"], "闯宫")

    def test_no_template_leaves_plot_beats_empty(self):
        session = _session_with_fake()
        session.reset(player_profile={"name": "玩家"})
        self.assertIn(session.state["plot"].get("template_plot_beats", []), ([], None))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web_session_templates.py::TemplateInjectionTest -v`
Expected: FAIL（`template_plot_beats` 为 None）

- [ ] **Step 3: 实现注入**

在 `web_session.py` 新增一个私有注入方法，并在 `_rebuild_session` 完成故事初始化后调用。先看 `_rebuild_session`（第 652 行）末尾，在 `initialize_story` 分支之后调用注入。新增方法：

```python
    def _inject_template_plot_beats_unlocked(self) -> None:
        if self.selected_template_id is None or self._story_template_service is None:
            self.state["plot"]["template_plot_beats"] = []
            return
        chapter_hint = str(self.state["plot"].get("current_chapter_title", "") or "")
        try:
            beats = self._story_template_service.suggest_plot_beats(
                self.selected_template_id, query=chapter_hint, top_k=5,
            )
        except Exception:
            self.state["plot"]["template_plot_beats"] = []
            return
        self.state["plot"]["template_plot_beats"] = [
            {"label": b.get("label", ""), "summary": b.get("summary", "")}
            for b in beats
        ]
```

在 `_rebuild_session` 里，`initialize_story=True` 且故事初始化完成后调用 `self._inject_template_plot_beats_unlocked()`。找到 `_rebuild_session` 内调用 `self._initialize_story()` 的位置，在其后追加：

```python
        if initialize_story:
            self._initialize_story()
            self._inject_template_plot_beats_unlocked()
```

> 以 `_rebuild_session` 实际结构为准：若它已有 `if initialize_story: self._initialize_story()`，只需在该分支内追加注入调用。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web_session_templates.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add web_session.py tests/test_web_session_templates.py
git commit -m "feat(session): inject template plot beats into plot state on story init"
```

---

## 阶段三：HTTP 端点 + 应用装配

### Task 6: web_demo 装配模板服务并绑定到会话

**Files:**
- Modify: `web_demo.py`（构造 `build_story_template_service` 并 `session.bind_story_template_service(...)`；新增 CLI 参数 `--template-mysql-url` / `--template-pg-url`，缺省复用 `MYSQL_URL`/`PG_URL`）
- Test: `tests/test_web_demo_template_wiring.py`（新建，import-level 冒烟）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_web_demo_template_wiring.py`，只验证装配函数存在且在给定 URL 时调用绑定（用 monkeypatch 拦截 `build_story_template_service`）：

```python
import unittest
from unittest.mock import patch

import web_demo


class TemplateWiringTest(unittest.TestCase):
    def test_maybe_setup_template_binds_when_urls_present(self):
        calls = {}
        class _Sess:
            def bind_story_template_service(self, svc):
                calls["bound"] = svc
        with patch.object(web_demo, "build_story_template_service", return_value="SVC") as b:
            web_demo._maybe_setup_story_template(
                _Sess(), mysql_url="mysql://x", pg_url="pg://y",
            )
        self.assertEqual(calls.get("bound"), "SVC")
        b.assert_called_once()

    def test_maybe_setup_template_noop_without_urls(self):
        class _Sess:
            def bind_story_template_service(self, svc):
                raise AssertionError("should not bind")
        web_demo._maybe_setup_story_template(_Sess(), mysql_url="", pg_url="")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web_demo_template_wiring.py -v`
Expected: FAIL，`AttributeError: module 'web_demo' has no attribute '_maybe_setup_story_template'`

- [ ] **Step 3: 实现装配**

在 `web_demo.py` 顶部 import 区加：

```python
from StoryTemplate.factory import build_story_template_service
```

新增函数（放在 `_setup_recall` 附近）：

```python
def _maybe_setup_story_template(session, *, mysql_url: str, pg_url: str) -> None:
    if not (str(mysql_url).strip() and str(pg_url).strip()):
        return
    service = build_story_template_service(
        mysql_url=str(mysql_url).strip(), pg_url=str(pg_url).strip(),
    )
    session.bind_story_template_service(service)
```

在 `main`（构造 server 之前、`session` 已建好处）读取 URL 并调用。CLI 已有 `--database-url`；模板库默认复用环境变量：

```python
    import os
    template_mysql = os.environ.get("MYSQL_URL", "")
    template_pg = os.environ.get("PG_URL", "")
    _maybe_setup_story_template(session, mysql_url=template_mysql, pg_url=template_pg)
```

> 放在 `save_store`/recall 装配之后、`web_server.StageboundHTTPServer(...)` 构造之前。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web_demo_template_wiring.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web_demo.py tests/test_web_demo_template_wiring.py
git commit -m "feat(web): wire StoryTemplateService into session at bootstrap"
```

### Task 7: 新增 HTTP 端点（GET/POST templates、reset/new-game 透传）

**Files:**
- Modify: `web_server.py`（`do_GET` 增 `/api/templates` 与 `/api/templates/{id}`；`_handle_post_api_request` 增 `/api/templates/import` 与 `/api/templates/select`；`_build_reset_kwargs` 透传 `selected_template_id`）
- Test: `tests/test_web_server_templates.py`（新建，用假 session + 直接调用 handler 逻辑）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_web_server_templates.py`。直接测试 `_handle_post_api_request` 的分派与 `_build_reset_kwargs`（构造一个最小 handler 桩，注入假 server.session）：

```python
import unittest
from http import HTTPStatus
from types import SimpleNamespace

import web_server


class _FakeSession:
    def __init__(self):
        self.selected = None
        self.imported = None
    def list_templates(self):
        return [{"template_id": 1, "source_title": "鹿鼎记", "beat_count": 3, "created_at": ""}]
    def get_template_detail(self, tid):
        return {"template_id": tid, "style_bible": {}, "characters": [], "beats": [], "skeleton": []}
    def import_template(self, *, source_title, text, user_id=0):
        self.imported = (source_title, user_id)
        return 7
    def set_selected_template(self, tid):
        self.selected = tid
        return {"selected_template_id": tid}


def _handler():
    h = web_server.StageboundRequestHandler.__new__(web_server.StageboundRequestHandler)
    h.server = SimpleNamespace(session=_FakeSession(), save_store=None)
    return h


class PostTemplateEndpointsTest(unittest.TestCase):
    def test_import_dispatch(self):
        h = _handler()
        status, payload = h._handle_post_api_request(
            "/api/templates/import",
            {"source_title": "鹿鼎记", "text": "正文", "user_id": 0},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["template_id"], 7)
        self.assertEqual(h.server.session.imported, ("鹿鼎记", 0))

    def test_select_dispatch_and_clear(self):
        h = _handler()
        status, payload = h._handle_post_api_request("/api/templates/select", {"template_id": 1})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(h.server.session.selected, 1)
        status, payload = h._handle_post_api_request("/api/templates/select", {"template_id": None})
        self.assertIsNone(h.server.session.selected)

    def test_reset_kwargs_passes_selected_template(self):
        h = _handler()
        kwargs = h._build_reset_kwargs({"selected_template_id": 5})
        self.assertEqual(kwargs["selected_template_id"], 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web_server_templates.py -v`
Expected: FAIL（`/api/templates/import` 落到 `未知接口`，返回 NOT_FOUND；`_build_reset_kwargs` 无 `selected_template_id` 键）

- [ ] **Step 3: 实现端点**

`web_server.py` 的 `_handle_post_api_request`，在 `return HTTPStatus.NOT_FOUND, {"error": "未知接口。"}` 之前插入：

```python
        if path == "/api/templates/import":
            source_title = str(payload.get("source_title", "") or "")
            text = str(payload.get("text", "") or "")
            if not source_title or not text:
                raise RuntimeError("`source_title` 与 `text` 均为必填。")
            user_id = self._as_int(payload.get("user_id", 0), field_name="user_id")
            template_id = self.server.session.import_template(
                source_title=source_title, text=text, user_id=user_id,
            )
            return HTTPStatus.OK, {"template_id": template_id}
        if path == "/api/templates/select":
            raw = payload.get("template_id")
            template_id = None if raw is None else self._as_int(raw, field_name="template_id")
            return HTTPStatus.OK, self.server.session.set_selected_template(template_id)
```

`_build_reset_kwargs` 的返回 dict 追加：

```python
            "selected_template_id": (
                self._as_int(value, field_name="selected_template_id")
                if (value := payload.get("selected_template_id")) is not None
                else None
            ),
```

`do_GET`，在 `_serve_frontend_asset(parsed.path)` 之前插入两个路由：

```python
        if parsed.path == "/api/templates":
            self._write_json(HTTPStatus.OK, {"templates": self.server.session.list_templates()})
            return
        if parsed.path.startswith("/api/templates/"):
            raw_id = parsed.path.rsplit("/", 1)[-1]
            try:
                template_id = int(raw_id)
            except ValueError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "模板 id 必须是整数。"})
                return
            self._write_json(HTTPStatus.OK, self.server.session.get_template_detail(template_id))
            return
```

> 注意 GET 路由顺序：`/api/templates` 精确匹配放在 `startswith("/api/templates/")` 之前。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web_server_templates.py -v`
Expected: PASS

- [ ] **Step 5: 全后端回归 + 提交**

Run: `python -m pytest tests/test_web_server_templates.py tests/test_web_session_templates.py tests/test_web_session_auto_mode.py -v`
Expected: PASS

```bash
git add web_server.py tests/test_web_server_templates.py
git commit -m "feat(web): add template import/list/detail/select endpoints + reset passthrough"
```

---

## 阶段四：前端拆分与重排（原生 ES Module，无构建，手动验收）

> 前端无自动化测试框架；每个 Task 末尾用「启动服务器 + 浏览器验收」代替单测。启动命令：
> `python web_demo.py --database-url "$MYSQL_URL"`（需要模板功能时确保 `MYSQL_URL`/`PG_URL` 在环境或 `.env`）。
> 打开 `http://localhost:8000`（以 web_demo 实际端口为准，见其启动日志）。

### Task 8: 建立模块骨架 + 路由 + API 封装

**Files:**
- Create: `frontend/js/api.js`、`frontend/js/router.js`、`frontend/js/state.js`、`frontend/js/main.js`
- Modify: `frontend/index.html`（改为模块挂载点，引入 `main.js` 为 `type="module"`）

- [ ] **Step 1: 写 state.js（共享状态）**

`frontend/js/state.js`：

```javascript
export const appState = {
  userId: null,
  username: "",
  activePlayerId: null,
  selectedTemplateId: null,
};
```

- [ ] **Step 2: 写 api.js（后端封装，含现有端点 + 新模板端点）**

`frontend/js/api.js`（保留现有 JSON POST 与 SSE 流式；新增模板端点）：

```javascript
async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败：${res.status}`);
  return data;
}
async function getJson(path) {
  const res = await fetch(path);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败：${res.status}`);
  return data;
}

export const api = {
  ensureUser: (username) => postJson("/api/users/ensure", { username }),
  listPlayers: (userId) => getJson(`/api/players?user_id=${encodeURIComponent(userId)}`),
  getState: () => getJson("/api/state"),
  action: (input) => postJson("/api/action", { input }),
  setAuto: (enabled) => postJson("/api/auto", { enabled }),
  autoStep: (maxBeats) => postJson("/api/auto/step", { max_beats: maxBeats }),
  reset: (payload) => postJson("/api/reset", payload),
  newGame: (payload) => postJson("/api/new-game", payload),
  save: (payload) => postJson("/api/save", payload),
  load: (payload) => postJson("/api/load", payload),
  listTemplates: () => getJson("/api/templates"),
  templateDetail: (id) => getJson(`/api/templates/${id}`),
  importTemplate: (payload) => postJson("/api/templates/import", payload),
  selectTemplate: (templateId) => postJson("/api/templates/select", { template_id: templateId }),
};
```

- [ ] **Step 3: 写 router.js（hash 路由）**

`frontend/js/router.js`：

```javascript
const routes = {};
export function register(name, renderFn) { routes[name] = renderFn; }
export function navigate(name) { window.location.hash = `#/${name}`; }
function current() {
  const h = window.location.hash.replace(/^#\//, "");
  return h || "entry";
}
export function startRouter(mountEl) {
  const render = () => {
    const name = current();
    const fn = routes[name] || routes["entry"];
    mountEl.innerHTML = "";
    fn(mountEl);
  };
  window.addEventListener("hashchange", render);
  render();
}
```

- [ ] **Step 4: 写 main.js（挂载 + 注册占位页）**

`frontend/js/main.js`：

```javascript
import { startRouter, register } from "./router.js";

register("entry", (el) => { el.innerHTML = `<div class="route-entry">入口占位</div>`; });
register("login", (el) => { el.innerHTML = `<div class="route-login">登录占位</div>`; });
register("select", (el) => { el.innerHTML = `<div class="route-select">选择页占位</div>`; });

const mount = document.getElementById("app");
startRouter(mount);
```

- [ ] **Step 5: 改 index.html 为挂载点**

`frontend/index.html` body 精简为：

```html
<body>
  <div id="app"></div>
  <script type="module" src="./js/main.js"></script>
</body>
```

（保留 `<head>` 的 `<link rel="stylesheet" href="./styles.css">`。旧 `app.js` 暂时保留在仓库中，后续 Task 迁移完成后删除。）

- [ ] **Step 6: 浏览器验收**

Run: `python web_demo.py --database-url "$MYSQL_URL"`（若不测模板可省略 URL 用纯内存：`python web_demo.py`）
在浏览器打开首页 → 地址栏 `#/entry`、`#/login`、`#/select` 切换能看到对应占位文本，无 JS 报错（控制台）。

- [ ] **Step 7: 提交**

```bash
git add frontend/index.html frontend/js/
git commit -m "feat(frontend): ES module skeleton with router, api client, shared state"
```

### Task 9: 入口过渡页 + 登录页（含存档中心迁移）

**Files:**
- Create: `frontend/js/pages/entry.js`、`frontend/js/pages/login.js`
- Modify: `frontend/js/main.js`（改为 import 真实页面）、`frontend/styles.css`（入口/登录样式）

- [ ] **Step 1: entry.js**

```javascript
import { navigate } from "../router.js";
export function renderEntry(el) {
  el.innerHTML = `
    <section class="entry-hero">
      <div class="entry-pulse"></div>
      <h1 class="entry-title">Stagebound</h1>
      <p class="entry-sub">修仙叙事台</p>
      <button class="button button-primary entry-enter" type="button">进入</button>
    </section>`;
  el.querySelector(".entry-enter").addEventListener("click", () => navigate("login"));
}
```

- [ ] **Step 2: login.js（账号名连接 + 存档中心）**

```javascript
import { api } from "../api.js";
import { appState } from "../state.js";
import { navigate } from "../router.js";

export function renderLogin(el) {
  el.innerHTML = `
    <section class="login-shell">
      <h2>连接账号</h2>
      <div class="login-row">
        <input id="usernameInput" type="text" value="demo-user" placeholder="输入账号名">
        <button id="connectBtn" class="button button-primary" type="button">连接账号</button>
      </div>
      <div id="saveHub" class="save-hub" hidden>
        <div class="save-slot-list" id="saveSlotList"></div>
      </div>
      <p id="loginMsg" class="login-msg"></p>
    </section>`;

  const msg = el.querySelector("#loginMsg");
  el.querySelector("#connectBtn").addEventListener("click", async () => {
    try {
      const { user } = await api.ensureUser(el.querySelector("#usernameInput").value.trim());
      appState.userId = user.id;
      appState.username = user.username;
      await renderSaves(el);
      el.querySelector("#saveHub").hidden = false;
      msg.textContent = "已连接，可选择存档或直接进入。";
    } catch (e) { msg.textContent = e.message; }
  });
}

async function renderSaves(el) {
  const { players } = await api.listPlayers(appState.userId);
  const list = el.querySelector("#saveSlotList");
  if (!players.length) {
    list.innerHTML = `<div class="save-empty"><strong>还没有存档</strong>
      <button id="enterNew" class="button button-primary" type="button">进入并新开一局</button></div>`;
  } else {
    list.innerHTML = players.map(p =>
      `<button class="save-slot" data-pid="${p.id}">${p.slot_name || "存档"} · #${p.id}</button>`
    ).join("") + `<button id="enterNew" class="button button-ghost" type="button">再开一局</button>`;
    list.querySelectorAll(".save-slot").forEach(b =>
      b.addEventListener("click", () => {
        appState.activePlayerId = Number(b.dataset.pid);
        navigate("select");
      }));
  }
  const en = list.querySelector("#enterNew");
  if (en) en.addEventListener("click", () => navigate("select"));
}
```

- [ ] **Step 3: 接进 main.js**

`frontend/js/main.js` 顶部改为：

```javascript
import { startRouter, register } from "./router.js";
import { renderEntry } from "./pages/entry.js";
import { renderLogin } from "./pages/login.js";

register("entry", renderEntry);
register("login", renderLogin);
register("select", (el) => { el.innerHTML = `<div class="route-select">选择页占位</div>`; });

const mount = document.getElementById("app");
startRouter(mount);
```

- [ ] **Step 4: styles.css 增入口/登录样式**

在 `frontend/styles.css` 末尾追加（保留现有仙侠基调变量；若已有 `--` 主题变量则复用）：

```css
.entry-hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;text-align:center}
.entry-title{font-size:48px;letter-spacing:.2em}
.entry-sub{opacity:.7;letter-spacing:.4em}
.entry-enter{padding:12px 48px;font-size:16px}
.login-shell{max-width:640px;margin:80px auto;padding:24px}
.login-row{display:flex;gap:12px;margin:16px 0}
.login-row input{flex:1;padding:10px}
.save-hub{margin-top:24px}
.save-slot-list{display:flex;flex-direction:column;gap:8px}
.save-slot{text-align:left;padding:12px}
.login-msg{opacity:.7;margin-top:12px}
```

- [ ] **Step 5: 浏览器验收**

启动后：`#/entry` 点「进入」跳登录；输入账号名点「连接账号」，能看到存档列表或空态；点存档/再开一局跳到 `#/select` 占位。控制台无报错。

- [ ] **Step 6: 提交**

```bash
git add frontend/js/pages/entry.js frontend/js/pages/login.js frontend/js/main.js frontend/styles.css
git commit -m "feat(frontend): entry transition page + login with save hub"
```

### Task 10: 选择页外壳 + 窄标签侧边栏 + 工作区容器

**Files:**
- Create: `frontend/js/pages/select.js`（侧边栏 + 两个工作区挂载点，切换逻辑）
- Modify: `frontend/js/main.js`、`frontend/styles.css`

- [ ] **Step 1: select.js**

```javascript
import { appState } from "../state.js";
import { navigate } from "../router.js";
import { renderChat } from "./chat.js";
import { renderTemplates } from "./templates.js";

export function renderSelect(el) {
  if (!appState.userId) { navigate("login"); return; }
  el.innerHTML = `
    <div class="select-shell">
      <nav class="sidebar">
        <div class="sidebar-brand">Stagebound</div>
        <button class="side-item is-active" data-view="chat" type="button">💬 对话</button>
        <button class="side-item" data-view="templates" type="button">📚 模板库</button>
        <div class="sidebar-user">👤 ${appState.username || "-"}</div>
      </nav>
      <main class="workspace" id="workspace"></main>
    </div>`;

  const ws = el.querySelector("#workspace");
  const items = el.querySelectorAll(".side-item");
  const show = (view) => {
    items.forEach(i => i.classList.toggle("is-active", i.dataset.view === view));
    ws.innerHTML = "";
    (view === "templates" ? renderTemplates : renderChat)(ws);
  };
  items.forEach(i => i.addEventListener("click", () => show(i.dataset.view)));
  show("chat");
}
```

- [ ] **Step 2: 占位 chat.js / templates.js（让 select 可跑）**

`frontend/js/pages/chat.js`：

```javascript
export function renderChat(el) { el.innerHTML = `<div class="chat-placeholder">对话工作区占位</div>`; }
```

`frontend/js/pages/templates.js`：

```javascript
export function renderTemplates(el) { el.innerHTML = `<div class="tpl-placeholder">模板工作区占位</div>`; }
```

- [ ] **Step 3: 接进 main.js**

把 `select` 注册改为真实：

```javascript
import { renderSelect } from "./pages/select.js";
register("select", renderSelect);
```

- [ ] **Step 4: styles.css 增选择页/侧边栏样式（窄，约 120px）**

```css
.select-shell{display:flex;min-height:100vh}
.sidebar{width:120px;flex:0 0 120px;background:#141b2b;display:flex;flex-direction:column;padding:12px 8px;gap:8px}
.sidebar-brand{font-weight:600;font-size:13px;padding:4px 6px 10px;opacity:.9}
.side-item{text-align:left;padding:8px;border-radius:8px;background:transparent;border:0;color:inherit;cursor:pointer;font-size:13px}
.side-item.is-active{background:#2b3a5b}
.sidebar-user{margin-top:auto;font-size:11px;opacity:.7;padding:8px 6px;border-top:1px solid #2b3a5b}
.workspace{flex:1;padding:16px;overflow:auto}
```

- [ ] **Step 5: 浏览器验收**

登录后进 `#/select`：左侧 120px 侧边栏，两项可切换、高亮跟随，右侧显示对应占位；未登录直接访问 `#/select` 会被弹回登录页。

- [ ] **Step 6: 提交**

```bash
git add frontend/js/pages/select.js frontend/js/pages/chat.js frontend/js/pages/templates.js frontend/js/main.js frontend/styles.css
git commit -m "feat(frontend): select page shell with narrow labeled sidebar + workspace switch"
```

### Task 11: 对话工作区（迁移现有对话/自动/JSON 逻辑 + 选模板按钮）

**Files:**
- Modify: `frontend/js/pages/chat.js`（从旧 `app.js` 迁移对话流、输入、发送、自动开关、SSE、JSON 折叠面板）
- Create: `frontend/js/components/templatePickerModal.js`
- Modify: `frontend/styles.css`

- [ ] **Step 1: chat.js 布局与逻辑骨架**

参照旧 `app.js` 的行为迁移。核心 DOM：聊天流 `#storyFeed`、输入 `#playerInput`、发送 `#submitButton`、自动 `#autoModeToggle`、选模板 `#pickTemplateBtn`、当前模板标识 `#currentTemplateTag`、JSON 折叠 `#jsonPanel`。

```javascript
import { api } from "../api.js";
import { appState } from "../state.js";
import { openTemplatePicker } from "../components/templatePickerModal.js";

export function renderChat(el) {
  el.innerHTML = `
    <div class="chat-workspace">
      <div class="chat-topbar">
        <button id="toggleSideCard" class="button button-ghost" type="button">角色/存档</button>
        <span id="currentTemplateTag" class="tpl-tag">未使用模板</span>
        <div class="chat-topbar-right">
          <button id="pickTemplateBtn" class="button button-ghost" type="button">📚 选模板</button>
          <label class="auto-toggle"><input type="checkbox" id="autoModeToggle"><span>自动</span></label>
        </div>
      </div>
      <aside id="sideCard" class="chat-sidecard" hidden><div class="placeholder">角色卡/背包（迁移自旧 UI）</div></aside>
      <div class="chat-thread" id="storyFeed"><div class="chat-empty">等待剧情开始</div></div>
      <div class="chat-composer">
        <textarea id="playerInput" rows="4" placeholder="描述你想说什么、做什么……"></textarea>
        <div class="composer-actions">
          <button id="submitButton" class="button button-primary" type="button">发送</button>
        </div>
      </div>
      <details class="json-fold"><summary>JSON 调试</summary><pre id="parserJson"></pre></details>
    </div>`;

  const feed = el.querySelector("#storyFeed");
  const input = el.querySelector("#playerInput");
  const jsonPre = el.querySelector("#parserJson");

  const refreshTemplateTag = () => {
    el.querySelector("#currentTemplateTag").textContent =
      appState.selectedTemplateId ? `模板 #${appState.selectedTemplateId}` : "未使用模板";
  };
  refreshTemplateTag();

  el.querySelector("#toggleSideCard").addEventListener("click", () => {
    const s = el.querySelector("#sideCard"); s.hidden = !s.hidden;
  });
  el.querySelector("#pickTemplateBtn").addEventListener("click", () =>
    openTemplatePicker(() => refreshTemplateTag()));

  el.querySelector("#autoModeToggle").addEventListener("change", async (e) => {
    await api.setAuto(e.target.checked);
    if (e.target.checked) { const s = await api.autoStep(4); renderState(s, feed, jsonPre); }
  });

  el.querySelector("#submitButton").addEventListener("click", async () => {
    const text = input.value.trim();
    if (!text) return;
    appendBubble(feed, "player", text);
    input.value = "";
    try { const state = await api.action(text); renderState(state, feed, jsonPre); }
    catch (err) { appendBubble(feed, "system", err.message); }
  });
}

function appendBubble(feed, who, text) {
  const empty = feed.querySelector(".chat-empty"); if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = `bubble bubble-${who}`;
  div.textContent = text;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function renderState(state, feed, jsonPre) {
  jsonPre.textContent = JSON.stringify(state, null, 2);
  const history = (state.history || []).slice(-1);
  history.forEach(h => appendBubble(feed, h.speaker === "player" ? "player" : "npc", h.text || ""));
}
```

> 迁移提示：旧 `app.js` 已有更完整的 SSE 流式渲染与历史去重逻辑。以旧行为为准，把流式 `apply_player_action_streaming`（`/api/action` + `Accept: text/event-stream`）迁移进来替换上面的简单 `api.action`，保证不回退。上面的 `renderState` 是最小版占位，迁移时用旧逻辑补全气泡/角色/张力渲染。

- [ ] **Step 2: templatePickerModal.js（小弹窗，grid，默认未使用，可清除）**

```javascript
import { api } from "../api.js";
import { appState } from "../state.js";

export async function openTemplatePicker(onDone) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-small">
      <div class="modal-head">
        <strong>选择情节模板</strong>
        <span class="modal-status" id="pickStatus"></span>
        <button class="modal-close" type="button">✕</button>
      </div>
      <div class="tpl-grid" id="pickGrid"><div class="placeholder">加载中…</div></div>
      <div class="modal-foot">
        <button id="clearTpl" class="button button-ghost" type="button">清除模板</button>
        <button id="confirmTpl" class="button button-primary" type="button">确认</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  const status = overlay.querySelector("#pickStatus");
  const grid = overlay.querySelector("#pickGrid");
  let chosen = appState.selectedTemplateId;
  const refreshStatus = () => { status.textContent = chosen ? `已选 #${chosen}` : "默认：未使用模板"; };
  refreshStatus();

  const { templates } = await api.listTemplates();
  grid.innerHTML = `
    <button class="tpl-card ${!chosen ? "is-active" : ""}" data-id="">不用模板<br><small>自由发挥</small></button>` +
    templates.map(t => `<button class="tpl-card ${chosen === t.template_id ? "is-active" : ""}"
      data-id="${t.template_id}"><b>${t.source_title}</b><br><small>${t.beat_count} 情节节点</small></button>`).join("");

  grid.querySelectorAll(".tpl-card").forEach(c => c.addEventListener("click", () => {
    chosen = c.dataset.id ? Number(c.dataset.id) : null;
    grid.querySelectorAll(".tpl-card").forEach(x => x.classList.remove("is-active"));
    c.classList.add("is-active");
    refreshStatus();
  }));

  overlay.querySelector("#clearTpl").addEventListener("click", () => {
    chosen = null;
    grid.querySelectorAll(".tpl-card").forEach(x =>
      x.classList.toggle("is-active", x.dataset.id === ""));
    refreshStatus();
  });

  overlay.querySelector("#confirmTpl").addEventListener("click", async () => {
    await api.selectTemplate(chosen);
    appState.selectedTemplateId = chosen;
    close();
    if (onDone) onDone();
  });
}
```

- [ ] **Step 3: styles.css 增对话工作区 + 弹窗样式**

```css
.chat-workspace{display:flex;flex-direction:column;gap:12px;max-width:860px;margin:0 auto}
.chat-topbar{display:flex;align-items:center;gap:12px}
.chat-topbar-right{margin-left:auto;display:flex;gap:12px;align-items:center}
.tpl-tag{font-size:12px;opacity:.75;padding:2px 10px;border:1px solid #33415580;border-radius:12px}
.chat-sidecard{border:1px solid #33415580;border-radius:8px;padding:12px}
.chat-thread{min-height:360px;display:flex;flex-direction:column;gap:8px;padding:8px}
.bubble{padding:8px 12px;border-radius:10px;max-width:80%}
.bubble-player{align-self:flex-end;background:#2b3a5b}
.bubble-npc,.bubble-system{align-self:flex-start;background:#1f2740}
.chat-composer textarea{width:100%;padding:10px}
.json-fold{margin-top:8px}
.json-fold pre{max-height:280px;overflow:auto;font-size:12px}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:50}
.modal{background:#141b2b;border:1px solid #2b3a5b;border-radius:12px;padding:16px}
.modal-small{width:min(560px,90vw)}
.modal-head{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.modal-status{font-size:12px;opacity:.7;margin-left:auto}
.modal-close{background:transparent;border:0;color:inherit;cursor:pointer}
.modal-foot{display:flex;justify-content:flex-end;gap:12px;margin-top:12px}
.tpl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.tpl-card{padding:12px;border:1px solid #33415580;border-radius:8px;background:transparent;color:inherit;cursor:pointer;text-align:left}
.tpl-card.is-active{border-color:#4a6bff;background:#2b3a5b55}
```

- [ ] **Step 4: 浏览器验收**

对话页：发送消息能出现气泡、JSON 折叠可展开、自动开关调用 `/api/auto`；点「📚 选模板」弹出 grid 小弹窗，默认高亮「不用模板」并显示「默认：未使用模板」，选中某模板→确认→顶部标识变为「模板 #id」；再次打开点「清除模板」→回到未使用。控制台无报错。

- [ ] **Step 5: 提交**

```bash
git add frontend/js/pages/chat.js frontend/js/components/templatePickerModal.js frontend/styles.css
git commit -m "feat(frontend): chat workspace + template picker modal (grid, default none, clearable)"
```

### Task 12: 模板工作区（上传解析 + grid 列表 + 80% 详情大弹窗）

**Files:**
- Modify: `frontend/js/pages/templates.js`
- Create: `frontend/js/components/templateDetailModal.js`
- Modify: `frontend/styles.css`

- [ ] **Step 1: templates.js（左上传 + 右 grid 列表）**

```javascript
import { api } from "../api.js";
import { appState } from "../state.js";
import { openTemplateDetail } from "../components/templateDetailModal.js";

export function renderTemplates(el) {
  el.innerHTML = `
    <div class="tpl-workspace">
      <section class="tpl-upload">
        <h3>上传小说 · 解析情节</h3>
        <input id="tplTitle" type="text" placeholder="来源标题（如：鹿鼎记）">
        <input id="tplFile" type="file" accept=".txt,text/plain">
        <button id="tplImport" class="button button-primary" type="button">开始解析情节</button>
        <p id="tplProgress" class="tpl-progress"></p>
      </section>
      <section class="tpl-list">
        <h3>已有模板</h3>
        <div class="tpl-grid" id="tplGrid"><div class="placeholder">加载中…</div></div>
      </section>
    </div>`;

  const grid = el.querySelector("#tplGrid");
  const progress = el.querySelector("#tplProgress");

  const loadList = async () => {
    const { templates } = await api.listTemplates();
    grid.innerHTML = templates.length
      ? templates.map(t => `<button class="tpl-card" data-id="${t.template_id}">
          <b>${t.source_title}</b><br><small>${t.beat_count} 情节节点</small></button>`).join("")
      : `<div class="placeholder">还没有模板，先上传一部小说解析。</div>`;
    grid.querySelectorAll(".tpl-card").forEach(c =>
      c.addEventListener("click", () => openTemplateDetail(Number(c.dataset.id))));
  };
  loadList();

  el.querySelector("#tplImport").addEventListener("click", async () => {
    const title = el.querySelector("#tplTitle").value.trim();
    const file = el.querySelector("#tplFile").files[0];
    if (!title || !file) { progress.textContent = "请填写标题并选择文件。"; return; }
    progress.textContent = "读取文件…";
    const text = await file.text();
    progress.textContent = "解析中：分块 → 聚类 → 提取骨架（可能较久）…";
    try {
      const { template_id } = await api.importTemplate({
        source_title: title, text, user_id: appState.userId || 0,
      });
      progress.textContent = `解析完成，模板 #${template_id}`;
      await loadList();
    } catch (e) { progress.textContent = `解析失败：${e.message}`; }
  });
}
```

- [ ] **Step 2: templateDetailModal.js（80% 居中大弹窗）**

```javascript
import { api } from "../api.js";

export async function openTemplateDetail(templateId) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-large">
      <div class="modal-head"><strong>模板详情 #${templateId}</strong>
        <button class="modal-close" type="button">✕</button></div>
      <div class="modal-body" id="detailBody"><div class="placeholder">加载中…</div></div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  try {
    const d = await api.templateDetail(templateId);
    const sb = d.style_bible || {};
    overlay.querySelector("#detailBody").innerHTML = `
      <h4>文风</h4>
      <p>基调：${(sb.tone_tags || []).join("、") || "-"}</p>
      <p>世界观：${sb.world_premise || "-"}</p>
      <h4>情节节点（${(d.beats || []).length}）</h4>
      <ul>${(d.beats || []).map(b => `<li><b>${b.label}</b>：${b.summary}</li>`).join("") || "<li>-</li>"}</ul>
      <h4>角色骨架（${(d.characters || []).length}）</h4>
      <ul>${(d.characters || []).map(c => `<li><b>${c.name}</b>：${c.role_summary}</li>`).join("") || "<li>-</li>"}</ul>`;
  } catch (e) {
    overlay.querySelector("#detailBody").innerHTML = `<p>加载失败：${e.message}</p>`;
  }
}
```

- [ ] **Step 3: styles.css 增模板工作区 + 大弹窗样式**

```css
.tpl-workspace{display:grid;grid-template-columns:minmax(240px,340px) 1fr;gap:16px}
.tpl-upload{border:1px dashed #6b5a3b;border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px;height:fit-content}
.tpl-upload input[type=text]{padding:8px}
.tpl-progress{font-size:12px;opacity:.75}
.modal-large{width:80vw;height:80vh;display:flex;flex-direction:column}
.modal-large .modal-body{flex:1;overflow:auto;padding:8px 4px}
```

> 大弹窗「四周留白」由 overlay 的居中 + `80vw/80vh` 自然形成。

- [ ] **Step 4: 浏览器验收**

模板页：右侧显示已有模板 grid（或空态）；填标题+选 `.txt` 文件点解析，进度文案更新，成功后列表刷新出现新卡片；点任一模板卡片弹出约 80%、居中、四周留白的大弹窗，展示文风/情节节点/角色，点遮罩或 ✕ 关闭。控制台无报错。

- [ ] **Step 5: 提交**

```bash
git add frontend/js/pages/templates.js frontend/js/components/templateDetailModal.js frontend/styles.css
git commit -m "feat(frontend): template workspace with upload/parse + grid list + 80% detail modal"
```

### Task 13: 清理旧 app.js + 全流程收尾验收

**Files:**
- Modify/Delete: `frontend/app.js`（确认逻辑已全部迁移后删除；若仍有未迁移的角色卡/背包/张力渲染，先补迁到 chat.js 再删）
- Modify: `frontend/index.html`（移除任何遗留对 `app.js` 的引用）

- [ ] **Step 1: 核对迁移完整性**

对照旧 `frontend/app.js`，逐项确认：SSE 流式渲染、历史去重、角色卡/背包/张力、存档中心的保存/读取/新开局，都已在新模块（chat.js / login.js）实现。把仍缺失的补齐到对应模块。

- [ ] **Step 2: 删除旧文件**

确认 `index.html` 不再引用后：

```bash
git rm frontend/app.js
```

- [ ] **Step 3: 全流程浏览器验收**

启动 `python web_demo.py --database-url "$MYSQL_URL"`（确保 `MYSQL_URL`/`PG_URL` 就绪以测模板）：
1. 入口页「进入」→ 登录页连接账号 → 看到存档中心
2. 进选择页 → 侧边栏切换对话/模板
3. 对话页发送、自动开关、选模板弹窗（默认未使用/选择/清除）
4. 模板页上传解析、列表刷新、点卡片看 80% 详情弹窗
5. 存档保存/读取/再开一局
控制台全程无报错。

- [ ] **Step 4: 后端回归**

Run: `python -m pytest tests/test_template_repository.py tests/test_template_service.py tests/test_web_session_templates.py tests/test_web_server_templates.py tests/test_web_demo_template_wiring.py tests/test_web_session_auto_mode.py -v`
Expected: PASS（需数据库可达）

- [ ] **Step 5: 提交**

```bash
git add frontend/index.html
git rm frontend/app.js
git commit -m "chore(frontend): remove legacy monolithic app.js after module migration"
```

---

## Self-Review 记录（写计划时自查）

- **Spec 覆盖**：四页流程（Task 8-10）、对话工作区+选模板弹窗默认/清除标识（Task 11）、模板工作区+80% 详情弹窗（Task 12）、后端 list/detail/import/select 端点（Task 1-2,7）、服务接入会话（Task 3,6）、selected_template 透传+快照（Task 4）、suggest_plot_beats 注入（Task 5）、前端多模块拆分（Task 8-13）、轻量账号名登录（Task 9）——均有对应任务。
- **非目标**：密码认证、multipart 大文件、模板删除/编辑、情节高级策略——计划中未引入，符合 spec。
- **类型一致性**：`selected_template_id`（后端 int|None）↔ 前端 `selectedTemplateId`；`set_selected_template`/`selectTemplate`、`import_template`/`importTemplate`、`list_templates`/`listTemplates`、`get_template_detail`/`templateDetail` 命名前后一致。
- **占位扫描**：前端 Task 含最小可运行代码；chat.js 明确标注需以旧 app.js 的 SSE 逻辑补全（迁移而非从零），不是空占位。
