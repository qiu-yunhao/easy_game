# easy_game

`easy_game` 是一个面向修仙题材互动叙事的 Python 项目。它把剧情规划、角色行动、导演调度、玩家输入解析、旁白生成、记忆压缩和存档查询拆成多个可替换模块，再通过 `Graph` 层串成一条可持续推进的游戏流程。

项目支持两种运行思路：

- `heuristic`：只使用本地启发式逻辑，适合测试、离线调试和验证状态流转。
- `agent-first` / `live`：优先使用 LLM Agent 生成剧情、角色行为和旁白；当部分 Agent 不可用时，部分节点会回退到启发式逻辑。

## 项目结构

```text
easy_game/
├── Actor/                 # NPC/玩家行动解析后的执行、关系与记忆更新
├── Director/              # 当前舞台调度：谁在场、谁响应、张力与导演提示
├── Graph/                 # 游戏流程编排：故事规划、回合循环、旁白、转场
├── History/               # 历史记录、摘要压缩、场景/编剧/导演记忆
├── Narrator/              # 旁白生成、旁白队列、风格预设与启发式兜底
├── Persistence/           # SQLAlchemy 存档模型、快照保存、读取和查询
├── PlayerControl/         # 玩家输入、语义解析、玩家工具调用
├── PlayerWriter/          # 故事前提、章节大纲、场景候选等剧情规划
├── SceneEnd/              # 场景/章节结束条件判断
├── Scheduler/             # 下一位行动者选择
├── StylisticPolish/       # 非语言动作和旁白文本润色
├── frontend/              # 浏览器端 UI
├── skills/                # 工具/技能说明，供玩家和故事 Agent 调用
├── tests/                 # 回归测试
├── BaseAgent.py           # OpenAI 兼容 Chat Completions 客户端封装
├── ComponentFactory.py    # Agent 与策略对象的延迟构造工厂
├── GameState.py           # 全局游戏状态 TypedDict 定义
├── session_bootstrap.py   # 默认角色、场景和运行依赖初始化
├── web_session.py         # Web 运行时会话封装
├── web_server.py          # HTTP API 与静态前端服务
├── web_demo.py            # Web 入口
└── demo_run.py            # 命令行 Demo 入口
```

## 核心状态模型

全局状态集中定义在 `GameState.py`，运行时所有节点都接收并返回一个新的 `GameState`。它的主要分区包括：

- `plot`：章节、场景、主线目标、大纲、修为阶段、章节归档等剧情层信息。
- `scene`：地点、时间、当前 beat、张力、在场角色、焦点角色等舞台信息。
- `characters`：每个角色的情绪、意图、已知事实、关系增量和角色记忆。
- `history`：已经发生的事件、发言和系统旁白。
- `runtime`：回合计数、下一步行动、待处理旁白队列、场景/章节结束状态。
- `scene_plan`：当前场景目标、必须发生/不能发生的事项、戏剧曲线和退出条件。
- `director_brief`：导演节点给出的本轮调度建议、开场/收束文本和舞台动作。
- `memory`：压缩后的场景记忆、编剧记忆、导演记忆和调度记忆。
- `player`：玩家控制角色、最后输入和解析后的玩家行动。

这种结构让每个节点只负责更新自己关心的状态片段，方便测试和替换实现。

## Graph 编排

`Graph.builder` 是主流程入口，负责把节点组合成子图：

- `build_story_authoring_subgraph`：生成故事前提、章节大纲、角色阵容，并在角色生成后修订大纲。
- `build_story_setup_subgraph`：执行故事创作，并生成开场旁白。
- `build_chapter_preparation_subgraph`：扩展当前章节、生成章节/场景开场、刷新记忆、生成场景候选。
- `build_scene_direction_subgraph`：导演更新舞台状态，然后调度器选择下一位行动者。
- `build_chapter_runtime_subgraph`：章节准备、场景调度、beat 执行、场景/章节转场。
- `build_game_graph`：把故事设置和章节运行串成完整游戏图。

`Graph.graph_compile` 会优先使用 `langgraph` 的 `StateGraph` 编译节点；部分 beat 子图也支持 `fallback_to_runner=True`，在缺少 `langgraph` 时按顺序在进程内执行。

## 一轮游戏流程

一个典型回合从 `session_bootstrap` 构造初始状态和依赖开始：

1. `build_default_character_profiles` 创建玩家角色档案。
2. `build_default_scene_config` 创建初始场景配置。
3. `build_default_state` 生成 `GameState`。
4. `build_graph_dependencies` 创建 `GraphDependencies`，其中包含 Agent、策略、历史管理器、玩家接口等依赖。

进入故事后，核心流程如下：

1. `prepare_story_setup` 生成故事前提、大纲、初始角色阵容，并写入开场旁白。
2. `prepare_chapter_turn` 扩展当前章节，并行准备章节/场景开场和场景候选，然后刷新历史记忆、更新导演 brief、调用调度器。
3. `scheduler_node` 根据当前舞台和 runtime 状态选出 `runtime.next_act`。
4. `beat_resolution_node` 进入 beat 循环，循环内部依次执行导演引导、角色行动、历史提交、上下文推进、旁白、修炼进度、场景结束判断和记忆刷新。
5. 如果轮到玩家，`resolve_player_turn_state` 会从玩家接口取输入，并用 `SemanticParserAgent` 或启发式逻辑解析成 `ResolvedAct`。
6. 如果轮到 NPC，`resolve_npc_turn_state` 会按角色类型选择 `L1ActorAgent`、`L2ActorAgent` 或通用 `ActorAgent`，不可用时回退到启发式行动。
7. `apply_resolved_act` 将行动落入历史、关系、情绪、短期/长期记忆等状态。
8. `narration_subgraph_node` 把行动队列转为旁白文本，并按配置的叙事风格进行生成或兜底。
9. `scene_end_node` 判断场景或章节是否结束。
10. `transition_subgraph` 在场景结束后触发上下文转场；章节结束时归档当前章节并推进到下一章。

简化后的流程图：

```mermaid
flowchart TD
    A["Bootstrap: profiles + scene_config + GameState"] --> B["Story setup"]
    B --> C["Chapter preparation"]
    C --> D["Director brief"]
    D --> E["Scheduler selects next_act"]
    E --> F{"Player turn?"}
    F -->|Yes| G["Parse player input"]
    F -->|No| H["Actor agent or heuristic act"]
    G --> I["Apply resolved act"]
    H --> I
    I --> J["Narration + polish"]
    J --> K["History/memory refresh"]
    K --> L{"Scene/chapter ended?"}
    L -->|No| E
    L -->|Scene ended| M["Scene transition"]
    L -->|Chapter ended| N["Archive + chapter transition"]
    M --> C
    N --> C
```

## Agent 与启发式回退

Agent 构造统一通过 `ComponentFactory.py` 完成，避免启动时直接导入所有大模块。运行依赖集中放在 `GraphDependencies`：

- `PlaywrightAgent`：生成故事前提、章节大纲、章节扩展和场景候选。
- `ActorCreateAgent`：创建或补充剧情角色。
- `DirectorAgent`：生成舞台调度、焦点角色、响应队列和导演旁白。
- `ActorAgent` / `L1ActorAgent` / `L2ActorAgent`：生成角色行动。
- `NarratorAgent`：把结构化行动转为旁白。
- `SemanticParserAgent`：把玩家自然语言输入解析成 `ResolvedAct` 或工具调用。
- `StylisticPolishAgent`：润色非语言动作和旁白片段。
- `HistorySummarizerAgent`：辅助历史压缩。

如果以 `heuristic` 模式运行，项目会使用本地规则生成剧情片段、角色行动、场景结束判断和玩家输入解析，测试也主要覆盖这些确定性路径。`agent-first` / `live` 模式依赖 `BaseAgent` 中的 OpenAI 兼容客户端，需要配置：

```env
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL_ID=...
LLM_TIMEOUT_SECONDS=300
```

## 玩家输入与工具系统

Web 会话由 `web_session.WebGameSession` 维护。它会在玩家提交动作时：

1. 自动推进 NPC 行动，直到轮到玩家或场景结束。
2. 检查玩家输入是否像工具请求，例如背包、状态、关系、任务、存档/读档。
3. 如果是工具请求，交给 `PlayerCommandToolRuntime` 执行，并把结果作为系统消息写入历史。
4. 如果是普通行动，把输入推入 `BufferedPlayerInterface`，再进入 `resolve_story_turn`。

工具定义集中在 `ToolSkillRegistry.py`，说明文本放在 `skills/`。当前内置工具能力包括：

- 查询背包：`query_inventory`
- 查询玩家状态：`query_player_status`
- 查询角色关系：`query_relation`
- 查询任务：`query_quests`
- 手动存档/读档：`save_checkpoint` / `load_checkpoint`
- 给故事 Agent 使用的场景、记忆和角色名单查询

## 存档层

`Persistence` 使用 SQLAlchemy 维护用户、存档槽、世界状态、角色实例、关系互动、任务和快照：

- `Models.py` 定义数据库表模型。
- `Store.py` 提供 `GameSaveStore`，负责建表、创建新游戏、保存/读取快照和查询玩家状态。
- `store_snapshot.py` / `store_sync.py` 负责运行时快照与数据库行之间的序列化和同步。
- `mysql_schema.sql` 提供 MySQL 表结构参考。

Web 模式默认只使用内存会话；传入 `--database-url` 或设置 `STAGEBOUND_DATABASE_URL` 后会启用数据库存档。

## 运行方式

先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

环境配置从 `easy_game/.env.example` 复制为 `easy_game/.env`，把 MySQL root
密码填到 `MYSQL_URL` 和 `STAGEBOUND_DATABASE_URL` 中的
`YOUR_MYSQL_PASSWORD` 位置。仅使用 MySQL 存档时，`PG_URL` 与
`STAGEBOUND_RECALL_DATABASE_URL` 可留空。

初始化 MySQL 库表（会读取 `.env`，自动 `CREATE DATABASE IF NOT EXISTS`）：

```powershell
python scripts/init_mysql.py
```

命令行 Demo：

```powershell
python demo_run.py --mode heuristic --rounds 3
```

交互式命令行 Demo：

```powershell
python demo_run.py --mode heuristic --interactive --player-character player
```

Web Demo：

```powershell
python web_demo.py --mode heuristic --host 127.0.0.1 --port 8000
```

启用数据库的 Web Demo：

```powershell
python web_demo.py --mode heuristic --database-url "mysql+pymysql://user:pass@host:3306/stagebound"
```

测试：

```powershell
python -m pytest
```

## 当前测试覆盖

测试集中在 `tests/`，覆盖了角色档案层、beat 执行、上下文场景交接、导演冲突调度、旁白风格、持久化保存读取、玩家工具、故事规划回退、文本格式回归和工具技能注册等路径。最近一次本地验证结果为：

```text
82 passed
```
