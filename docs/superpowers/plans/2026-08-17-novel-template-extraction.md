# 小说模板情景提取（StoryTemplate 子包）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `StoryTemplate/` 子包，把一部中文小说离线提炼成 4 类结构化模板（风格/角色/桥段/骨架）+ 原文向量片段，对外经单一 `StoryTemplateService` Facade 提供导入与 4 个检索接口。

**Architecture:** 分层归并流水线（切块 → 逐块提炼 → 向量聚合 → 全局归并 → 落库）。子包严格单向依赖已落地的基础模块（`datatypes`/`embedding`/`vectordb`/`db`）与 `BaseAgent`，不反向依赖 easy_game 运行时。结构化产物存 MySQL 4 分表，原文片段存 pgvector（按 `template_id` 维度隔离，前缀 `tmpl:{template_id}:`）。

**服务定位（用户 2026-08-17 澄清）：** StoryTemplate 是**长期共享服务**，非一次性脚本。本次交付「小说 → 4 类模板入库」的可复用能力；以后消费方（不在本次范围）包括：游戏构建期用户从库里**选用**已有模板、大章节开始时按剧情**相似性**向模板骨架偏移规划。因此提取逻辑必须**完全通用**（不含任何特定小说的专有词），鹿鼎记仅为验证语料。

**模板归属（用户 2026-08-17 拍板）：全局可见 + 保留 user_id 扩展位。** 模板是平台级共享资产，所有游戏/存档均可选用（检索**不按 user/player 过滤**），与回忆系统的 `u{user}:p{player}` 租户隔离**解耦**。故 `import_novel(*, user_id=0, source_title, text)` —— **user_id 可选（默认 0=平台/官方，只存不过滤，作扩展预留），不要 player_id**；`story_template` 表保留 `user_id` 列作归属标记，便于以后扩展「用户私有模板」而无需迁表；Repository 查询不按 user 过滤；向量片段前缀用 `tmpl:{template_id}:`（`datatypes.template_scope_prefix`，仅隔离多模板）。`source_title` 作为模板来源元数据。

**Tech Stack:** Python 3.12 / SQLAlchemy 2.0 (MySQL `mysql+pymysql://` + 自持 MetaData) / pgvector (`vectordb.PgVectorStore`) / bge-small-zh-v1.5 (`embedding.BgeEmbeddingModel`, 512 维 COSINE) / DeepSeek LLM (`BaseAgent`, `response_format="json"` + 两次重试)。

**规约（继承既有约定）：** 中文回复 + 中文注释；TDD 红→绿→中文 commit，**不 push**；面向接口 + 依赖注入；测试用真依赖（真 bge / 真 MySQL / 真 pgvector / 真 LLM 极短文本）。

**验证解释器：** `/Users/qiuyunhao.1/miniconda3/bin/python3`（下称 `PY`）。运行测试统一 `HF_ENDPOINT=https://hf-mirror.com $PY -m unittest tests.<mod> -v`。

**已确认的基础模块 API（实现时严格照此调用，勿臆造）：**
- `datatypes.VectorDoc(doc_id, doc_type, text, metadata={})` frozen；`datatypes.ScoredDoc(doc, score, factors={})` frozen。
- `datatypes.template_scope_prefix(template_id: int) -> str` → `"tmpl:{tid}:"`（**本次新增**，全局共享模板的向量前缀，不带 user/player；`datatypes/tenancy.py` 现有 `template_prefix(tid, uid, pid)` 保留不动，本子包不用它）。
- `embedding.EmbeddingModel`（抽象）：`.dimension -> int`、`.encode(texts: Sequence[str]) -> list[list[float]]`；实现 `embedding.BgeEmbeddingModel()`。
- `vectordb.VectorStore`（抽象）：`.upsert(rows: Sequence[tuple[VectorDoc, list[float]]])`、`.search(query_vector, *, top_k=10, filters=None) -> list[ScoredDoc]`、`.delete(ids)`；实现 `vectordb.PgVectorStore(database_url, *, table="vector_docs", dim=512)`，`filters` 里 `doc_type` 按顶层列过滤，其余键按 JSONB `meta->>key` 等值过滤。
- `db.Database(config: DatabaseConfig | str)`：`.create_all(metadata)`、`.session()`（contextmanager，不自动 commit）、`.engine`。
- `BaseAgent(base_url, model, api_key, system_prompt, client, **kw)`：`.command(instruction, history=None, response_format=None)`，`response_format="json"` 走 JSON 模式并本地修复截断 JSON；测试传 `client=<fake>`。

**测试库连接串：** MySQL `mysql+pymysql://root@localhost:3306/easygame_test`；pgvector `postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test`（读 `.env`：`os.environ["MYSQL_URL"]` / `os.environ["PG_URL"]`）。

---

## File Structure

```text
StoryTemplate/
├── __init__.py                # 对外表面：导出 StoryTemplateService + 4 类 TypedDict
├── TemplateSchema.py          # 4 类产物 TypedDict + JSON response schema（纯数据契约）
├── TemplateChunker.py         # 长文切块 + order_index（卷/章/节/回 正则）
├── TemplateClustering.py      # 纯向量算法：事件块筛选 / 桥段聚类去重 / 角色合并（注入 EmbeddingModel）
├── TemplateExtractAgent.py    # 继承 BaseAgent：Level1 逐块信号 + Level3 四类全局归并（两次重试）
├── TemplateRepository.py      # 4 张 MySQL 分表持久化（注入 db.Database，自持 MetaData）
├── StoryTemplateService.py    # 对外 Facade：import_novel + get/suggest/next/search
└── factory.py                 # 装配 Service + 注入默认实现（延迟构造 bge/pg/mysql）

tests/
├── test_template_chunker.py       # 纯逻辑
├── test_template_schema.py        # 纯逻辑
├── test_template_clustering.py    # 真 bge
├── test_template_extract_agent.py # fake LLM client（离线，秒级）
├── test_template_repository.py    # 真 MySQL
├── test_template_service.py       # fake LLM + 真 MySQL + 真 pgvector（极短小说端到端）
└── test_template_e2e_luding.py    # 手动触发：真 LLM + 鹿鼎记全文（不进日常套件）

docs/foundation-requirements.md    # 补 StoryTemplate 依赖说明（pymysql 已在，补 4 表 + 运行入口）
```

每文件单一职责；子模块（Chunker/Clustering/ExtractAgent/Repository）不对外暴露，只经 Service 使用。

---

## Task 1: TemplateSchema —— 4 类产物数据契约

**Files:**
- Create: `StoryTemplate/TemplateSchema.py`
- Test: `tests/test_template_schema.py`

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import unittest

from StoryTemplate.TemplateSchema import (
    StyleBible, CharacterArchetype, PlotBeat, PlotSkeletonNode,
    STYLE_BIBLE_RESPONSE_SCHEMA, CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
    PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
    CHUNK_SIGNAL_RESPONSE_SCHEMA,
    empty_style_bible,
)


class SchemaShapeTests(unittest.TestCase):
    def test_style_bible_has_all_fields(self):
        sb: StyleBible = {
            "narrative_voice": "第三人称全知", "tone_tags": ["古雅", "诙谐"],
            "prose_rhythm": "长短交错", "signature_devices": ["环境白描"],
            "world_premise": "江湖庙堂交织", "cultivation_system": "无",
            "factions": ["天地会"], "key_locations": ["扬州"],
            "world_rules": ["不可泄露身份"], "lexicon": ["韦小宝"],
        }
        self.assertEqual(set(StyleBible.__annotations__), set(sb))

    def test_empty_style_bible_is_valid_default(self):
        sb = empty_style_bible()
        self.assertEqual(sb["narrative_voice"], "")
        self.assertEqual(sb["tone_tags"], [])
        self.assertEqual(set(StyleBible.__annotations__), set(sb))

    def test_response_schemas_are_json_object_type(self):
        for schema in (
            STYLE_BIBLE_RESPONSE_SCHEMA, CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
            PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
            CHUNK_SIGNAL_RESPONSE_SCHEMA,
        ):
            self.assertEqual(schema["type"], "json_schema")
            self.assertIn("json_schema", schema)

    def test_character_and_beat_and_node_fields(self):
        self.assertEqual(
            set(CharacterArchetype.__annotations__),
            {"name", "role_summary", "persona", "speech_style", "secrets",
             "signature_relations", "suggested_layer"},
        )
        self.assertEqual(
            set(PlotBeat.__annotations__),
            {"beat_id", "label", "tags", "summary", "dramatic_function", "reusable_conflict"},
        )
        self.assertEqual(
            set(PlotSkeletonNode.__annotations__),
            {"node_id", "order_index", "title", "event_summary",
             "preconditions", "maps_to_chapter_hint"},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_schema -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'StoryTemplate'`

- [ ] **Step 3: 建包 + 写实现**

先建空 `StoryTemplate/__init__.py`（内容暂空，Task 7 再填导出），再写 `StoryTemplate/TemplateSchema.py`：

```python
from __future__ import annotations

from typing import Any, TypedDict

"""4 类模板产物的数据契约（纯 TypedDict）+ LLM JSON response schema。

沿用 PlayerWriter/PlaywriterSchema.py 的 json_schema 风格：response schema 供
BaseAgent.command(response_format=...) 约束 LLM 输出结构。TypedDict 是出库/入库口径。
"""


class StyleBible(TypedDict):
    narrative_voice: str
    tone_tags: list[str]
    prose_rhythm: str
    signature_devices: list[str]
    world_premise: str
    cultivation_system: str
    factions: list[str]
    key_locations: list[str]
    world_rules: list[str]
    lexicon: list[str]


class CharacterArchetype(TypedDict):
    name: str
    role_summary: str
    persona: list[str]
    speech_style: str
    secrets: list[str]
    signature_relations: list[str]
    suggested_layer: str


class PlotBeat(TypedDict):
    beat_id: str
    label: str
    tags: list[str]
    summary: str
    dramatic_function: str
    reusable_conflict: str


class PlotSkeletonNode(TypedDict):
    node_id: str
    order_index: int
    title: str
    event_summary: str
    preconditions: list[str]
    maps_to_chapter_hint: str


class ChunkSignal(TypedDict):
    """Level1 逐块提炼出的局部信号（未归并）。"""
    chunk_id: str
    order_index: int
    style_tone_tags: list[str]
    style_devices: list[str]
    characters: list[dict[str, Any]]  # {name, behavior}
    is_event: bool
    event_summary: str


def empty_style_bible() -> StyleBible:
    return {
        "narrative_voice": "", "tone_tags": [], "prose_rhythm": "",
        "signature_devices": [], "world_premise": "", "cultivation_system": "",
        "factions": [], "key_locations": [], "world_rules": [], "lexicon": [],
    }


def _obj_schema(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}

STYLE_BIBLE_RESPONSE_SCHEMA = _obj_schema(
    "style_bible",
    {
        "narrative_voice": _STR, "tone_tags": _STR_LIST, "prose_rhythm": _STR,
        "signature_devices": _STR_LIST, "world_premise": _STR,
        "cultivation_system": _STR, "factions": _STR_LIST,
        "key_locations": _STR_LIST, "world_rules": _STR_LIST, "lexicon": _STR_LIST,
    },
    ["narrative_voice", "tone_tags", "prose_rhythm", "signature_devices",
     "world_premise", "cultivation_system", "factions", "key_locations",
     "world_rules", "lexicon"],
)

CHARACTER_ARCHETYPE_RESPONSE_SCHEMA = _obj_schema(
    "character_archetypes",
    {"characters": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": _STR, "role_summary": _STR, "persona": _STR_LIST,
            "speech_style": _STR, "secrets": _STR_LIST,
            "signature_relations": _STR_LIST, "suggested_layer": _STR,
        },
        "required": ["name", "role_summary", "persona", "speech_style",
                     "secrets", "signature_relations", "suggested_layer"],
        "additionalProperties": False,
    }}},
    ["characters"],
)

PLOT_BEAT_RESPONSE_SCHEMA = _obj_schema(
    "plot_beats",
    {"beats": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "label": _STR, "tags": _STR_LIST, "summary": _STR,
            "dramatic_function": _STR, "reusable_conflict": _STR,
        },
        "required": ["label", "tags", "summary", "dramatic_function", "reusable_conflict"],
        "additionalProperties": False,
    }}},
    ["beats"],
)

PLOT_SKELETON_RESPONSE_SCHEMA = _obj_schema(
    "plot_skeleton",
    {"nodes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": _STR, "event_summary": _STR,
            "preconditions": _STR_LIST, "maps_to_chapter_hint": _STR,
        },
        "required": ["title", "event_summary", "preconditions", "maps_to_chapter_hint"],
        "additionalProperties": False,
    }}},
    ["nodes"],
)

CHUNK_SIGNAL_RESPONSE_SCHEMA = _obj_schema(
    "chunk_signal",
    {
        "style_tone_tags": _STR_LIST, "style_devices": _STR_LIST,
        "characters": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _STR, "behavior": _STR},
            "required": ["name", "behavior"], "additionalProperties": False,
        }},
        "is_event": {"type": "boolean"}, "event_summary": _STR,
    },
    ["style_tone_tags", "style_devices", "characters", "is_event", "event_summary"],
)
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_schema -v`
Expected: PASS（4 tests）

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/__init__.py StoryTemplate/TemplateSchema.py tests/test_template_schema.py
git commit -m "feat(story-template): 4 类产物 TypedDict + LLM response schema"
```

---

## Task 2: TemplateChunker —— 卷/章/节/回 切块 + order_index

**Files:**
- Create: `StoryTemplate/TemplateChunker.py`
- Test: `tests/test_template_chunker.py`

**契约：** `Chunk` 为 `@dataclass(frozen=True)`，字段 `chunk_id: str`、`order_index: int`、`text: str`、`title: str`。`TemplateChunker(chunk_size: int = 2000)`，方法 `chunk(text: str) -> list[Chunk]`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import unittest

from StoryTemplate.TemplateChunker import TemplateChunker, Chunk


class ChapterMarkerTests(unittest.TestCase):
    def test_chinese_numeral_chapters(self):
        text = "第一章 初入江湖\n甲行走江湖。\n第二章 风波\n乙掀起风波。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].title, "初入江湖")
        self.assertEqual(chunks[0].order_index, 0)
        self.assertIn("甲行走江湖", chunks[0].text)
        self.assertEqual(chunks[1].order_index, 1)

    def test_arabic_and_spaced_and_no_prefix(self):
        text = "第37章 甲\n内容一\n卷二\n内容二\n三十七回 乙\n内容三"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 3)

    def test_hui_marker(self):
        text = "第一百零八回 大结局\n尾声内容。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "大结局")

    def test_volume_composite_order(self):
        # 卷号作 order 高位：卷一/章二 应排在 卷二/章一 之前
        text = ("第一卷\n第二章 甲\n甲内容\n"
                "第二卷\n第一章 乙\n乙内容")
        chunks = TemplateChunker().chunk(text)
        titles = [c.title for c in chunks]
        self.assertEqual(titles.index("甲") < titles.index("乙"), True)


class BoundaryTests(unittest.TestCase):
    def test_no_marker_falls_back_to_sliding_window(self):
        text = "甲" * 4500  # 无任何标记
        chunks = TemplateChunker(chunk_size=2000).chunk(text)
        self.assertEqual(len(chunks), 3)  # 2000 + 2000 + 500
        self.assertEqual([c.order_index for c in chunks], [0, 1, 2])

    def test_inline_marker_not_matched(self):
        # 正文里出现「这一章」不应被当标题切块
        text = "第一章 开始\n他说这一章的教训很深刻，第二章内容也提到过。"
        chunks = TemplateChunker().chunk(text)
        self.assertEqual(len(chunks), 1)

    def test_overlong_title_line_treated_as_body(self):
        long_tail = "关于修炼的长篇大论" * 5  # >30 字
        text = f"第一章 {long_tail}\n正文。"
        chunks = TemplateChunker().chunk(text)
        # 标题过长 → 整行当正文，不产生独立标题块（回退滑窗，1 块）
        self.assertEqual(len(chunks), 1)

    def test_prologue_and_epilogue_ordering(self):
        text = ("楔子\n开篇引子。\n"
                "第一章 正传\n正文。\n"
                "尾声\n收束。")
        chunks = TemplateChunker().chunk(text)
        # 楔子排最前，尾声排最后
        self.assertTrue(chunks[0].text.startswith("开篇引子") or "引子" in chunks[0].text)
        self.assertIn("收束", chunks[-1].text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_chunker -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'TemplateChunker'`

- [ ] **Step 3: 写实现**

`StoryTemplate/TemplateChunker.py`：

```python
from __future__ import annotations

import re
from dataclasses import dataclass

"""长文切块：识别中文卷/章/节/回标记，产出带 order_index 的 Chunk。

分层：卷/部/篇/集=大层（order 高位）；章/节/回/折=小层。以最细可用层切块；
完全无标记回退 ~chunk_size 字滑窗。楔子/序排最前，尾声/番外排最后。
只在行首独立匹配 + 标题长度上限，防正文误命中。
"""

_BIG = "卷部篇集"
_SMALL = "章节回折"
_NUM = "[0-9]+|[一二三四五六七八九十百千零两]+"
_LINE = re.compile(
    rf"^\s*第?\s*({_NUM})\s*([{_BIG}{_SMALL}])\s*([:：、.\-—]?\s*(.*))?$"
)
_PROLOGUE = re.compile(r"^\s*(楔子|序|序章|序言)\s*$")
_EPILOGUE = re.compile(r"^\s*(尾声|番外|后记|终章)\s*$")
_TITLE_MAX = 30

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    order_index: int
    text: str
    title: str


def _parse_number(raw: str) -> int | None:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    total, section, number = 0, 0, 0
    for ch in raw:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            section += (number or 1) * unit
            number = 0
        else:
            return None
    result = section + number
    return result or None


@dataclass
class _Marker:
    is_big: bool
    number: int | None
    title: str
    line_index: int


class TemplateChunker:
    def __init__(self, chunk_size: int = 2000) -> None:
        self._chunk_size = max(1, int(chunk_size))

    def chunk(self, text: str) -> list[Chunk]:
        lines = text.splitlines()
        markers = self._scan_markers(lines)
        has_small = any(not m.is_big for m in markers)
        # 仅有大层时按大层切；有小层则忽略大层作为切点（大层号并入复合排序）。
        cut_markers = [m for m in markers if (not m.is_big) or (not has_small)]
        prologue, epilogue = self._scan_special(lines)
        if not cut_markers and not prologue and not epilogue:
            return self._sliding_window(text)
        return self._cut_by_markers(lines, cut_markers, markers, prologue, epilogue)

    def _scan_markers(self, lines: list[str]) -> list[_Marker]:
        out: list[_Marker] = []
        for i, line in enumerate(lines):
            m = _LINE.match(line)
            if not m:
                continue
            title = (m.group(4) or "").strip()
            if len(line.strip()) > _TITLE_MAX and title:
                continue  # 标题行过长视为正文
            marker_word = m.group(2)
            out.append(_Marker(
                is_big=marker_word in _BIG,
                number=_parse_number(m.group(1)),
                title=title,
                line_index=i,
            ))
        return out

    def _scan_special(self, lines: list[str]) -> tuple[int | None, int | None]:
        prologue = epilogue = None
        for i, line in enumerate(lines):
            if prologue is None and _PROLOGUE.match(line):
                prologue = i
            if _EPILOGUE.match(line):
                epilogue = i
        return prologue, epilogue

    def _sliding_window(self, text: str) -> list[Chunk]:
        body = text.strip()
        chunks: list[Chunk] = []
        for idx, start in enumerate(range(0, len(body), self._chunk_size)):
            piece = body[start:start + self._chunk_size]
            chunks.append(Chunk(chunk_id=f"win_{idx}", order_index=idx, text=piece, title=""))
        return chunks or [Chunk(chunk_id="win_0", order_index=0, text=body, title="")]

    def _cut_by_markers(
        self, lines, cut_markers, all_markers, prologue, epilogue,
    ) -> list[Chunk]:
        # 复合排序键：(卷号, 章号)。卷号取该切点之前最近的大层号。
        big_before: list[int] = []
        cur_big = 0
        big_by_line = {m.line_index: (m.number or 0) for m in all_markers if m.is_big}
        for m in cut_markers:
            for ln in range(0, m.line_index + 1):
                if ln in big_by_line:
                    cur_big = big_by_line[ln]
            big_before.append(cur_big)

        # 用切点行号把正文切段。
        cut_lines = [m.line_index for m in cut_markers]
        segments: list[tuple[int, str, str]] = []  # (sort_key_tuple 占位, title, text)
        entries: list[tuple[tuple[int, int, int], str, str]] = []
        for idx, m in enumerate(cut_markers):
            start = m.line_index + 1
            end = cut_lines[idx + 1] if idx + 1 < len(cut_lines) else len(lines)
            text = "\n".join(lines[start:end]).strip()
            sort_key = (0, big_before[idx], m.number if m.number is not None else idx)
            entries.append((sort_key, m.title, text))

        # 楔子/序 → 最前（key 首位 -1）；尾声/番外 → 最后（key 首位 1）。
        if prologue is not None:
            end = cut_lines[0] if cut_lines else len(lines)
            entries.append(((-1, 0, 0), "楔子", "\n".join(lines[prologue + 1:end]).strip()))
        if epilogue is not None:
            entries.append(((1, 0, 0), "尾声", "\n".join(lines[epilogue + 1:]).strip()))

        entries.sort(key=lambda e: e[0])
        chunks: list[Chunk] = []
        for order, (_, title, text) in enumerate(entries):
            chunks.append(Chunk(chunk_id=f"ch_{order}", order_index=order, text=text, title=title))
        return chunks
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_chunker -v`
Expected: PASS（8 tests）。若排序/边界个别红，仅调 `_cut_by_markers` 的 key 计算，勿改契约。

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/TemplateChunker.py tests/test_template_chunker.py
git commit -m "feat(story-template): 卷章节回切块 + 复合 order_index + 边界防护"
```

---

## Task 3: TemplateClustering —— 纯向量事件筛选 / 桥段去重 / 角色合并

**Files:**
- Create: `StoryTemplate/TemplateClustering.py`
- Test: `tests/test_template_clustering.py`

**契约：** `TemplateClustering(embedding: EmbeddingModel, *, dedup_threshold: float = 0.6, merge_threshold: float = 0.82)`。方法：
- `embed(texts: list[str]) -> list[list[float]]`（转调注入的 embedding）。
- `dedup_beats(beat_texts: list[str]) -> list[list[int]]`：返回簇（每簇是原索引列表），相似度 ≥ dedup_threshold 归一簇。
- `merge_characters(names: list[str], vectors: list[list[float]]) -> list[list[int]]`：同名**或**向量相似度 ≥ merge_threshold 归并；返回索引簇。

（事件块筛选逻辑放在 ExtractAgent 消费 `is_event` 信号，Clustering 只提供相似度原语；不在本任务实现独立 `filter_event_blocks`，YAGNI。）

- [ ] **Step 1: 写失败测试**（真 bge，极短文本）

```python
from __future__ import annotations

import unittest

from embedding import BgeEmbeddingModel
from StoryTemplate.TemplateClustering import TemplateClustering


class ClusteringRealBgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clustering = TemplateClustering(BgeEmbeddingModel())

    def test_embed_returns_512_dim(self):
        vecs = self.clustering.embed(["拜师学艺", "夺宝奇遇"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 512)

    def test_dedup_groups_similar_beats(self):
        beats = ["他拜入宗门成为弟子", "少年正式拜师入门修行", "两人在擂台上激烈交手"]
        clusters = self.clustering.dedup_beats(beats)
        # 前两条语义近 → 同簇；第三条独立。共 2 簇。
        self.assertEqual(len(clusters), 2)
        sizes = sorted(len(c) for c in clusters)
        self.assertEqual(sizes, [1, 2])

    def test_merge_characters_by_name_or_vector(self):
        names = ["张三", "张三", "李四"]
        vecs = self.clustering.embed([
            "第三章的张三行侠仗义", "第八十章的张三行侠仗义", "李四阴险狡诈",
        ])
        clusters = self.clustering.merge_characters(names, vecs)
        self.assertEqual(len(clusters), 2)  # 两个张三合一，李四独立


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_clustering -v`
Expected: FAIL — `ImportError: cannot import name 'TemplateClustering'`

- [ ] **Step 3: 写实现**

`StoryTemplate/TemplateClustering.py`：

```python
from __future__ import annotations

import math
from typing import Sequence

from embedding import EmbeddingModel

"""纯向量算法层：不调 LLM，只用注入的 embedding 做相似度聚类。

- dedup_beats：桥段片段两两余弦，≥ dedup_threshold 并查集归簇（去重）。
- merge_characters：同名或向量 ≥ merge_threshold 归并（避免同角色跨章割裂）。
bge 已归一化，余弦相似度 = 点积。
"""


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self) -> list[list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            groups.setdefault(self.find(i), []).append(i)
        return list(groups.values())


class TemplateClustering:
    def __init__(
        self,
        embedding: EmbeddingModel,
        *,
        dedup_threshold: float = 0.6,
        merge_threshold: float = 0.82,
    ) -> None:
        self._embedding = embedding
        self._dedup_threshold = dedup_threshold
        self._merge_threshold = merge_threshold

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embedding.encode(texts)

    def _cluster_by_vectors(self, vectors, threshold, extra_same=None) -> list[list[int]]:
        n = len(vectors)
        uf = _UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                same = _cosine(vectors[i], vectors[j]) >= threshold
                if extra_same is not None and extra_same(i, j):
                    same = True
                if same:
                    uf.union(i, j)
        return uf.clusters()

    def dedup_beats(self, beat_texts: list[str]) -> list[list[int]]:
        if not beat_texts:
            return []
        vectors = self.embed(beat_texts)
        return self._cluster_by_vectors(vectors, self._dedup_threshold)

    def merge_characters(self, names: list[str], vectors: list[list[float]]) -> list[list[int]]:
        if not names:
            return []
        return self._cluster_by_vectors(
            vectors, self._merge_threshold,
            extra_same=lambda i, j: names[i].strip() == names[j].strip() and bool(names[i].strip()),
        )
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_clustering -v`
Expected: PASS（3 tests）。真 bge 对超短桥段文本的语义相似度偏低（实测「拜入宗门」↔「拜师入门」仅 ~0.66，与不相关桥段 ~0.42 分离清晰），故 `dedup_threshold` 默认取 0.6（落在 0.42/0.66 干净间隔中点，两侧都稳）。若簇数不符，仅微调 `dedup_threshold` 默认值——改阈值默认值即可，勿改算法、勿改契约签名。

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/TemplateClustering.py tests/test_template_clustering.py
git commit -m "feat(story-template): 向量聚类原语——桥段去重 + 角色同名/相似度合并"
```

---

## Task 4: TemplateExtractAgent —— Level1 逐块信号 + Level3 四类归并

**Files:**
- Create: `StoryTemplate/TemplateExtractAgent.py`
- Test: `tests/test_template_extract_agent.py`

**契约（继承 `BaseAgent`）：**
- `map_chunks(chunks: list[Chunk]) -> list[ChunkSignal]`：逐块串行调 LLM，产出 `ChunkSignal`（带 `chunk_id`/`order_index` 透传）。
- `reduce_style(signals: list[ChunkSignal]) -> StyleBible`
- `reduce_characters(name_clusters: list[list[str]], behaviors: list[str]) -> list[CharacterArchetype]`（入参为已合并的角色簇名 + 行为样本）
- `reduce_beats(beat_summaries: list[str]) -> list[PlotBeat]`（入参为去重后代表桥段文本；给 `beat_id`）
- `reduce_skeleton(event_signals: list[ChunkSignal]) -> list[PlotSkeletonNode]`（按 order_index 排序后产出，给 `node_id`/`order_index`）

测试注入 **fake client**：一个返回预置 JSON 的对象，模拟 `client.chat.completions.create(...).choices[0].message.content`。参照 `BaseAgent.command` 的调用路径。

- [ ] **Step 1: 写失败测试**（fake LLM，离线秒级）

```python
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from StoryTemplate.TemplateChunker import Chunk
from StoryTemplate.TemplateExtractAgent import TemplateExtractAgent


class _FakeClient:
    """按调用序返回预置 JSON 内容，模拟 OpenAI client。"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self._i = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        payload = self._payloads[min(self._i, len(self._payloads) - 1)]
        self._i += 1
        msg = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _agent(payloads):
    return TemplateExtractAgent(client=_FakeClient(payloads), model="fake", base_url="http://x", api_key="k")


class MapChunksTests(unittest.TestCase):
    def test_map_chunks_transfers_order_and_flags(self):
        signal = {
            "style_tone_tags": ["古雅"], "style_devices": ["白描"],
            "characters": [{"name": "甲", "behavior": "拔剑"}],
            "is_event": True, "event_summary": "甲遇袭",
        }
        agent = _agent([signal, signal])
        chunks = [
            Chunk(chunk_id="ch_0", order_index=0, text="甲遇袭。", title="一"),
            Chunk(chunk_id="ch_1", order_index=1, text="乙旁观。", title="二"),
        ]
        signals = agent.map_chunks(chunks)
        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0]["chunk_id"], "ch_0")
        self.assertEqual(signals[1]["order_index"], 1)
        self.assertTrue(signals[0]["is_event"])


class ReduceTests(unittest.TestCase):
    def test_reduce_style_returns_style_bible(self):
        sb = {
            "narrative_voice": "第三人称", "tone_tags": ["古雅"], "prose_rhythm": "长句",
            "signature_devices": ["白描"], "world_premise": "江湖", "cultivation_system": "无",
            "factions": ["天地会"], "key_locations": ["扬州"], "world_rules": [], "lexicon": [],
        }
        agent = _agent([sb])
        result = agent.reduce_style([])
        self.assertEqual(result["narrative_voice"], "第三人称")
        self.assertEqual(result["factions"], ["天地会"])

    def test_reduce_beats_assigns_beat_ids(self):
        agent = _agent([{"beats": [
            {"label": "拜师", "tags": ["成长"], "summary": "弟子拜入门派",
             "dramatic_function": "铺垫", "reusable_conflict": "身份认同"},
        ]}])
        beats = agent.reduce_beats(["某人拜入宗门"])
        self.assertEqual(len(beats), 1)
        self.assertTrue(beats[0]["beat_id"])
        self.assertEqual(beats[0]["label"], "拜师")

    def test_reduce_skeleton_sorts_and_ids(self):
        agent = _agent([{"nodes": [
            {"title": "开端", "event_summary": "起", "preconditions": [], "maps_to_chapter_hint": "1"},
            {"title": "发展", "event_summary": "承", "preconditions": ["开端"], "maps_to_chapter_hint": "2"},
        ]}])
        # 事件信号乱序传入，验证按 order_index 排
        from StoryTemplate.TemplateChunker import Chunk  # noqa
        sig = lambda oi, s: {"chunk_id": f"c{oi}", "order_index": oi, "style_tone_tags": [],
                             "style_devices": [], "characters": [], "is_event": True, "event_summary": s}
        nodes = agent.reduce_skeleton([sig(2, "承"), sig(1, "起")])
        self.assertEqual([n["order_index"] for n in nodes], [0, 1])
        self.assertTrue(all(n["node_id"] for n in nodes))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_extract_agent -v`
Expected: FAIL — `ImportError: cannot import name 'TemplateExtractAgent'`

- [ ] **Step 3: 写实现**

`StoryTemplate/TemplateExtractAgent.py`：

```python
from __future__ import annotations

import uuid
from typing import Any

from BaseAgent import BaseAgent
from PromptUtils import render_json_instruction
from StoryTemplate.TemplateChunker import Chunk
from StoryTemplate.TemplateSchema import (
    CharacterArchetype, ChunkSignal, PlotBeat, PlotSkeletonNode, StyleBible,
    empty_style_bible,
    CHARACTER_ARCHETYPE_RESPONSE_SCHEMA, CHUNK_SIGNAL_RESPONSE_SCHEMA,
    PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
    STYLE_BIBLE_RESPONSE_SCHEMA,
)

"""分层归并提取：Level1 逐块信号（真 LLM，串行）+ Level3 四类全局归并。

继承 BaseAgent 复用 JSON 模式与截断修复。第一版串行；map_chunks 签名预留
「块列表 → 信号列表」，后续换并行不动调用方。归并入参已由 Service 侧用
Clustering 预处理（去重/合并），本层只负责「文字 → 结构化」的 LLM 提炼。
"""

EXTRACT_SYSTEM_PROMPT = """
你是小说模板提取助手。从给定中文小说片段中提炼结构化信息，只返回严格 JSON。
不要照抄原文长句；风格标签要抽象概括；桥段概要去掉专有名词只留冲突结构。
"""


class TemplateExtractAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("system_prompt", EXTRACT_SYSTEM_PROMPT)
        kwargs.setdefault("temperature", 0.4)
        super().__init__(**kwargs)

    def map_chunks(self, chunks: list[Chunk]) -> list[ChunkSignal]:
        signals: list[ChunkSignal] = []
        for chunk in chunks:
            raw = self.command(
                instruction=render_json_instruction(
                    "提炼此片段的风格标签、手法、出场角色及行为，判断是否含关键情节事件：",
                    {"chunk_text": chunk.text[:3000]},
                ),
                response_format=CHUNK_SIGNAL_RESPONSE_SCHEMA,
            )
            signals.append({
                "chunk_id": chunk.chunk_id,
                "order_index": chunk.order_index,
                "style_tone_tags": list(raw.get("style_tone_tags", [])),
                "style_devices": list(raw.get("style_devices", [])),
                "characters": list(raw.get("characters", [])),
                "is_event": bool(raw.get("is_event", False)),
                "event_summary": str(raw.get("event_summary", "") or ""),
            })
        return signals

    def reduce_style(self, signals: list[ChunkSignal]) -> StyleBible:
        tone_votes = [t for s in signals for t in s.get("style_tone_tags", [])]
        device_votes = [d for s in signals for d in s.get("style_devices", [])]
        raw = self.command(
            instruction=render_json_instruction(
                "综合以下各章风格投票与世界观线索，产出统一的风格圣经与世界观设定：",
                {"tone_votes": tone_votes, "device_votes": device_votes},
            ),
            response_format=STYLE_BIBLE_RESPONSE_SCHEMA,
        )
        result = empty_style_bible()
        for key in result:
            if key in raw:
                result[key] = raw[key]  # type: ignore[literal-required]
        return result

    def reduce_characters(
        self, name_clusters: list[list[str]], behaviors: list[str],
    ) -> list[CharacterArchetype]:
        raw = self.command(
            instruction=render_json_instruction(
                "把以下角色簇（同一角色的多个名字样本）与行为样本归并成角色原型：",
                {"name_clusters": name_clusters, "behavior_samples": behaviors},
            ),
            response_format=CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
        )
        return [self._as_character(c) for c in raw.get("characters", [])]

    def reduce_beats(self, beat_summaries: list[str]) -> list[PlotBeat]:
        raw = self.command(
            instruction=render_json_instruction(
                "把以下去重后的桥段片段抽象成可复用的情节桥段（去专有名词，只留冲突结构）：",
                {"beat_samples": beat_summaries},
            ),
            response_format=PLOT_BEAT_RESPONSE_SCHEMA,
        )
        beats: list[PlotBeat] = []
        for b in raw.get("beats", []):
            beats.append({
                "beat_id": uuid.uuid4().hex[:12],
                "label": str(b.get("label", "") or ""),
                "tags": list(b.get("tags", [])),
                "summary": str(b.get("summary", "") or ""),
                "dramatic_function": str(b.get("dramatic_function", "") or ""),
                "reusable_conflict": str(b.get("reusable_conflict", "") or ""),
            })
        return beats

    def reduce_skeleton(self, event_signals: list[ChunkSignal]) -> list[PlotSkeletonNode]:
        ordered = sorted(event_signals, key=lambda s: s.get("order_index", 0))
        raw = self.command(
            instruction=render_json_instruction(
                "把以下按顺序排列的关键事件归并成主线骨架节点（A→B→C）：",
                {"events": [s.get("event_summary", "") for s in ordered]},
            ),
            response_format=PLOT_SKELETON_RESPONSE_SCHEMA,
        )
        nodes: list[PlotSkeletonNode] = []
        for idx, n in enumerate(raw.get("nodes", [])):
            nodes.append({
                "node_id": uuid.uuid4().hex[:12],
                "order_index": idx,
                "title": str(n.get("title", "") or ""),
                "event_summary": str(n.get("event_summary", "") or ""),
                "preconditions": list(n.get("preconditions", [])),
                "maps_to_chapter_hint": str(n.get("maps_to_chapter_hint", "") or ""),
            })
        return nodes

    @staticmethod
    def _as_character(c: dict[str, Any]) -> CharacterArchetype:
        return {
            "name": str(c.get("name", "") or ""),
            "role_summary": str(c.get("role_summary", "") or ""),
            "persona": list(c.get("persona", [])),
            "speech_style": str(c.get("speech_style", "") or ""),
            "secrets": list(c.get("secrets", [])),
            "signature_relations": list(c.get("signature_relations", [])),
            "suggested_layer": str(c.get("suggested_layer", "") or ""),
        }
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_extract_agent -v`
Expected: PASS（4 tests）

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/TemplateExtractAgent.py tests/test_template_extract_agent.py
git commit -m "feat(story-template): 提取 agent —— 逐块信号 + 四类全局归并"
```

---

## Task 5: TemplateRepository —— MySQL 4 分表持久化

**Files:**
- Create: `StoryTemplate/TemplateRepository.py`
- Test: `tests/test_template_repository.py`

**契约：** 子包自持 SQLAlchemy `MetaData` + 4 张 `Table`（不复用 `Persistence.Models.Base`，避免建到别人的表）。`TemplateRepository(database: db.Database)`。方法：
- `create_all()` → `self._database.create_all(self._metadata)`。
- `save_template(*, user_id=0, source_title, style_bible, characters, beats, skeleton) -> int`：插 `story_template` 拿自增 `template_id`，再写 4 从表；返回 `template_id`。（`user_id` 可选默认 0=平台，只存不过滤；无 player_id）
- `get_style_bible(template_id) -> StyleBible`
- `get_beats(template_id) -> list[PlotBeat]`
- `get_skeleton(template_id) -> list[PlotSkeletonNode]`（按 order_index 升序）
- `get_characters(template_id) -> list[CharacterArchetype]`

列表字段统一 `json.dumps(ensure_ascii=False)` 存 `Text`，读回 `json.loads`。

- [ ] **Step 1: 写失败测试**（真 MySQL）

```python
from __future__ import annotations

import os
import unittest

from db import Database
from StoryTemplate.TemplateRepository import TemplateRepository
from StoryTemplate.TemplateSchema import empty_style_bible


def _mysql_url() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    return os.environ["MYSQL_URL"]


class RepositoryRealMysqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = TemplateRepository(Database(_mysql_url()))
        cls.repo.create_all()

    def _sample(self):
        sb = empty_style_bible()
        sb["narrative_voice"] = "第三人称"
        sb["tone_tags"] = ["古雅", "诙谐"]
        sb["factions"] = ["天地会"]
        chars = [{
            "name": "韦小宝", "role_summary": "市井混混", "persona": ["机灵", "圆滑"],
            "speech_style": "俚俗", "secrets": ["身世成谜"],
            "signature_relations": ["亦友亦敌"], "suggested_layer": "player",
        }]
        beats = [{
            "beat_id": "b1", "label": "拜师", "tags": ["成长"], "summary": "弟子拜门",
            "dramatic_function": "铺垫", "reusable_conflict": "身份认同",
        }]
        skeleton = [
            {"node_id": "n2", "order_index": 1, "title": "发展", "event_summary": "承",
             "preconditions": ["开端"], "maps_to_chapter_hint": "2"},
            {"node_id": "n1", "order_index": 0, "title": "开端", "event_summary": "起",
             "preconditions": [], "maps_to_chapter_hint": "1"},
        ]
        return sb, chars, beats, skeleton

    def test_save_and_read_back_roundtrip(self):
        sb, chars, beats, skeleton = self._sample()
        tid = self.repo.save_template(
            user_id=1, source_title="鹿鼎记测试",
            style_bible=sb, characters=chars, beats=beats, skeleton=skeleton,
        )
        self.assertIsInstance(tid, int)

        got_sb = self.repo.get_style_bible(tid)
        self.assertEqual(got_sb["narrative_voice"], "第三人称")
        self.assertEqual(got_sb["tone_tags"], ["古雅", "诙谐"])

        got_chars = self.repo.get_characters(tid)
        self.assertEqual(got_chars[0]["name"], "韦小宝")
        self.assertEqual(got_chars[0]["persona"], ["机灵", "圆滑"])

        got_beats = self.repo.get_beats(tid)
        self.assertEqual(got_beats[0]["label"], "拜师")

        got_skel = self.repo.get_skeleton(tid)
        # 按 order_index 升序读回
        self.assertEqual([n["order_index"] for n in got_skel], [0, 1])
        self.assertEqual(got_skel[0]["title"], "开端")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_repository -v`
Expected: FAIL — `ImportError: cannot import name 'TemplateRepository'`

- [ ] **Step 3: 写实现**

`StoryTemplate/TemplateRepository.py`：

```python
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text,
    insert, select,
)

from db import Database
from StoryTemplate.TemplateSchema import (
    CharacterArchetype, PlotBeat, PlotSkeletonNode, StyleBible, empty_style_bible,
)

"""4 张 MySQL 分表持久化，注入 db.Database（自持 MetaData，不污染他表）。

列表字段统一 JSON 文本编码存 Text 列（MySQL 5.7+ 无原生数组），读回解码。
主表 story_template 自增 template_id 作各从表外键。
"""

_META = MetaData()

story_template = Table(
    "story_template", _META,
    Column("template_id", BigInteger().with_variant(Integer, "sqlite"),
           primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, default=0),
    Column("source_title", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

template_style_bible = Table(
    "template_style_bible", _META,
    Column("template_id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("narrative_voice", Text, nullable=False),
    Column("tone_tags", Text, nullable=False),
    Column("prose_rhythm", Text, nullable=False),
    Column("signature_devices", Text, nullable=False),
    Column("world_premise", Text, nullable=False),
    Column("cultivation_system", Text, nullable=False),
    Column("factions", Text, nullable=False),
    Column("key_locations", Text, nullable=False),
    Column("world_rules", Text, nullable=False),
    Column("lexicon", Text, nullable=False),
)

template_character = Table(
    "template_character", _META,
    Column("id", BigInteger().with_variant(Integer, "sqlite"),
           primary_key=True, autoincrement=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("name", String(128), nullable=False),
    Column("role_summary", Text, nullable=False),
    Column("persona", Text, nullable=False),
    Column("speech_style", Text, nullable=False),
    Column("secrets", Text, nullable=False),
    Column("signature_relations", Text, nullable=False),
    Column("suggested_layer", String(32), nullable=False),
)

template_plot_beat = Table(
    "template_plot_beat", _META,
    Column("beat_id", String(32), primary_key=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("label", String(128), nullable=False),
    Column("tags", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("dramatic_function", String(128), nullable=False),
    Column("reusable_conflict", Text, nullable=False),
)

template_plot_skeleton = Table(
    "template_plot_skeleton", _META,
    Column("node_id", String(32), primary_key=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("order_index", Integer, nullable=False),
    Column("title", String(255), nullable=False),
    Column("event_summary", Text, nullable=False),
    Column("preconditions", Text, nullable=False),
    Column("maps_to_chapter_hint", String(128), nullable=False),
)


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class TemplateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._metadata = _META

    def create_all(self) -> None:
        self._database.create_all(self._metadata)

    def save_template(
        self, *, user_id: int = 0, source_title: str,
        style_bible: StyleBible, characters: list[CharacterArchetype],
        beats: list[PlotBeat], skeleton: list[PlotSkeletonNode],
    ) -> int:
        with self._database.session() as db:
            result = db.execute(insert(story_template).values(
                user_id=user_id, source_title=source_title,
                created_at=datetime.now(timezone.utc),
            ))
            template_id = int(result.inserted_primary_key[0])

            db.execute(insert(template_style_bible).values(
                template_id=template_id,
                narrative_voice=style_bible["narrative_voice"],
                tone_tags=_dumps(style_bible["tone_tags"]),
                prose_rhythm=style_bible["prose_rhythm"],
                signature_devices=_dumps(style_bible["signature_devices"]),
                world_premise=style_bible["world_premise"],
                cultivation_system=style_bible["cultivation_system"],
                factions=_dumps(style_bible["factions"]),
                key_locations=_dumps(style_bible["key_locations"]),
                world_rules=_dumps(style_bible["world_rules"]),
                lexicon=_dumps(style_bible["lexicon"]),
            ))
            for c in characters:
                db.execute(insert(template_character).values(
                    template_id=template_id, name=c["name"],
                    role_summary=c["role_summary"], persona=_dumps(c["persona"]),
                    speech_style=c["speech_style"], secrets=_dumps(c["secrets"]),
                    signature_relations=_dumps(c["signature_relations"]),
                    suggested_layer=c["suggested_layer"],
                ))
            for b in beats:
                db.execute(insert(template_plot_beat).values(
                    beat_id=b["beat_id"], template_id=template_id, label=b["label"],
                    tags=_dumps(b["tags"]), summary=b["summary"],
                    dramatic_function=b["dramatic_function"],
                    reusable_conflict=b["reusable_conflict"],
                ))
            for n in skeleton:
                db.execute(insert(template_plot_skeleton).values(
                    node_id=n["node_id"], template_id=template_id,
                    order_index=n["order_index"], title=n["title"],
                    event_summary=n["event_summary"],
                    preconditions=_dumps(n["preconditions"]),
                    maps_to_chapter_hint=n["maps_to_chapter_hint"],
                ))
            db.commit()
            return template_id

    def get_style_bible(self, template_id: int) -> StyleBible:
        with self._database.session() as db:
            row = db.execute(select(template_style_bible).where(
                template_style_bible.c.template_id == template_id
            )).mappings().first()
        if row is None:
            return empty_style_bible()
        return {
            "narrative_voice": row["narrative_voice"],
            "tone_tags": json.loads(row["tone_tags"]),
            "prose_rhythm": row["prose_rhythm"],
            "signature_devices": json.loads(row["signature_devices"]),
            "world_premise": row["world_premise"],
            "cultivation_system": row["cultivation_system"],
            "factions": json.loads(row["factions"]),
            "key_locations": json.loads(row["key_locations"]),
            "world_rules": json.loads(row["world_rules"]),
            "lexicon": json.loads(row["lexicon"]),
        }

    def get_characters(self, template_id: int) -> list[CharacterArchetype]:
        with self._database.session() as db:
            rows = db.execute(select(template_character).where(
                template_character.c.template_id == template_id
            )).mappings().all()
        return [{
            "name": r["name"], "role_summary": r["role_summary"],
            "persona": json.loads(r["persona"]), "speech_style": r["speech_style"],
            "secrets": json.loads(r["secrets"]),
            "signature_relations": json.loads(r["signature_relations"]),
            "suggested_layer": r["suggested_layer"],
        } for r in rows]

    def get_beats(self, template_id: int) -> list[PlotBeat]:
        with self._database.session() as db:
            rows = db.execute(select(template_plot_beat).where(
                template_plot_beat.c.template_id == template_id
            )).mappings().all()
        return [{
            "beat_id": r["beat_id"], "label": r["label"], "tags": json.loads(r["tags"]),
            "summary": r["summary"], "dramatic_function": r["dramatic_function"],
            "reusable_conflict": r["reusable_conflict"],
        } for r in rows]

    def get_skeleton(self, template_id: int) -> list[PlotSkeletonNode]:
        with self._database.session() as db:
            rows = db.execute(select(template_plot_skeleton).where(
                template_plot_skeleton.c.template_id == template_id
            ).order_by(template_plot_skeleton.c.order_index)).mappings().all()
        return [{
            "node_id": r["node_id"], "order_index": r["order_index"], "title": r["title"],
            "event_summary": r["event_summary"],
            "preconditions": json.loads(r["preconditions"]),
            "maps_to_chapter_hint": r["maps_to_chapter_hint"],
        } for r in rows]
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_repository -v`
Expected: PASS（1 test）。若报表已存在冲突，无害（create_all 幂等）。

- [ ] **Step 5: 提交**

```bash
git add StoryTemplate/TemplateRepository.py tests/test_template_repository.py
git commit -m "feat(story-template): MySQL 4 分表持久化 + JSON 列表编码往返"
```

---

## Task 6: StoryTemplateService + factory —— 对外 Facade 与装配

**Files:**
- Create: `StoryTemplate/StoryTemplateService.py`
- Create: `StoryTemplate/factory.py`
- Test: `tests/test_template_service.py`

**契约：**
```python
class StoryTemplateService:
    def __init__(self, *, chunker, extract_agent, clustering, repository,
                 vector_store, embedding): ...
    def import_novel(self, *, source_title, text, user_id=0) -> int: ...
    def get_style_bible(self, template_id) -> StyleBible: ...
    def suggest_plot_beats(self, template_id, *, query, top_k=5) -> list[PlotBeat]: ...
    def next_skeleton_nodes(self, template_id, *, chapter_hint) -> list[PlotSkeletonNode]: ...
    def search_style_passages(self, template_id, *, query, top_k=5) -> list[str]: ...
```

`import_novel` 编排：切块 → `embedding.encode` 全块 → `extract_agent.map_chunks` → 用 `clustering` 对桥段去重 / 角色合并 → `extract_agent.reduce_*` 四类归并 → `repository.save_template` 拿 `template_id` → 原文片段（每块）转 `VectorDoc`（`doc_id = template_scope_prefix(tid)+chunk_id`，`doc_type="style_passage"`，metadata 带 `template_id/order_index`）+ 向量 `upsert`。返回 `template_id`。（`user_id` 可选默认 0，仅透传给 `save_template` 存库作归属，不进向量前缀、不参与检索过滤。）

- `search_style_passages`：`embedding.encode([query])[0]` → `vector_store.search(vec, top_k, filters={"template_id": str(tid), "doc_type": "style_passage"})` → 取 `.doc.text`。
- `suggest_plot_beats`：读 `repository.get_beats(tid)`，按 `query` 子串命中 `label/tags/summary` 过滤（无命中返回全部前 top_k）——纯结构化检索，不走向量。
- `next_skeleton_nodes`：读 `repository.get_skeleton(tid)`，返回 `maps_to_chapter_hint == chapter_hint` 的节点；无则返回 order 最小的未匹配节点前若干。

`factory.build_story_template_service(*, mysql_url, pg_url, client=None)` 延迟构造：`BgeEmbeddingModel` / `PgVectorStore(pg_url)` / `TemplateRepository(Database(mysql_url))`（并 `create_all`）/ `TemplateExtractAgent(client=client)` / `TemplateChunker` / `TemplateClustering`。（Service 不再需要 user/player 租户；模板全局共享，只按 template_id 隔离。）

- [ ] **Step 1: 写失败测试**（fake LLM + 真 MySQL + 真 pgvector 端到端）

```python
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace

from dotenv import load_dotenv

from StoryTemplate.factory import build_story_template_service


class _ScriptedClient:
    """按 response schema 名路由返回:map 阶段回 chunk_signal,reduce 回各自结构。"""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        schema = kwargs.get("response_format", {})
        name = ""
        if isinstance(schema, dict):
            name = schema.get("json_schema", {}).get("name", "")
        payload = self._route(name)
        msg = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    def _route(self, name):
        if name == "chunk_signal":
            return {"style_tone_tags": ["古雅"], "style_devices": ["白描"],
                    "characters": [{"name": "韦小宝", "behavior": "耍滑"}],
                    "is_event": True, "event_summary": "韦小宝闯宫"}
        if name == "style_bible":
            return {"narrative_voice": "第三人称", "tone_tags": ["古雅", "诙谐"],
                    "prose_rhythm": "长短交错", "signature_devices": ["白描"],
                    "world_premise": "江湖庙堂", "cultivation_system": "无",
                    "factions": ["天地会"], "key_locations": ["皇宫"],
                    "world_rules": [], "lexicon": ["韦小宝"]}
        if name == "character_archetypes":
            return {"characters": [{"name": "韦小宝", "role_summary": "市井混混",
                    "persona": ["机灵"], "speech_style": "俚俗", "secrets": [],
                    "signature_relations": ["亦友亦敌"], "suggested_layer": "player"}]}
        if name == "plot_beats":
            return {"beats": [{"label": "闯宫", "tags": ["冒险", "宫廷"],
                    "summary": "小人物混入权力中心", "dramatic_function": "转折",
                    "reusable_conflict": "身份错位"}]}
        if name == "plot_skeleton":
            return {"nodes": [{"title": "入宫", "event_summary": "混入皇宫",
                    "preconditions": [], "maps_to_chapter_hint": "1"}]}
        return {}


def _urls():
    load_dotenv()
    return os.environ["MYSQL_URL"], os.environ["PG_URL"]


class ServiceEndToEndTests(unittest.TestCase):
    def test_import_and_retrieve(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        novel = ("第一回 初入皇宫\n韦小宝凭机灵混入皇宫，结识小玄子。\n"
                 "第二回 天地会\n韦小宝身陷天地会与朝廷之间。")
        tid = service.import_novel(
            source_title="鹿鼎记极短版", text=novel,
        )
        self.assertIsInstance(tid, int)

        sb = service.get_style_bible(tid)
        self.assertIn("古雅", sb["tone_tags"])
        self.assertEqual(sb["factions"], ["天地会"])

        beats = service.suggest_plot_beats(tid, query="宫廷", top_k=5)
        self.assertTrue(any("闯宫" == b["label"] for b in beats))

        nodes = service.next_skeleton_nodes(tid, chapter_hint="1")
        self.assertTrue(nodes)
        self.assertEqual(nodes[0]["title"], "入宫")

        passages = service.search_style_passages(tid, query="韦小宝混入皇宫", top_k=3)
        self.assertTrue(passages)
        self.assertTrue(any("皇宫" in p or "韦小宝" in p for p in passages))

    def test_tenant_isolation_on_passages(self):
        mysql_url, pg_url = _urls()
        service = build_story_template_service(
            mysql_url=mysql_url, pg_url=pg_url, client=_ScriptedClient(),
        )
        tid = service.import_novel(source_title="租户A",
                                   text="第一回 甲\n甲的独特往事内容。")
        # 用不存在的模板 id 检索 → 空（template_id 前缀隔离）
        empty = service.search_style_passages(tid + 999999, query="甲", top_k=3)
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认红**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_service -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'StoryTemplate.factory'`

- [ ] **Step 3: 写实现**

`StoryTemplate/StoryTemplateService.py`：

```python
from __future__ import annotations

from typing import Any

from datatypes import VectorDoc, template_scope_prefix
from StoryTemplate.TemplateSchema import (
    PlotBeat, PlotSkeletonNode, StyleBible,
)

"""对外 Facade：编排导入流水线 + 4 个检索接口。子模块只经本类使用。

模板全局共享（用户拍板）：user_id 仅透传存库作归属，不进向量前缀、不参与检索过滤；
向量片段按 template_id 隔离（前缀 tmpl:{tid}:）。
"""


class StoryTemplateService:
    def __init__(
        self, *, chunker, extract_agent, clustering, repository, vector_store, embedding,
    ) -> None:
        self._chunker = chunker
        self._extract = extract_agent
        self._clustering = clustering
        self._repo = repository
        self._vector_store = vector_store
        self._embedding = embedding

    def import_novel(self, *, source_title: str, text: str, user_id: int = 0) -> int:
        chunks = self._chunker.chunk(text)
        # Level1 逐块信号（真 LLM 串行）。
        signals = self._extract.map_chunks(chunks)

        # Level2 向量聚合：桥段去重 + 角色合并。
        event_signals = [s for s in signals if s.get("is_event")]
        beat_texts = [s["event_summary"] for s in event_signals if s.get("event_summary")]
        beat_clusters = self._clustering.dedup_beats(beat_texts) if beat_texts else []
        beat_reps = [beat_texts[c[0]] for c in beat_clusters]

        char_pairs = [(c.get("name", ""), c.get("behavior", ""))
                      for s in signals for c in s.get("characters", [])]
        names = [p[0] for p in char_pairs]
        behaviors = [p[1] for p in char_pairs]
        char_clusters: list[list[int]] = []
        if names:
            char_vecs = self._clustering.embed(
                [f"{n} {b}" for n, b in char_pairs]
            )
            char_clusters = self._clustering.merge_characters(names, char_vecs)
        name_clusters = [[names[i] for i in cluster] for cluster in char_clusters]

        # Level3 全局归并（四类各 1 次 LLM）。
        style_bible = self._extract.reduce_style(signals)
        characters = self._extract.reduce_characters(name_clusters, behaviors)
        beats = self._extract.reduce_beats(beat_reps)
        skeleton = self._extract.reduce_skeleton(event_signals)

        # 落 MySQL 4 表。
        template_id = self._repo.save_template(
            user_id=user_id, source_title=source_title,
            style_bible=style_bible, characters=characters, beats=beats, skeleton=skeleton,
        )

        # 原文片段入向量库（按 template_id 隔离，全局共享无 per-player 前缀）。
        prefix = template_scope_prefix(template_id)
        docs = [
            VectorDoc(
                doc_id=f"{prefix}{chunk.chunk_id}",
                doc_type="style_passage",
                text=chunk.text,
                metadata={
                    "template_id": template_id, "order_index": chunk.order_index,
                },
            )
            for chunk in chunks if chunk.text.strip()
        ]
        if docs:
            vectors = self._embedding.encode([d.text for d in docs])
            self._vector_store.upsert(list(zip(docs, vectors)))
        return template_id

    def get_style_bible(self, template_id: int) -> StyleBible:
        return self._repo.get_style_bible(template_id)

    def suggest_plot_beats(self, template_id: int, *, query: str, top_k: int = 5) -> list[PlotBeat]:
        beats = self._repo.get_beats(template_id)
        q = (query or "").strip()
        if not q:
            return beats[:top_k]
        hits = [b for b in beats
                if q in b["label"] or q in b["summary"] or any(q in t for t in b["tags"])]
        return (hits or beats)[:top_k]

    def next_skeleton_nodes(self, template_id: int, *, chapter_hint: str) -> list[PlotSkeletonNode]:
        nodes = self._repo.get_skeleton(template_id)
        matched = [n for n in nodes if n["maps_to_chapter_hint"] == chapter_hint]
        return matched or nodes[:1]

    def search_style_passages(self, template_id: int, *, query: str, top_k: int = 5) -> list[str]:
        vec = self._embedding.encode([query])[0]
        scored = self._vector_store.search(
            vec, top_k=top_k,
            filters={"template_id": str(template_id), "doc_type": "style_passage"},
        )
        return [s.doc.text for s in scored]
```

`StoryTemplate/factory.py`：

```python
from __future__ import annotations

from typing import Any

from db import Database
from embedding import BgeEmbeddingModel
from vectordb import PgVectorStore
from StoryTemplate.StoryTemplateService import StoryTemplateService
from StoryTemplate.TemplateChunker import TemplateChunker
from StoryTemplate.TemplateClustering import TemplateClustering
from StoryTemplate.TemplateExtractAgent import TemplateExtractAgent
from StoryTemplate.TemplateRepository import TemplateRepository

"""装配 StoryTemplateService，注入默认真实现（延迟构造，测试可传 fake client）。"""


def build_story_template_service(
    *, mysql_url: str, pg_url: str, client: Any | None = None,
) -> StoryTemplateService:
    embedding = BgeEmbeddingModel()
    vector_store = PgVectorStore(pg_url)
    repository = TemplateRepository(Database(mysql_url))
    repository.create_all()
    extract_agent = TemplateExtractAgent(client=client)
    return StoryTemplateService(
        chunker=TemplateChunker(),
        extract_agent=extract_agent,
        clustering=TemplateClustering(embedding),
        repository=repository,
        vector_store=vector_store,
        embedding=embedding,
    )
```

- [ ] **Step 4: 跑测试确认绿**

Run: `HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 -m unittest tests.test_template_service -v`
Expected: PASS（2 tests）

- [ ] **Step 5: 填 `__init__.py` 导出 + 提交**

`StoryTemplate/__init__.py`：

```python
from StoryTemplate.StoryTemplateService import StoryTemplateService
from StoryTemplate.TemplateSchema import (
    CharacterArchetype, PlotBeat, PlotSkeletonNode, StyleBible,
)

__all__ = [
    "StoryTemplateService", "StyleBible", "CharacterArchetype",
    "PlotBeat", "PlotSkeletonNode",
]
```

```bash
git add StoryTemplate/StoryTemplateService.py StoryTemplate/factory.py StoryTemplate/__init__.py tests/test_template_service.py
git commit -m "feat(story-template): Service Facade + factory 装配 + 端到端检索"
```

---

## Task 7: 通用小说模板提取脚本（手动触发，真 LLM；默认用鹿鼎记验证）

**Files:**
- Create: `scripts/extract_novel_template.py`
- Modify: `docs/foundation-requirements.md`（补 StoryTemplate 运行入口说明）

这是**通用手动验证脚本**（任意小说均可，`--path` 指定），不进日常单测（真 DeepSeek 调用、长文耗时）。用 `.env` 真实 LLM client（`build_story_template_service(client=None)` 会让 `TemplateExtractAgent` 自建真实 client）。为控制首轮成本，`--max-chunks N` 只提取前 N 块。默认 `--path docs/鹿鼎记.txt` 仅作示例语料，功能不绑定该书。

- [ ] **Step 1: 写脚本**

`scripts/extract_novel_template.py`：

```python
"""通用小说情节提取脚本:把任意中文小说跑通「切块→提炼→聚类→归并→入库」全链路。

模板是全局共享资产(user_id 仅作归属标记),换任意小说只需改 --path/--title。
默认用鹿鼎记.txt 作示例语料验证,功能不绑定该书。

用法:
  HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 \
    scripts/extract_novel_template.py --path docs/鹿鼎记.txt --title 鹿鼎记 --max-chunks 3
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_bootstrap import ensure_environment
from StoryTemplate.factory import build_story_template_service
from StoryTemplate.TemplateChunker import TemplateChunker


def main() -> int:
    parser = argparse.ArgumentParser(description="通用小说情节模板提取")
    parser.add_argument("--path", default="docs/鹿鼎记.txt",
                        help="小说文本路径(任意中文小说)")
    parser.add_argument("--title", default="",
                        help="模板来源标题;留空则用文件名")
    parser.add_argument("--user-id", type=int, default=0,
                        help="归属者 user_id(默认 0=平台/官方;只存不过滤)")
    parser.add_argument("--max-chunks", type=int, default=3,
                        help="只提取前 N 块以控制 LLM 成本/耗时;0 表示全文")
    args = parser.parse_args()

    ensure_environment(require_bge=True)  # LLM/MySQL/PG/bge 全需

    title = args.title or os.path.splitext(os.path.basename(args.path))[0]
    with open(args.path, encoding="utf-8") as f:
        text = f.read()
    print(f"[1] 读入 {args.path}: {len(text)} 字 (标题={title!r})")

    if args.max_chunks > 0:
        chunks = TemplateChunker().chunk(text)
        print(f"[2] 切块总数 {len(chunks)},仅取前 {args.max_chunks} 块提取")
        text = "\n".join(c.text for c in chunks[:args.max_chunks])

    service = build_story_template_service(
        mysql_url=os.environ["MYSQL_URL"], pg_url=os.environ["PG_URL"], client=None,
    )
    print("[3] 服务已装配 (真 bge + 真 pgvector + 真 MySQL + 真 DeepSeek),开始提取...")

    tid = service.import_novel(source_title=title, text=text, user_id=args.user_id)
    print(f"[4] 提取完成,template_id={tid}")

    sb = service.get_style_bible(tid)
    print(f"\n[风格圣经] 叙事视角={sb['narrative_voice']!r}")
    print(f"    语气标签={sb['tone_tags']}")
    print(f"    势力={sb['factions']}  地点={sb['key_locations']}")

    chars = service._repo.get_characters(tid)
    print(f"\n[角色原型] {len(chars)} 个:")
    for c in chars[:5]:
        print(f"    - {c['name']}({c['suggested_layer']}): {c['role_summary']}")

    beats = service.suggest_plot_beats(tid, query="", top_k=10)
    print(f"\n[情节桥段] {len(beats)} 条:")
    for b in beats[:5]:
        print(f"    - {b['label']} [{'/'.join(b['tags'])}]: {b['summary']}")

    all_nodes = service._repo.get_skeleton(tid)
    print(f"\n[主线骨架] {len(all_nodes)} 节点:")
    for n in all_nodes[:5]:
        print(f"    #{n['order_index']} {n['title']}: {n['event_summary']}")

    passages = service.search_style_passages(tid, query=title, top_k=2)
    print(f"\n[风格片段检索] {title!r} → {len(passages)} 段命中")

    print(f"\n[结果] {title} 章节情节提取全链路跑通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 建 MySQL 库 + 跑脚本（前 3 块，控制成本）**

```bash
mysql -u root -e "CREATE DATABASE IF NOT EXISTS easygame_test CHARACTER SET utf8mb4;"
HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 scripts/extract_novel_template.py --path docs/鹿鼎记.txt --title 鹿鼎记 --max-chunks 3
```

Expected: 打印 [1]..[4] + 风格圣经/角色/桥段/骨架/片段检索各有内容，末行「全链路跑通」。若某类为空，检查对应 `reduce_*` 的 LLM 返回（真 LLM 偶发字段缺失，第一版容忍空列表）。

- [ ] **Step 3: 补文档**

在 `docs/foundation-requirements.md` 的 StoryTemplate 段落末尾追加运行入口：

```markdown
### 章节情节提取运行入口（通用，任意小说）

导入任意一部中文小说，提炼 4 类共享模板 + 原文向量片段：

```bash
HF_ENDPOINT=https://hf-mirror.com python3 scripts/extract_novel_template.py \
  --path docs/鹿鼎记.txt --title 鹿鼎记 --max-chunks 3
```

`--max-chunks 0` 提取全文（真 DeepSeek 调用量大、耗时长）；换书只改 `--path/--title`。
模板为**全局共享**资产（`--user-id` 仅作归属标记，只存不过滤）。结果落 MySQL 4 表
（`story_template` / `template_style_bible` / `template_character` /
`template_plot_beat` / `template_plot_skeleton`）+ pgvector（`style_passage` 片段，
按 `tmpl:{tid}:` 前缀隔离多模板）。
```

- [ ] **Step 4: 提交（脚本 + 文档）**

```bash
git add scripts/extract_novel_template.py docs/foundation-requirements.md
git commit -m "feat(story-template): 鹿鼎记全文提取脚本 + 运行入口文档"
```

---

## Self-Review

**1. Spec coverage:**
- §3.3 切块（卷/章/节/回/纯数字/无「第」/无标记/序·楔子·番外 + 复合 order + 误命中防护）→ Task 2 ✓
- §3.4 分层归并流水线（Level0 切块 → embedding → Level1 map → Level2 聚合 → Level3 归并 → 落库 + 片段入库）→ Task 6 `import_novel` 编排 ✓
- §3.5 全局连贯（order_index 透传、角色同名+相似度合并、风格投票）→ Task 4 reduce_style 投票 + Task 3 merge_characters + order 透传 ✓
- §3.7 第一版串行、map_chunks 收敛单方法预留并行接口 → Task 4 ✓
- §4 四类产物 TypedDict + MySQL 4 分表 → Task 1 + Task 5 ✓
- §5.1 Service 5 个接口 → Task 6 ✓
- §5.2 面向接口 + 依赖注入（embedding/vectorstore/BaseAgent/Repository 均注入）→ Task 6 构造函数 + factory ✓
- §7 测试矩阵 → chunker/schema（纯逻辑）、clustering（真 bge）、extract_agent（fake client）、repository（真 MySQL）、service（fake LLM + 真库）、e2e 鹿鼎记（Task 7 手动脚本）✓
- §8 依赖：pymysql 已装（env_bootstrap 已探测）；MySQL 建库在 Task 7 ✓

**Gap 修正：** spec §7 列 `test_template_e2e_fulltext.py` 为「手动触发不进套件」，本plan 用 `scripts/extract_luding_template.py`（Task 7）替代——更贴合「用鹿鼎记真实测试」的当前诉求，且天然不进日常单测。已在文件结构标注。

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 均含完整可运行代码。

**3. Type consistency:**
- `Chunk(chunk_id, order_index, text, title)` 在 Task 2 定义，Task 4/6 一致引用 ✓
- `ChunkSignal` 字段（chunk_id/order_index/style_tone_tags/style_devices/characters/is_event/event_summary）Task 1 定义，Task 4 map_chunks 产出一致、Task 6 消费一致 ✓
- `template_scope_prefix(template_id)`（全局共享，不带 user/player）在 Task 6 doc_id 前缀调用一致 ✓；`save_template(*, user_id=0, ...)` user_id 仅存不过滤 ✓
- `StoryTemplateService.__init__` 参数（chunker/extract_agent/clustering/repository/vector_store/embedding）与 factory 传参一致（Task 6）✓
- `save_template(**)` 参数与 service 调用一致（Task 5/6）✓
- PgVectorStore `filters` 用 `{"template_id": str(tid), "doc_type": "style_passage"}`——`doc_type` 走顶层列、`template_id` 走 JSONB astext（与 pgvector_store.py:100-107 行为一致，str 化匹配）✓

## 边界（本 plan 不含）

- Level1 并行 fan-out（后续 spec）。
- `TemplateInjection` 接线 Playwright（后续 spec，放 easy_game 侧）。
- 采样率/簇数/阈值系统性调优（第一版给经验默认值）。
- 全文 11572 行一次性提取的成本优化——Task 7 用 `--max-chunks` 控制首轮。
