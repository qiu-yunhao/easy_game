# 小说模板情景提取（对齐基础模块版）设计

日期：2026-08-16
状态：待实现（spec 已定稿，等待 review）
取代：`2026-08-15-novel-template-extraction-design.md`（写于基础模块重构之前，embedding/向量/数据类型的自建假设已作废）

## 0. 与旧 spec 的差异（对齐基础模块）

核心设计（离线提炼 4 类结构化产物 + 原文向量片段、分层归并 + embedding 加速、对外单一 Facade + 面向接口 + 依赖注入、单向依赖）**全部保留**。仅把「自建基础能力」改为「依赖已落地的基础模块」：

| 旧 spec 假设 | 对齐后 |
|---|---|
| 在 `Recall/embedding/` 或 `StoryTemplate/TemplateEmbedding.py` 自建 bge 加载器 | 依赖 `embedding.BgeEmbeddingModel`（基础模块，512 维 COSINE，已验证） |
| `StoryTemplate/interfaces.py` 自定义 `VectorStore` + `StoryTemplate/PgVectorStore.py` | 依赖 `vectordb.VectorStore` / `vectordb.PgVectorStore`（基础模块） |
| 自定义 VectorDoc / 租户前缀 | 依赖 `datatypes.VectorDoc` / `datatypes.template_prefix`（基础模块） |
| `TemplateRepository` 直写 MySQL 驱动 | 复用 `db.Database`（SQLAlchemy），连接串 `mysql+pymysql://` |

## 1. 背景与目标

在「自动写小说」模式下，允许用户提供一部小说作为**模板**。系统离线把小说提炼成结构化模板 + 原文向量片段，供 `PlaywrightAgent` 在生成 premise / outline / chapter / scene 时**按需注入与检索**。

**定位（已锁定，不再讨论）：**

- 小说 = **风格 + 世界观参照**；剧情仍由 Playwright **原创**，不逐场景照搬原著。
- 额外提取两类情节素材：**情节桥段池**（无序、可复用）+ **有序情节骨架**（主线 A→B→C）。
- 角色仅作**原型参照**，不自动实例化成可玩 `CharacterProfile`。
- 提取是**离线一次性**（导入时发生），结果持久化；游戏运行时零提取开销，只做检索 + 注入。

**执行位置：** 新建 `StoryTemplate` 子包（与 `PlayerWriter` 平级），沿用 `BaseAgent` + JSON schema + 两次重试模式（参照 `PlayerWriter/PlayerWriterAgent.py` 的 `_execute_with_retry`）。

## 2. 整体架构与依赖方向

小说文本不直接进入生成上下文（太长、会污染原创性）。它先被离线提炼成结构化模板，再由 Playwright 按需引用。

```
用户提供小说.txt
      │
      ▼
┌─────────────────────────── StoryTemplate 子包 ───────────────────────────┐
│  1. TemplateChunker      长文本 → 卷/章/节/回切块（依赖 embedding 向量化）  │
│  2. TemplateExtractAgent 分层归并提取（BaseAgent + 两次重试）：             │
│       ├─ StyleBible      写作风格 + 世界观设定                              │
│       ├─ CharacterArchetype 角色原型（仅参照）                             │
│       ├─ PlotBeat        情节桥段池（无序，带标签）                        │
│       └─ PlotSkeletonNode 有序情节骨架（事件 A→B→C）                       │
│  3. TemplateClustering   纯向量：事件块筛选 / 桥段聚类去重 / 角色合并       │
│  4. TemplateRepository   MySQL 4 分表持久化（注入 db.Database）            │
│  5. 片段入向量库          vectordb.PgVectorStore（租户前缀）               │
└──────────────────────────────────────────────────────────────────────────┘
      │                                          │
      ▼（结构化模板，MySQL）                     ▼（原文片段向量，pgvector）
┌──────────────────┐                    ┌────────────────────┐
│ 四张分表（§4）    │                    │ vectordb 向量库      │
└──────────────────┘                    └────────────────────┘
      │
      ▼ 按需注入（下一个独立 spec，本设计不含）
┌──────────────────────────────────────────────────────────────────────────┐
│  easy_game 侧 TemplateInjection → PlaywrightFormatter.build_*_instruction  │
└──────────────────────────────────────────────────────────────────────────┘
```

**依赖方向（严格单向向下）：**

```
StoryTemplate  ──依赖──▶  embedding / vectordb / datatypes / db（基础模块）
StoryTemplate  ──依赖──▶  BaseAgent（LLM 注入）
easy_game(Playwright) ──依赖──▶ StoryTemplateService（接口）
StoryTemplate  ✗不反向依赖✗  easy_game 运行时（GameState/Graph）
```

**双轨划分原则（延续既有 RAG 约定）：**

- 向量库存**小说原文片段**（供风格模仿参照）；StyleBible / 角色 / 情节层是**结构化提炼**存 MySQL。
- 向量后端用 **pgvector**（`vectordb.PgVectorStore`）；结构化后端用 **MySQL**（`db.Database` + `mysql+pymysql://`）。两者都经 `db.Database` 抽象注入。
- 向量行必须带租户前缀 `tmpl:{template_id}:u{user}:p{player}:`（`datatypes.template_prefix`），避免多用户 / 多模板互相覆盖。pgvector 中该前缀作为 doc_id 组成部分（`PgVectorStore` 已以 doc_id 为主键幂等 upsert）。

## 3. 长文处理：embedding 加速的分层归并

### 3.1 难点

- 10 万字 ≈ 15–18 万 token，远超单次上下文，必须切块。
- 独立提取会**丢跨块信息**（同一角色跨章、主线连贯性）。
- 纯 map-reduce 的一次性 reduce 又会撑爆上下文。
- 核心难点：**在有限上下文里保持全局连贯性**，同时控制 LLM 调用量。

### 3.2 embedding 规格（复用基础模块）

- 模型：`embedding.BgeEmbeddingModel`（`BAAI/bge-small-zh-v1.5`，**512 维**，COSINE，归一化）。
- 向量库：`vectordb.PgVectorStore`（`vector(512)` + HNSW + `vector_cosine_ops`）。
- **不在本子包内加载模型或定义向量接口**：向量化经注入的 `embedding.EmbeddingModel`，存储经注入的 `vectordb.VectorStore`。

**embedding 能做/不能做：** embedding 只算语义相似度，**不能生成/提炼**结构化内容。

- 可用 embedding（`TemplateClustering`，零 LLM）：判断两块是否同一事件、桥段聚类去重、角色归并、筛选事件块。
- 必须 LLM（`TemplateExtractAgent`）：从文字提炼风格标签 / 角色 persona / 事件概要、把多片段归并成设定。

**采样粒度（已选：中度方案）：** embedding 负责去重 / 聚类 / 筛事件块；**风格与角色仍逐块提炼保证不漏**。目标 LLM 调用量 ~50 次（10 万字），比纯分层归并省约一半。

### 3.3 切块：中文卷/章/节/回标记识别（TemplateChunker）

中文小说分层标记形式丰富，切块正则需覆盖：

**层级词：** 卷 / 部 / 篇 / 集（大层）；章 / 节 / 回 / 折（小层）。

**数字形式：**

- 中文数字：`第三十七章`、`第一百零八回`
- 阿拉伯数字：`第37章`、`第 37 章`（带空格）
- 无「第」前缀：`三十七章`、`卷二`、`037 章`

**排版形式：**

- 带标题：`第三章 初入宗门`、`第三章：初入宗门`、`第三章、初入宗门`
- 纯标记独占一行：`第三章`
- 常见前后空白 / 全角空格

**正则草案（按行匹配，行首独立）：**

```
标记词 = (卷|部|篇|集|章|节|回|折)
数字   = ([0-9]+|[一二三四五六七八九十百千零两]+)
行首标记 = ^\s*第?\s*<数字>\s*<标记词>\s*([:：、.\-—]?\s*.*)?$
```

**分层与排序策略（关键）：**

- 卷/部/篇/集 = 大层；章/节/回/折 = 小层。同一部书可能同时出现「第一卷」与「第一章」。
- 切块以**最细可用层**为准：
  - 有章/节/回/折标记 → 按它切；卷号作为 `order_index` 的高位（复合排序 `(卷号, 章号)`，跨卷不乱序）。
  - 只有卷/部/篇/集（无更细标记）→ 按卷切。
  - 完全无标记 → ~2000 字滑窗，`order_index` 按滑窗序号。

**误命中与边界防护：**

- 只在**行首独立**匹配（避免正文里「这一章的教训」被当标题）。
- 标题行长度上限（≤30 字），过长视为正文不切。
- 数字解析失败（生僻写法）→ 仍切块，`order_index` 用出现顺序兜底，不丢块。
- 序 / 楔子 / 尾声 / 番外 → 独立特殊块：楔子/序排最前，尾声/番外排最后。

每块产出 `chunk_id + order_index + 原文`，随后全部块交 `embedding.encode` 向量化（本地，≈免费）。

### 3.4 分层归并流水线（import_novel 内部，串行）

```
Level 0: 切块 (TemplateChunker) → list[Chunk]（见 §3.3）
             │
         embedding.encode(所有 chunk 文本) → 每块 512 维向量
             │
Level 1: Map — 逐块局部信号 (TemplateExtractAgent._map_chunks，串行，真 LLM)
  · 风格：逐块提炼（不采样，保证不漏）
  · 角色：逐块提炼出现角色 + 行为片段
  · 情节：TemplateClustering 先按向量筛"事件块"，只对事件块提炼事件概要
  → list[ChunkSignal]（带 chunk_id + order_index）
             │
Level 2: 向量聚合 (TemplateClustering，零 LLM)
  · 桥段去重：向量聚类，相似片段归一类
  · 角色合并：同名 + 向量相似度双 key
  · 风格聚合：各块风格标签投票统计
             │
Level 3: 全局归并 (TemplateExtractAgent，四类产物各 1 次真 LLM)
  · StyleBible          ← 全局风格投票 + 世界观设定汇总
  · CharacterArchetype  ← 跨块合并后的角色特征
  · PlotBeat            ← 聚类去重后的桥段 → 抽象成可复用桥段
  · PlotSkeletonNode    ← 事件按 order_index 排序 → 主线骨架
             │
持久化: TemplateRepository(MySQL) 写 4 表 → 返回 template_id
        原文片段 → PgVectorStore.upsert（doc_id 带 template_prefix 租户前缀）
```

### 3.5 保持全局连贯性的手段

- **order_index 全程透传**：chunk → signal → 产物都带顺序号；PlotSkeleton 最终按 order 排序，主线 A→B→C 不乱。
- **角色跨块合并键**：同名 + 向量相似度双 key，避免「第 3 章张三」与「第 80 章张三」被当成两人。
- **风格投票聚合**：各块风格样本统计高频标签，得稳定全局风格，不被个别章节带偏。

### 3.6 规模自适应与调用量

- 可配置参数：`chunk_size`（默认 ~2000 字）、`group_size`（默认 10 块/组）、`max_levels`（默认 3，超了继续递归组间归并）、`event_block_threshold`（事件块筛选相似度阈值）、`max_failed_ratio`（默认 0.2）。
- 块数很多时自动多加一层组间归并，层数随规模自适应。

**10 万字调用量估算（中度方案）：** 全块 embedding 0 次 LLM（本地 ~90 次）；Level 1 风格+角色逐块 ~35–45 次；Level 3 全局归并 4 次；**LLM 总计 ~50 次**。一次导入发生，结果持久化，重开游戏直接读表。

### 3.7 并行执行（第一版先串行，留接口）

块之间相互独立，理论上 Level 1 可并行 fan-out。**第一版先串行实现**，把 Level 1 逐块提炼收敛到 `TemplateExtractAgent._map_chunks(chunks) -> list[ChunkSignal]` 一个方法里，签名预留「接收块列表 → 返回信号列表」，后续换并行实现（命名 agent + `max_concurrency` + 结果按 order 归位 + 部分失败隔离）时**不动调用方**。并行是纯性能优化，不影响正确性与测试。

### 3.8 权衡（已知代价）

- 事件块筛选可能漏掉极冷门主线事件（`event_block_threshold` 可调，放宽更全）。
- 引入聚类逻辑，比纯 map-reduce 略复杂，多一个调参旋钮。
- 第一版串行导入 10 万字耗时较长；并行留作后续优化。

## 4. 数据结构（4 类产物）

沿用 `PlayerWriter/PlaywriterSchema.py` 的 JSON-schema 风格。TypedDict 定义在 `TemplateSchema.py`，纯数据契约。分表存 MySQL。

### 主表 story_template
`template_id, user_id, player_id, source_title, created_at`

### ① StyleBible（风格 + 世界观，每模板单条，始终注入）
```python
class StyleBible(TypedDict):
    narrative_voice: str          # 叙事人称/视角
    tone_tags: list[str]          # 语气标签（冷峻、诙谐、古雅…）
    prose_rhythm: str             # 句式节奏（长句铺陈 / 短句凌厉）
    signature_devices: list[str]  # 标志性手法（环境白描、内心独白…）
    world_premise: str            # 世界观一句话核心
    cultivation_system: str       # 修炼体系（境界划分、灵根规则）
    factions: list[str]           # 主要势力/门派
    key_locations: list[str]      # 标志性地点
    world_rules: list[str]        # 硬设定/禁忌
    lexicon: list[str]            # 专有名词/术语表
```

### ② CharacterArchetype（角色原型，多条，仅参照）
```python
class CharacterArchetype(TypedDict):
    name: str
    role_summary: str               # 在原著里的定位
    persona: list[str]              # 对应 CharacterProfile.persona
    speech_style: str
    secrets: list[str]
    signature_relations: list[str]  # 典型关系模式（如"亦师亦敌"）
    suggested_layer: str            # 建议映射到 player/actor/L2/L1
```

### ③ PlotBeat（情节桥段池，多条，无序，带标签）
```python
class PlotBeat(TypedDict):
    beat_id: str
    label: str                    # 桥段名（拜师/夺宝/背叛/渡劫）
    tags: list[str]               # 检索标签
    summary: str                  # 桥段概要（抽象到可复用，去掉专有情节）
    dramatic_function: str        # 戏剧功能（转折/铺垫/高潮）
    reusable_conflict: str        # 可复用的核心冲突
```

`summary` **抽象化处理**：去掉原著专有名词，只留冲突结构。

### ④ PlotSkeletonNode（有序情节骨架，多条，带序 + 依赖）
```python
class PlotSkeletonNode(TypedDict):
    node_id: str
    order_index: int              # 主线顺序
    title: str
    event_summary: str            # 事件概要（A→B→C 的一环）
    preconditions: list[str]      # 前置节点/条件
    maps_to_chapter_hint: str     # 建议对应到第几个修为阶段/章节
```

### MySQL 4 分表（TemplateRepository，SQLAlchemy Table）

- `story_template`(template_id PK, user_id, player_id, source_title, created_at)
- `template_style_bible`(template_id FK/PK, 各标量列；列表字段存 JSON 文本)
- `template_character`(id PK, template_id FK, 各字段；列表存 JSON)
- `template_plot_beat`(beat_id PK, template_id FK, 各字段；tags 存 JSON)
- `template_plot_skeleton`(node_id PK, template_id FK, order_index, 各字段；preconditions 存 JSON)

MySQL 5.7+ 无原生数组类型，列表字段统一 JSON 编码存 `TEXT/JSON` 列，读回时解码。

## 5. 对外 Facade 与依赖注入

### 5.1 StoryTemplateService（对外唯一入口）

```python
class StoryTemplateService:
    def import_novel(self, *, user_id, player_id, source_title, text) -> str: ...
        # 切块→向量化→Level1 逐块提炼→Level2 聚合→Level3 归并→MySQL 4 表 + 片段入向量库；返回 template_id
    def get_style_bible(self, template_id) -> StyleBible: ...
    def suggest_plot_beats(self, template_id, *, query, top_k) -> list[PlotBeat]: ...
    def next_skeleton_nodes(self, template_id, *, chapter_hint) -> list[PlotSkeletonNode]: ...
    def search_style_passages(self, template_id, *, query_vector, top_k) -> list[str]: ...
```

内部子模块（Chunker / ExtractAgent / Clustering / Repository）**不对外直接暴露**，只经 Service 使用。Service 出口只给纯 TypedDict / str。

### 5.2 面向接口 + 依赖注入

跨边界协作对象以抽象接口声明，构造时注入：

- `embedding.EmbeddingModel`（抽象）→ `BgeEmbeddingModel`（实现）：向量化可 mock。
- `vectordb.VectorStore`（抽象）→ `PgVectorStore`（实现）：向量存储可替换后端。
- `BaseAgent`（LLM）：`TemplateExtractAgent` 继承之，测试可注入 fake `client`。
- `TemplateRepository`：注入 `db.Database`，engine 可换（测试/生产切库只换连接串）。

`factory.py` 装配 Service + 注入默认实现（参照 `ComponentFactory` 延迟构造风格），不在内部 `import` 具体实现细节。

### 5.3 与 easy_game 的边界

- 依赖方向**单向**：easy_game（Playwright 层）依赖 `StoryTemplateService` 接口；`StoryTemplate` **不反向依赖** easy_game 的 GameState / Graph。
- **注入适配 `TemplateInjection`（把模板产物转成 Playwright 指令片段）放 easy_game 侧，不在本子包，且不纳入第一版**。第一版范围 = 导入流水线 + 4 类产物落库 + 4 个检索接口跑通。接线 Playwright 是下一个独立 spec。
- 数据契约是纯 TypedDict（§4），无框架耦合。

## 6. 模块划分（StoryTemplate 子包）

```text
StoryTemplate/
├── __init__.py                # 只导出 StoryTemplateService + 4 类数据契约（对外表面）
├── StoryTemplateService.py    # 对外 Facade：import_novel / get_* / suggest_* / next_* / search_*
├── TemplateSchema.py          # 4 类产物 TypedDict + JSON schema（§4，纯数据契约）
├── TemplateChunker.py         # 长文切块 + order_index（卷/章/节/回 正则，见 §3.3）
├── TemplateExtractAgent.py    # 分层归并提取（继承 BaseAgent + _execute_with_retry 两次重试）
├── TemplateClustering.py      # 纯向量：事件块筛选 / 桥段聚类去重 / 角色合并（注入 EmbeddingModel）
├── TemplateRepository.py      # 4 张分表持久化（注入 db.Database，MySQL）
└── factory.py                 # 装配 Service + 注入默认实现（延迟构造）
```

相比旧 spec 删去：`interfaces.py`（用 `vectordb`/`embedding` 抽象）、`TemplateEmbedding.py`（向量化用 `embedding.BgeEmbeddingModel`，纯向量算法归入 `TemplateClustering.py`）、`PgVectorStore.py`（用 `vectordb.PgVectorStore`）、`TemplateParallelRunner.py`（第一版串行，方法内留接口）。

## 7. 测试策略（真 LLM + 极短文本 / TDD）

真 LLM 测试统一用**极短文本**（几百字），单次调用秒级、成本可控，仍验证真实提取链路。bge / pgvector 已在基础模块验证。

| 测试文件 | 依赖 | 说明 |
|---|---|---|
| `tests/test_template_chunker.py` | 纯逻辑 | 卷/章/节/回/纯数字/无「第」/无标记/序·楔子·番外；复合 order 排序；误命中防护 |
| `tests/test_template_schema.py` | 纯逻辑 | 4 类 TypedDict + JSON schema 结构 |
| `tests/test_template_clustering.py` | 真 bge | 极短文本：事件块筛选 / 桥段聚类去重 / 同名+相似度角色合并 |
| `tests/test_template_extract_agent.py` | 真 LLM + 极短文本 | 验证 Level1 逐块信号 + Level3 四类归并真跑通 |
| `tests/test_template_repository.py` | 真 MySQL(easygame_test) | 4 表建表 + 写入 + 读回；template_id 幂等 |
| `tests/test_template_service.py` | 真 LLM + 真 MySQL + 真 pgvector | 极短小说端到端：import_novel → 4 接口检索；租户前缀隔离 |
| `tests/test_template_e2e_fulltext.py` | 真全链路 | **手动触发**（环境变量/标记），完整长文，不进日常套件 |

- 每模块 red→green→中文 commit，不 push。
- Service / Repository 集成测试用真 MySQL；ExtractAgent 测试注入真 LLM client（`BaseAgent` 支持传入 `client`）。

## 8. 依赖与测试库

### 新增 Python 包

- `pymysql`（MySQL 驱动）。

### 连接串

- 结构化分表（MySQL）：`mysql+pymysql://root@localhost:3306/easygame_test`（本机 Homebrew MySQL 8，root 免密）。
- 向量片段（PostgreSQL）：`postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test`（复用基础模块测试库）。

### 首次运行前置

```bash
pip install pymysql
mysql -u root -e "CREATE DATABASE IF NOT EXISTS easygame_test CHARACTER SET utf8mb4;"
# PostgreSQL easygame_test + vector 扩展已在基础模块建好
```

依赖信息补进 `docs/foundation-requirements.md`。

## 9. 与既有约定的一致性

- 中文回复 + 中文注释。
- 按模块分子包（`StoryTemplate/`）。
- TDD：先写测试再实现，红→绿→中文 commit，不 push。
- 复用基础模块（`datatypes` / `embedding` / `vectordb` / `db`），单向向下依赖，不反向依赖 easy_game 运行时。
- 对外服务化解耦：单一 Facade（`StoryTemplateService`）+ 面向接口 + 依赖注入。

## 10. MVP 边界与后续

- **第一版（本 spec）**：切块（卷/章/节/回 正则）+ 逐块提炼（串行，真 LLM）+ 向量聚合 + 四类产物 + MySQL 4 分表 + pgvector 片段存储 + 4 个检索接口跑通。
- **后续独立 spec**：
  - Level 1 并行 fan-out（`max_concurrency` + 部分失败隔离）替换串行实现。
  - `TemplateInjection` 接线 Playwright 的 `build_*_instruction`（放 easy_game 侧）。
  - 采样率/簇数/阈值调优。
