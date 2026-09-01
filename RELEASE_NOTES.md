# easy_game 版本发布说明

> 当前版本：`4a574a1`（2026-09-01）  
> 对比基线：`61d89af`（2026-04-12）  
> 对比范围：`61d89af..4a574a1`  
> 变更规模：308 个文件，+43,789 / -5,022

> 说明：仓库在 2026 年 5 月没有新的提交，因此“截至 5 月的版本”对应的是 5 月之前最后一次提交 `61d89af`。本次发布说明以它为上一版本。

## 版本标识

| 项 | 上一版本 | 当前版本 |
| --- | --- | --- |
| Commit | `61d89af` | `4a574a1` |
| 日期 | 2026-04-12 | 2026-09-01 |
| Python 文件数 | 118 | 285 |
| 测试文件数 | 20 | 102 |
| 顶层目录数 | 15 | 29 |
| 主要形态 | 对话式叙事引擎 | Web 互动叙事平台 |

## 这次更新为什么是“大版本”

截至 5 月的版本已经具备 Actor / Director / Graph / History / Narrator / Persistence 等核心模块，但整体仍更像一个“会生成对话和剧情状态的后端”。当前版本在此基础上新增了 14 个顶层模块，把记忆、长期召回、向量检索、情节模板、世界观构建、前端工程化和评估体系都补齐了。

从代码结构看，这不是一次局部功能迭代，而是一次从“对话引擎”到“完整互动叙事产品”的版本跃迁。

## 新增顶层模块

| 新增目录 | 作用 |
| --- | --- |
| `Memory/` | 角色记忆的读写、在场过滤、Provider 抽象和 MemoryStore |
| `Recall/` | 回忆系统：场景切分、索引、异步索引器、召回服务 |
| `StoryTemplate/` | 小说/模板提取、聚类、持久化、检索服务 |
| `WorldSetting/` | 世界观设定、题材预设、校验、晋升判定和 World Builder |
| `datatypes/` | VectorDoc、ScoredDoc、租户前缀等共享数据契约 |
| `db/` | DatabaseConfig、Database、DataAccess 统一数据库访问层 |
| `embedding/` | EmbeddingModel 抽象与 BGE 中文向量实现 |
| `vectordb/` | VectorStore 抽象与 PgVectorStore 实现 |
| `hybrid_retrieval/` | RRF 融合、重排、稀疏检索和端到端检索入口 |
| `eval_rag/` | 检索/生成评测数据、指标、评分器和 CLI |
| `scripts/` | 初始化 MySQL、模板提取、RAG 评测、性能探针等脚本 |
| `Cultivation/` | 修炼领域插件化，从顶层 `Cultivation.py` 迁移而来 |
| `docs/` | 基础需求、RAG 进度、复盘和评测报告 |
| `.claude/` | GitNexus 相关技能与仓库协作配置 |

## 主要功能与代码结构变化

### 1. 角色与对话引擎重构

**上一版**：角色创建逻辑集中在根目录 `actor_create_agent.py`，修炼逻辑在顶层 `Cultivation.py`，对话逻辑集中在 `Graph/nodes.py`。

**这一版**：

- `actor_create_agent.py` 迁移并拆分为 `Actor/ActorCreateAgent.py`、`ActorCreateSchema.py`、`ActorCreatePrompt.py`、`ActorCreateHeuristics.py`。
- 新增 `CharacterRepository.py`，收敛角色档案写入入口。
- 删除 `SupportingSceneIntentPolicy.py`，相关策略被更明确的模块替代。
- `Graph/nodes.py` 拆分出 `dialogue_nodes.py`、`beat_nodes.py`，减少循环依赖。
- `Cultivation.py` 迁移为 `Cultivation/realms.py`，并新增 `Cultivation/progression.py`。
- 删除 `Actor/L2ActorAgent.py`，角色层级从 L1 / L2 / actor 收敛为 L1 / actor。

### 2. Graph 编排可扩展化与并行回合

**上一版**：beat 执行集中在 `Graph/beat_subgraph.py`，主流程相对固定。

**这一版**：

- 新增 `Graph/hookable_node.py`、`Graph/hooks.py`，把 beat 子图步骤改造成可注册 hook。
- 新增 `Graph/beat_nodes.py`、`Graph/beat_group.py`，支持多角色响应分组与组内并行生成。
- 新增 `Graph/conversation_controller.py`，抽取会话推进与停止条件。
- 新增 `Graph/dependencies.py`，集中管理 GraphDependencies。
- 新增 `Graph/dialogue_nodes.py`，玩家/角色对话路径更独立。
- 整轮输出支持逐条事件流式推送，并补充 `on_token` 级流式能力。

### 3. 记忆系统从“队列”升级为“在场感知 + 异步压缩”

**上一版**：记忆更接近 FIFO 队列，且存在三层角色记忆结构。

**这一版**：

- 新增 `Memory/` 包，包含 `provider.py`、`default_provider.py`、`scene_filter.py`、`store.py`、`context.py`。
- 新增 `History/MemoryRefreshPolicy.py`，把“是否压缩”抽成纯决策函数。
- 新增 `History/AsyncMemoryCompactor.py`，将历史压缩移到后台执行，玩家回合不再等待同步压缩。
- 历史条目新增 `on_stage`、`location_id` 在场快照，短期记忆按在场角色过滤。
- 角色记忆收敛为两层模型，删除旧的三层 `CharacterMemoryState` 测试和 L2 结构。
- 持久化读写通过 `MemoryStore` 归一化，减少记忆序列化与运行时状态的耦合。

### 4. 长期记忆与 RAG 召回体系

**上一版**：没有独立的长期召回基础设施。

**这一版**：

- 新增 `datatypes/`，定义 `VectorDoc`、`ScoredDoc` 和租户前缀。
- 新增 `db/`，提供统一数据库连接与 `DataAccess`。
- 新增 `embedding/`，支持 BGE 中文向量模型。
- 新增 `vectordb/`，提供 PgVector 存储。
- 新增 `hybrid_retrieval/`，支持稠密/稀疏召回、RRF 融合与重排。
- 新增 `Recall/`，包含场景索引、记忆块索引、异步索引器、召回服务和工厂。
- 新增 `eval_rag/`，覆盖检索指标、生成指标、QA 生成和评测 CLI。
- 玩家工具注册 `query_recall`，让游戏内可以直接进行回忆检索。
- Web 会话在幕结束时触发异步回忆索引，并通过 `recall_index_log_store` 防重。

### 5. 小说模板与情节模板系统

**上一版**：没有模板提取、存储和检索能力。

**这一版**：

- 新增 `StoryTemplate/` 包。
- `TemplateChunker.py` 负责卷章节回切块与复合顺序。
- `TemplateClustering.py` 负责桥段去重和角色相似度合并。
- `TemplateExtractAgent.py` 负责逐块信号提取和全局归并。
- `TemplateRepository.py` 提供 MySQL 分表持久化。
- `StoryTemplateService.py` 提供模板列表、详情和检索服务。
- 新增 `scripts/extract_novel_template.py`，支持从小说全文提取情节模板。
- 前端新增模板工作区，支持上传解析、列表和详情弹窗。

### 6. 前端从单文件迁移到 ES Module 架构

**上一版**：`frontend/app.js` 是一个大型单文件应用。

**这一版**：

- 删除 `frontend/app.js`。
- 新增 `frontend/js/` 目录，包含 `api.js`、`router.js`、`state.js`、`main.js`。
- 页面拆分为 `entry.js`、`select.js`、`chat.js`、`conversation.js`、`templates.js`。
- 组件拆分为 `templatePickerModal.js`、`templateDetailModal.js`。
- 前端从单文件 DOM 脚本演进为无构建原生 ES Module 结构。

### 7. Web 会话、自动模式和 API 扩展

**上一版**：Web 会话主要负责玩家动作处理、自动推进 NPC、基础存档和工具路由。

**这一版**：

- `web_session.py` 大幅扩展，新增模板服务绑定、自动模式、世界构建器、回忆触发和 writer review。
- 新增自动模式开关和逐拍推进：`/api/auto`、`/api/auto/step`。
- 新增模板相关端点：模板列表、导入、详情、选择。
- 新增 World Builder 端点：开始、回答、草稿查询、应用、引用。
- 新增 SSE 事件类型，使整轮输出可流式返回。
- 会话推进委托给 `ConversationController`，减少 WebGameSession 的私有流程方法。

### 8. WorldSetting 与世界观构建器

**上一版**：世界观设定没有独立数据契约，修仙等级散落在顶层修炼逻辑中。

**这一版**：

- 新增 `WorldSetting/` 包。
- `schema.py` 定义题材无关的世界设定数据契约。
- `validation.py` 提供设定校验。
- `xianxia_preset.py`、`wuxia_preset.py`、`infinite_flow_preset.py` 提供内置题材预设。
- `advancement.py` 提供四种晋升条件判断。
- `genre_factory.py` 支持题材工厂和题材列表。
- `builder.py` 提供多字段确认、草稿快照和顺序无关推进。
- `WorldBuilderAgent.py` 提供世界观构建 Agent。
- 前端新增世界观聊天式构建流程，支持流式、Markdown、草稿恢复和多字段填充。

### 9. 工程化与可运行性

**上一版**：没有 `requirements.txt`，数据库初始化和环境加载缺少统一入口。

**这一版**：

- 新增 `requirements.txt`。
- 新增 `.env.example`。
- 新增 `env_bootstrap.py`，统一加载和检查环境变量。
- 新增 `scripts/init_mysql.py`，自动初始化 MySQL 库表。
- 新增多个开发/评测脚本，包括 RAG 评测、模板提取、性能探针、流式粒度探针。
- 新增 GitNexus 技能文档，便于代码理解、影响分析和重构。

## 关键能力对比

| 能力 | `61d89af` | `4a574a1` |
| --- | --- | --- |
| 角色层级 | L1 / L2 / actor | L1 / actor |
| 角色创建逻辑 | 根目录单文件 | Actor 子包四件套 |
| 记忆模型 | FIFO + 三层角色记忆 | 在场过滤 + 两层模型 + 异步压缩 |
| 长期召回 | 无 | pgvector + 混合检索 + 异步索引 |
| 向量存储 | 无 | PgVectorStore |
| Embedding | 无 | BGE 中文向量模型 |
| 情节模板 | 无 | 提取、聚类、持久化、检索 |
| 世界观构建 | 无 | 题材预设 + World Builder + 聊天式填写 |
| 自动模式 | 基础 NPC 自动推进 | 显式自动模式 + 逐拍推进 + 章节暂停 |
| 前端架构 | 单文件 `app.js` | ES Module 多页面 |
| 流式输出 | 无 | 整轮流式 + token 级流式 |
| 数据库访问 | SQLAlchemy 存档为主 | 统一 Database / DataAccess |
| 测试规模 | 20 个测试文件 | 102 个测试文件 |

## 版本演进时间线

| 日期 | 主题 | 关键提交 |
| --- | --- | --- |
| 2026-08-12 | 并行 beat 响应组 | `7ee4445` 起 |
| 2026-08-13 | Graph hooks、回忆索引、Actor 拆分、流式输出 | `01c9696`、`522f962`、`534dedc`、`f9f731f` |
| 2026-08-14 | 角色三层记忆注入 | `220ff2c` 起 |
| 2026-08-15 | 基础模块：datatypes / db / embedding / vectordb / hybrid | `5747ea5` 起 |
| 2026-08-16 | 小说模板提取设计对齐 | `22fb34d` |
| 2026-08-17 | Recall 栈、模板提取、自动模式、环境加载 | `ec0d198` 起 |
| 2026-08-18 | RAG 评测、模板运行时注入 | `313f559` 起 |
| 2026-08-19 | 前端 ES Module 重构和模板工作区 | `b7b9588` 起 |
| 2026-08-20 | 记忆架构收敛与异步压缩 | `ab25c50` 起 |
| 2026-08-21 | L2 全局移除、长期 RAG、持久化收敛 | `23f7396` 起 |
| 2026-08-24 | 自动模式改用运行时标志 | `b699dd6` 起 |
| 2026-08-26 | 世界观设定与题材工厂 | `6768781` 起 |
| 2026-08-27 | 世界观 builder 工作流与题材选择 | `485bb1f` |
| 2026-09-01 | World Builder 聊天、Markdown、草稿恢复 | `94bac2a`、`4a574a1` |

## 删除与重命名

| 变更类型 | 旧路径 | 新路径 |
| --- | --- | --- |
| 重命名 | `actor_create_agent.py` | `Actor/ActorCreateAgent.py` |
| 重命名 | `Cultivation.py` | `Cultivation/realms.py` |
| 删除 | `Actor/L2ActorAgent.py` | 无 |
| 删除 | `SupportingSceneIntentPolicy.py` | 无 |
| 删除 | `frontend/app.js` | 拆分为 `frontend/js/*` |
| 删除 | `tests/test_actor_formatter_payload.py` | 拆分为多个 payload/recall 测试 |
| 删除 | `tests/test_character_memory_layers.py` | 替换为两层记忆模型测试 |

## 升级与兼容性提示

- 任何仍从根目录导入 `actor_create_agent` 的外部脚本应改为 `Actor.ActorCreateAgent`。
- 任何仍依赖 `frontend/app.js` 的部署方式应改为加载 `frontend/js/main.js`。
- 依赖旧 L2 角色分层的存档或调用方需要按 L1 / actor 两层模型处理。
- 数据库初始化现在应使用 `python scripts/init_mysql.py`，并先配置 `.env`。
- RAG / 召回 / 模板功能需要额外的 `PG_URL`、`STAGEBOUND_RECALL_DATABASE_URL` 等环境变量。

## 当前 README 需要同步的内容

当前 `README.md` 仍保留部分上一版结构描述，发布后建议更新：

- “项目结构”尚未列出 `Memory/`、`Recall/`、`StoryTemplate/`、`WorldSetting/`、`db/`、`embedding/`、`vectordb/`、`hybrid_retrieval/`、`eval_rag/` 等目录。
- NPC 回合描述仍提到 `L2ActorAgent`，但代码树中已删除该文件。
- “当前测试覆盖”仍写着 `82 passed`，按当前测试文件规模应重新运行并更新。
