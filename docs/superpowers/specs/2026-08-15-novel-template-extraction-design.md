# 小说模板情景提取（Novel Template Extraction）设计

日期：2026-08-15
状态：待实现（spec 已定稿，等待 review）

## 1. 背景与目标

在「自动写小说」模式下，允许用户提供一部小说作为**模板**。系统离线把小说提炼成结构化模板 + 原文向量片段，供 `PlaywrightAgent` 在生成 premise / outline / chapter / scene 时**按需注入与检索**。

**定位（已锁定，不再讨论）：**

- 小说 = **风格 + 世界观参照**；剧情仍由 Playwright **原创**，不逐场景照搬原著。
- 额外提取两类情节素材：**情节桥段池**（无序、可复用）+ **有序情节骨架**（主线 A→B→C）。
- 角色仅作**原型参照**，不自动实例化成可玩 `CharacterProfile`。
- 提取是**离线一次性**（导入时发生），结果持久化；游戏运行时零提取开销，只做检索 + 注入。

**执行位置：** 新建 `StoryTemplate` 子包（与 `PlayerWriter` 平级），沿用 `BaseAgent` + JSON schema + 两次重试模式（参照 `PlayerWriter/PlayerWriterAgent.py` 的 `_execute_with_retry`）。

## 2. 整体架构与数据流

小说文本不直接进入生成上下文（太长、会污染原创性）。它先被离线提炼成结构化模板，再由 Playwright 按需引用。

```
用户提供小说.txt
      │
      ▼
┌─────────────────────────── StoryTemplate 子包 ───────────────────────────┐
│  1. TemplateChunker      长文本 → 章节/片段切块（复用 bge-small-zh 向量化）│
│  2. TemplateExtractAgent embedding 加速的分层归并提取：                    │
│       ├─ StyleBible      写作风格 + 世界观设定                              │
│       ├─ CharacterArchetype 角色原型（仅参照）                             │
│       ├─ PlotBeatLibrary 情节桥段池（无序，带标签）                        │
│       └─ PlotSkeleton    有序情节骨架（事件 A→B→C）                        │
│  3. TemplateStore        分表持久化 + 片段入向量库（租户前缀）              │
└──────────────────────────────────────────────────────────────────────────┘
      │                                          │
      ▼（结构化模板，存 MySQL）                  ▼（原文片段向量，存 pgvector）
┌──────────────────┐                    ┌────────────────────┐
│ 四张分表          │                    │ 向量库（原文片段）   │
│ （见 §4）         │                    │ 供生成时 RAG 检索   │
└──────────────────┘                    └────────────────────┘
      │
      ▼ 按需注入
┌──────────────────────────────────────────────────────────────────────────┐
│  PlaywrightFormatter.build_*_instruction()                                 │
│    在 premise/outline/chapter/scene 指令里注入：                           │
│      · StyleBible 摘要（风格+世界观，始终注入）                            │
│      · 相关 PlotBeat / PlotSkeleton 节点（按当前进度检索/挑选）            │
│      · 可选：从向量库检索到的原文风格片段                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

**双轨划分原则（延续既有 RAG 系统约定）：**

- 向量库存**小说原文片段**（供风格模仿参照）；StyleBible / 角色 / 情节层是**结构化提炼**存 MySQL。与现有「结构化事实走 SQL、叙事走向量」一致。
- **向量库用 pgvector**（模板层先落地 pgvector，项目后续整体从 Redis Stack 迁到 pgvector）。为迁移铺路，向量存储抽成 `VectorStore` 接口（见 §6），模板层只实现 pgvector 一种后端。
- 向量行必须带租户前缀 `tmpl:{template_id}:u{user}:p{player}:`，避免多用户 / 多模板互相覆盖（呼应既有 code review 踩过的租户前缀坑）。pgvector 中该前缀作为主键/唯一约束的组成部分。

## 3. 长文处理：embedding 加速的分层归并

### 3.1 难点

- 10 万字 ≈ 15–18 万 token，远超单次上下文，必须切块。
- 独立提取会**丢跨块信息**（同一角色跨章、主线连贯性）。
- 纯 map-reduce 的一次性 reduce 又会撑爆上下文。
- 核心难点：**在有限上下文里保持全局连贯性**，同时控制 LLM 调用量。

### 3.2 关键决策

**Embedding 规格（与既有 RAG 约定对齐）：**

- 模型：本地 `bge-small-zh-v1.5`，**512 维**，相似度 **COSINE**。
- pgvector 向量列声明为 `vector(512)`，索引用 **HNSW + `vector_cosine_ops`**，与 bge 的 512 维 / COSINE 对齐。
- **前置依赖**：`Recall/embedding/` 目录目前为空（仅 `__init__.py`，加载器尚未实现）。模板层需要一个 bge 加载器 + `encode`（带 batch）。实现时优先**与 Recall 共用同一 embedding 模块**（落地在 `Recall/embedding/`），而非在 `StoryTemplate/` 内另起一份，避免两处模型加载重复。这一项在实现计划中标为前置任务。

**embedding 能做/不能做：** embedding 只算语义相似度，**不能生成/提炼**结构化内容。因此：

- 可用 embedding：判断两块是否同一事件、桥段聚类去重、角色归并、筛选事件块。**零 LLM、本地秒级、成本可忽略**。
- 必须 LLM：从文字提炼风格标签 / 角色 persona / 事件概要、把多片段归并成设定。

**采样粒度（已选：中度方案）：** embedding 负责去重 / 聚类 / 筛事件块；**风格与角色仍逐块提炼保证不漏**。目标 LLM 调用量 ~50 次（10 万字），比纯分层归并（~100 次）省约一半，同时避免长尾小角色 / 冷门桥段漏采。

### 3.3 分层归并流水线

```
                        小说全文 (10万字+)
                             │
  Level 0: 切块 (TemplateChunker)
  · 优先按章节标记切（正则 "第X章/卷"）；无标记则 ~2000 字滑窗
  · 每块带 chunk_id + order_index + 原文
  · 全部 chunk 做 embedding（本地，≈免费）
                             │
  Level 1: Map — 逐块局部信号 (ChunkSignal)
  · 风格：逐块提炼（中度方案，不采样，保证不漏）
  · 角色：逐块提炼出现的角色 + 行为片段（逐块，保证不漏）
  · 情节：先用 embedding 筛出"事件块"（与事件/冲突/转折语义近），
          只对事件块提炼事件概要（跳过纯环境/闲聊块）
                             │
  Level 2: 向量聚合（尽量零 LLM）
  · 桥段去重：向量聚类，相似片段归为一类 → 抽象成一个 PlotBeat
  · 角色合并：同名 + 向量相似度双 key 合并跨块特征，取高频/高显著特征
  · 风格聚合：各块风格标签投票统计，得稳定全局风格
                             │
  Level 3: 全局归并 (FinalReduce) — 四类产物各 1 次 LLM 收尾
  · StyleBible          ← 全局风格投票 + 世界观设定汇总
  · CharacterArchetype  ← 跨块合并后的角色特征
  · PlotBeat            ← 聚类去重后的桥段 → 抽象成可复用桥段
  · PlotSkeleton        ← 事件按 order_index 排序 → 主线骨架
```

### 3.4 保持全局连贯性的手段

- **order_index 全程透传**：chunk → signal → digest 都带顺序号；PlotSkeleton 最终按 order 排序，主线 A→B→C 不乱。
- **角色跨块合并键**：同名 + 向量相似度双 key，避免"第 3 章张三"与"第 80 章张三"被当成两人。
- **风格投票聚合**：各块风格样本统计高频标签，得稳定全局风格，不被个别章节带偏。

### 3.5 规模自适应与调用量

- 可配置参数：`chunk_size`（默认 ~2000 字）、`group_size`（默认 10 块/组）、`max_levels`（默认 3，超了继续递归组间归并）、`event_block_threshold`（事件块筛选相似度阈值）。
- 块数很多（如 300 块）时自动多加一层组间归并，**层数随规模自适应**。

**10 万字调用量估算（中度方案）：**

| 阶段 | 说明 | LLM 调用 |
|------|------|:---:|
| 全块 embedding | 本地 bge，≈免费 | 0（本地 ~90 次） |
| Level 1 风格+角色逐块提炼 | 保证不漏 | ~35–45 |
| Level 1 事件块提炼 | 仅筛出的事件块 | 含在上一行采样内 |
| Level 2 向量聚合/去重 | 纯向量 | ~0 |
| Level 3 全局归并 | 四类产物各一次 | ~4 |
| **LLM 总计** | | **~50** |

- 一次导入发生，结果持久化；重开游戏直接读表，不再调 LLM。

### 3.5.1 Level 1 并行执行（MVP 即启用）

块之间相互独立，Level 1 直接并行 fan-out，不再"先串行"。按 `~/CLAUDE.md` 的多 agent 约定：多个提炼 agent 各领一批块，完成后把结果汇总回主流程。

工程约束：

- **并发上限** `max_concurrency`（默认 5，可配置）：受 API 限流约束，避免打爆后端。
- **结果归位**：每个提炼结果带 `chunk_id` + `order_index`，汇总时按序归位，再进 Level 2/3。乱序返回不影响连贯性。
- **部分失败隔离**：单块失败独立重试（沿用 `_execute_with_retry` 两次），重试仍失败则标记该块跳过并记录，不拖垮整批；跳过块数超过阈值 `max_failed_ratio`（默认 20%）才整体失败。
- Level 2 向量聚合、Level 3 全局归并依赖上一层输出，需等 Level 1 全部汇总后进行；Level 3 四类产物之间也相互独立，可并行。

### 3.6 权衡（已知代价）

- 事件块筛选可能漏掉极冷门的主线事件（阈值可调）。中度方案已对风格/角色不采样，情节层保留少量漏采风险，`event_block_threshold` 可放宽以更全。
- 引入聚类逻辑，比纯 map-reduce 略复杂，多一个聚类调参旋钮。
- 并行引入并发控制与部分失败处理复杂度；用 `max_concurrency` + `max_failed_ratio` 两个旋钮兜底。

## 4. 数据结构（四类产物）

沿用 `PlayerWriter/PlaywriterSchema.py` 的 JSON-schema 风格。分表存储，四张表挂在 `story_template` 主表下。

### 主表 story_template
`template_id, user_id, source_title, created_at`

### ① StyleBible（风格 + 世界观，每模板单条，始终注入）
```python
class StyleBible(TypedDict):
    # 写作风格
    narrative_voice: str          # 叙事人称/视角
    tone_tags: list[str]          # 语气标签（冷峻、诙谐、古雅…）
    prose_rhythm: str             # 句式节奏（长句铺陈 / 短句凌厉）
    signature_devices: list[str]  # 标志性手法（环境白描、内心独白…）
    # 世界观设定
    world_premise: str            # 世界观一句话核心
    cultivation_system: str       # 修炼体系（境界划分、灵根规则）
    factions: list[str]           # 主要势力/门派
    key_locations: list[str]      # 标志性地点
    world_rules: list[str]        # 硬设定/禁忌（不可违反的世界规则）
    lexicon: list[str]            # 专有名词/术语表（保持用词一致）
```

### ② CharacterArchetype（角色原型，多条，仅参照，不自动实例化）
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
    tags: list[str]               # 检索标签（冲突类型、情绪、场景）
    summary: str                  # 桥段概要（抽象到可复用，去掉专有情节）
    dramatic_function: str        # 戏剧功能（转折/铺垫/高潮）
    reusable_conflict: str        # 可复用的核心冲突
```

`summary` **抽象化处理**：去掉原著专有名词，只留冲突结构，避免照搬、更贴合"参照而非复刻"的定位。

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

## 5. 注入机制（生成时按需调用）

在 `PlayerWriter/PlayerWriterFormatter.py` 的各 `build_*_instruction` 中注入：

- **StyleBible 摘要**：始终注入（风格 + 世界观是全局约束）。
- **PlotBeat**：生成 scene candidates 时，按当前 beat/张力检索相关桥段作为灵感候选。
- **PlotSkeleton**：生成 outline / chapter expansion 时，按当前进度（章节序号）挑对应骨架节点作为主线参考。
- **原文风格片段**（可选）：从向量库检索与当前场景语义近的原文片段，供风格模仿。

注入是**建议性**的：Playwright 仍原创，模板作为约束 + 灵感，不强制照搬。

## 5.5 架构约束（解耦与对外服务）

`StoryTemplate` 是一个**对外提供服务的独立模块**，不与 easy_game 内部强耦合。核心原则：

### 5.5.1 对外统一 Facade

对外只暴露一个门面 `StoryTemplateService`，隐藏内部分层与流水线细节。外部（含 easy_game 的 Playwright 层、未来其他调用方）只依赖这一个入口：

```python
class StoryTemplateService:
    def import_novel(self, *, user_id, player_id, source_title, text) -> str: ...
        # 执行 切块→并行提取→归并→分表持久化→片段入向量库；返回 template_id
    def get_style_bible(self, template_id) -> StyleBible: ...
    def suggest_plot_beats(self, template_id, *, query, top_k) -> list[PlotBeat]: ...
    def next_skeleton_nodes(self, template_id, *, chapter_hint) -> list[PlotSkeletonNode]: ...
    def search_style_passages(self, template_id, *, query_vector, top_k) -> list[str]: ...
```

内部子模块（Chunker / ExtractAgent / ParallelRunner / Embedding / Store / Injection）**不对外直接暴露**。

### 5.5.2 面向接口 + 依赖注入

所有跨边界的协作对象都以**抽象接口**声明，由构造时注入，便于单测替换与后续迁移：

- `VectorStore`（抽象）→ `PgVectorStore`（实现）：向量存储可替换后端。
- `EmbeddingModel`（抽象）→ bge 实现：向量化可替换/可 mock。
- `LLMClient`（复用现有 `BaseAgent`）：提取 Agent 依赖注入，测试用 fake。
- `TemplateRepository`（抽象）→ MySQL 实现：四张分表持久化可替换。

`StoryTemplateService` 通过构造函数接收这些依赖（默认在工厂里装配，参照 `ComponentFactory` 的延迟构造风格），不在内部 `import` 具体实现。

### 5.5.3 与 easy_game 的边界

- 依赖方向**单向**：easy_game（Playwright 层）依赖 `StoryTemplateService` 接口；`StoryTemplate` **不反向依赖** easy_game 的 GameState / Graph 等运行时结构。
- 注入接入点（§5）通过 `TemplateInjection` 适配：把 Service 返回的模板产物转成 Playwright 指令片段，**适配逻辑放在 easy_game 侧**，模板模块只输出纯数据（TypedDict），不关心 Playwright 的 prompt 格式。
- 数据契约是纯 TypedDict（§4），无框架耦合，可被任意外部调用方消费。

### 5.5.4 可测试性

- 每个子模块单一职责、可独立单测（切块、聚类、归并、持久化、注入分开测）。
- Service 层用注入的 fake 依赖做集成测试，不触碰真实 LLM / DB / 向量库。
- 遵循 TDD：先写接口契约测试，再写实现。

## 6. 模块划分（StoryTemplate 子包）

```text
StoryTemplate/
├── __init__.py                # 只导出 StoryTemplateService + 数据契约（对外表面）
├── StoryTemplateService.py    # 对外 Facade：import_novel / suggest_* / search_*（唯一入口）
├── interfaces.py              # 抽象接口：VectorStore / EmbeddingModel / TemplateRepository
├── TemplateSchema.py          # 四类产物的 TypedDict + JSON schema（对应 §4，纯数据契约）
├── TemplateChunker.py         # 长文切块 + order_index
├── TemplateExtractAgent.py    # 分层归并提取（BaseAgent + _execute_with_retry）
├── TemplateParallelRunner.py  # Level 1 并行 fan-out：并发上限 + 结果归位 + 部分失败隔离
├── TemplateEmbedding.py       # EmbeddingModel 实现：bge-small-zh 向量化、聚类、去重、事件块筛选
├── PgVectorStore.py           # VectorStore 的 pgvector 实现（项目迁移目标后端）
├── TemplateRepository.py      # TemplateRepository 的 MySQL 实现（四张分表持久化）
└── factory.py                 # 装配 Service + 注入默认实现（延迟构造，参照 ComponentFactory）
```

内部子模块（Chunker / ExtractAgent / ParallelRunner / Embedding / Store 等）不对外暴露，只经 `StoryTemplateService` 使用。抽象接口集中在 `interfaces.py`，具体实现按接口注入。

`TemplateInjection`（把模板产物转成 Playwright 指令片段的适配逻辑）**放在 easy_game 侧**，不在本子包内 —— 模板模块只输出纯数据，不关心 prompt 格式（见 §5.5.3）。

## 7. 与既有约定的一致性

- 中文回复 + 中文注释。
- 按模块分子包（`StoryTemplate/`）。
- TDD：先写测试再实现。
- 按内容拆分 commit，不 push。
- 复用既有 bge-small-zh 向量化基建与 Recall 向量库约定（租户前缀）；向量后端本设计用 pgvector，通过 `VectorStore` 接口为项目整体迁移铺路。
- 对外服务化解耦：单一 Facade（`StoryTemplateService`）+ 面向接口 + 依赖注入 + 单向依赖（见 §5.5），保证可被外部调用、可单测、可替换实现。

## 8. MVP 边界与后续

- **MVP**：Level 1 并行执行（并发上限 + 部分失败隔离）；中度采样；四类产物 + 四张分表（MySQL）+ pgvector 向量存储 + 注入接口跑通。
- **后续优化**：采样率/簇数/并发数可配置调优；向量库原文片段检索接入注入；Recall 回忆系统迁移到 pgvector（复用本设计的 `VectorStore` 接口）。
