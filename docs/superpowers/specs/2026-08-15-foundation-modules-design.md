# 基础模块体系（Foundation Modules）设计

日期：2026-08-15
状态：待实现（spec 定稿中，等待 review）

## 1. 背景与目标

easy_game 的向量化、数据库操作、共享数据类型、检索逻辑目前散落在 `Recall/`、`Persistence/` 等业务模块内，导致：

- 新模块（如小说模板 `StoryTemplate`）要用 embedding / 向量库，只能反向依赖 `Recall` 或复制一份 —— 耦合或重复。
- 数据库连接封装绑死在业务类 `GameSaveStore` 里，无法被其他模块复用。
- 向量后端要从 Redis Stack 迁到 pgvector，牵动面太大。

**目标：** 把公共基础能力剥离成一组**职责单一、互不依赖（同层）的基础模块**，上层业务（Recall 回忆、游戏存档、未来的 StoryTemplate 等）平等地依赖它们，依赖方向严格单向向下。

**本 spec 只做基础模块体系。** 小说模板提取、Recall 迁移到 pgvector 作为后续独立 spec，依赖本 spec 产出的基础模块。

## 2. 分层架构

```
第二层（组合基础，依赖第一层）
        ┌────────────────────────────────────┐
        │  混合检索 HybridRetrieval             │
        │  端到端：稠密 + 稀疏 → RRF 融合 → 重排 │
        └───┬────────────┬───────────┬─────────┘
            ▼            ▼           ▼
第一层（纯基础，互不依赖）
   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ 公用数据  │  │ 数据库    │  │ 向量库    │  │ embedding │
   │ 结构      │  │ 基础      │  │ 基础      │  │ 基础      │
   │ datatypes │  │ (SQLA)   │  │ (pgvector)│  │ (bge)    │
   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
        ▲             ▲             ▲             ▲
        └─────────────┴──────┬──────┴─────────────┘
                             │（上层业务各自按需依赖，单向向下）
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                     ▼
   ┌──────────┐      ┌──────────────┐      ┌──────────────┐
   │  Recall   │      │ Persistence  │      │ StoryTemplate│
   │ (回忆系统) │      │ (游戏存档)    │      │ (小说模板,后续)│
   └──────────┘      └──────────────┘      └──────────────┘
```

**依赖规则（硬约束）：**

- 第一层四个模块**互不依赖**。
- 第二层（混合检索）只依赖第一层，不依赖任何业务模块。
- 基础模块**不反向依赖**任何业务模块（不 import GameState / Graph / Recall 等）。
- 业务模块依赖基础模块，方向单向向下。

## 3. 第一层基础模块

### 3.1 公用数据结构（datatypes）

跨模块共享的纯数据类型与约定，无逻辑、无框架耦合。

- **可检索文档基类**：把 `Recall/domain/documents.py` 的 `RecallDoc` 泛化为通用 `VectorDoc`（`doc_id / doc_type / tenant keys / text / metadata`），Recall 的 `RecallDoc` 可继承或组合它。
- **租户前缀约定**：统一 `tenant_prefix(user_id, player_id) -> "u{user}:p{player}:"`，以及模板层扩展前缀 `tmpl:{template_id}:`。这是既有 code review 踩过的致命坑（各玩家共用 scene_id，不加前缀会跨租户覆盖），必须集中在此，杜绝各模块各写一份。
- **检索结果类型**：`ScoredDoc`（doc + score + 分项因子），供混合检索和业务层共用。

### 3.2 数据库基础（db）

SQLAlchemy engine / session 的通用封装，从现有 `Persistence/Store.py` 抽出。

- `DatabaseConfig`（database_url / echo / pool 参数）。
- `Database`：持有 `engine` + `sessionmaker`，提供 `session()` 上下文管理器、`create_all(metadata)` 等通用能力。
- **不含任何业务表逻辑**（存档表、角色表等仍留在 Persistence）。
- **Persistence 改为依赖它**：`GameSaveStore` 不再自己 `create_engine`，改为接收注入的 `Database`（构造函数注入，保持向后兼容 —— 仍可传 url，由内部构造 `Database`）。

### 3.3 向量库基础（vectordb）

pgvector 的基本操作，纯基础设施，不含业务语义。

- `VectorStore`（抽象接口）：`upsert(rows)` / `search(query_vector, *, filters, top_k)` / `delete(ids)`。
- `PgVectorStore`（实现）：连 PostgreSQL + pgvector 扩展。
  - 向量列 `vector(512)`（对齐 bge），索引 **HNSW + `vector_cosine_ops`**（COSINE）。
  - 行 id 带租户前缀（用 §3.1 的约定），前缀作为主键/唯一约束组成，保证多租户/多来源不互相覆盖。
  - 支持按 metadata 过滤（如 user_id / player_id / doc_type）。
- 依赖 §3.1 的数据类型；**不依赖** embedding（只接收现成向量）。

### 3.4 embedding 基础（embedding）

bge-small-zh-v1.5 本地加载与编码。承接现在为空的 `Recall/embedding/`。

- `EmbeddingModel`（抽象接口）：`encode(texts) -> list[vector]`，`dimension` 属性。
- bge 实现：本地加载 `bge-small-zh-v1.5`（512 维，COSINE 语义），`encode` 带 batch。
- 依赖注入 + 可 mock（测试不加载真实模型）。
- 独立第一层，不依赖向量库/数据库/数据结构。

## 4. 第二层：混合检索（HybridRetrieval）

端到端的检索流程全部下沉到此模块，业务层只传查询与参数。

- **依赖**：向量库基础（稠密 KNN）、数据库/向量库的关键词能力（稀疏）、embedding 基础（把 query 文本转向量）、公用数据结构。
- **端到端流程**：
  1. 稠密检索：query 经 embedding → `VectorStore.search` KNN。
  2. 稀疏检索：关键词/全文检索（pgvector 侧或 DB 全文索引）。
  3. **RRF 融合**（k=60，可配置）合并两个排名。
  4. **可配置重排**：三因子 `relevance`（RRF 分）/ `recency`（时间衰减）/ `importance`（文档重要度）；权重与衰减策略作为参数传入，默认给一套策略，业务可覆盖。
- **粗召回→细召回**：支持先按 summary 粒度粗召回定位，再在命中范围内按 chunk 粒度细召回（Recall 的双粒度用法）。
- 输出 `list[ScoredDoc]`。
- 业务层（Recall.query_recall / StoryTemplate 检索）只调 `HybridRetrieval.search(query, *, filters, weights, top_k)`。

## 5. 对既有代码的影响

- **Persistence**：`GameSaveStore` 改为依赖 `db.Database`（注入），去掉内部 `create_engine`。存档功能行为不变，仅换连接来源。需回归现有持久化测试。
- **Recall**：
  - `Recall/domain/documents.py` 的 `RecallDoc` 改为基于 datatypes 的 `VectorDoc`。
  - `Recall/embedding/`、`Recall/storage/`（空目录）不再自行实现，改为依赖 embedding / vectordb 基础模块。
  - Recall 进度文档里"检索层 RRF+三因子重排"改为**调用** HybridRetrieval，而非自己实现。
  - **向量后端从 Redis Stack 改为 pgvector**（旧进度文档的 Redis 假设作废，以本 spec 为准）。
- **新依赖**：引入 PostgreSQL + pgvector（`psycopg` / `pgvector` Python 包）、bge 模型加载依赖（如 sentence-transformers 或等价）。项目当前无 requirements 清单，本次需补一份依赖说明。

## 6. 模块划分（目录）

按 easy_game 现有扁平 + 子包风格，各基础模块为项目根下子包：

```text
datatypes/          # 公用数据结构（VectorDoc / ScoredDoc / 租户前缀约定）
├── __init__.py
├── documents.py
└── tenancy.py

db/                 # 数据库基础
├── __init__.py
├── config.py       # DatabaseConfig
└── database.py     # Database（engine/session 封装）

vectordb/           # 向量库基础
├── __init__.py
├── interface.py    # VectorStore 抽象
└── pgvector_store.py

embedding/          # embedding 基础
├── __init__.py
├── interface.py    # EmbeddingModel 抽象
└── bge_model.py

hybrid_retrieval/   # 第二层：混合检索
├── __init__.py
├── rrf.py          # RRF 融合
├── rerank.py       # 三因子可配置重排
└── retriever.py    # HybridRetrieval 端到端入口
```

（顶层目录名如需统一收进 `foundation/` 可后续调整；本 spec 先按扁平子包，与现有 Recall/Persistence 平级。）

## 7. 架构约束（解耦）

- **面向接口 + 依赖注入**：`VectorStore` / `EmbeddingModel` / `Database` 都以抽象声明，构造时注入，便于单测替换与后端迁移。
- **单一职责**：每个基础模块只做一件事，可独立单测。
- **单向依赖**：基础模块不 import 业务模块；同层不互相依赖（除混合检索依赖第一层）。
- **纯数据契约**：datatypes 只是 TypedDict / dataclass，无框架耦合，任意模块可消费。

## 8. 与既有约定的一致性

- 中文回复 + 中文注释 / docstring。
- 代码按模块分子包，不堆在一个文件夹；新文件不放根目录（基础模块子包本身即顶层子包，符合项目现状）。
- TDD：先写接口契约测试（红）再实现（绿）。
- 按内容拆分 commit，中文 message，不 push。

## 9. MVP 边界与后续

- **MVP（本 spec）**：四个第一层基础模块 + 混合检索；Persistence 改依赖 db；Recall 数据类型改依赖 datatypes（不含 Recall 检索/存储完整重接线）。
- **后续 spec**：
  1. Recall 迁移到 pgvector + 接线 HybridRetrieval。
  2. 小说模板 `StoryTemplate`（依赖本基础模块体系，见 `2026-08-15-novel-template-extraction-design.md`，其向量/embedding/数据类型改为依赖基础模块）。
  3. 项目整体向量后端从 Redis Stack 迁移到 pgvector。
