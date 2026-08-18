# Web UI 重排设计 — Stagebound 修仙叙事台

**日期**: 2026-08-18
**状态**: 待实现
**范围**: 前端页面重排（入口/登录/选择/工作区）+ 后端补齐模板导入/列表/详情/选择接口 + 情节解析结果展示

## 背景与动机

`easy_game` 后端新增了三块能力：自动对话模式（`web_session.set_auto_mode` / `auto_step`，已接入 `web_server`）、情节解析（`StoryTemplateService.import_novel`）、情节样本模板检索（`suggest_plot_beats` / `next_skeleton_nodes` / `get_style_bible` 等）。

但当前前端（单文件 `frontend/index.html` + 62KB `app.js` + `styles.css`）是围绕"单页对话 + 存档中心"设计的：首页把 hero、存档中心、角色栏、聊天、JSON 三栏全堆在一屏，视觉凌乱；模板导入/查看/选择在前端**完全没有入口**，后端 `StoryTemplateService` 也只被独立脚本 `scripts/extract_novel_template.py` 调用，`web_server` 未暴露任何模板端点，`web_session` 依赖里 `story_template_service` 只是个 `None` 占位。

本次重排目标：把应用拆成清晰的多页流程，给模板能力一个完整可用的 UI 链路，并整理臃肿的前端代码。

## 页面流与信息架构

单页应用（SPA），前端路由（hash 或 history），页面间无刷新切换。四个逻辑页面：

```
① 入口过渡页 → ② 登录页 → ③ 选择页(侧边栏) → ④ 工作区(对话 / 模板库)
```

- **① 入口过渡页**：标题 + 氛围动画 + 单个「进入」按钮。轻量，点击进入登录页。
- **② 登录页**：输入账号名 → 连接账号（复用 `POST /api/users/ensure`，**轻量账号名模式，无密码**）。连接成功后展示该账号名下的**存档中心**（从旧首页搬来：存档槽列表、继续游戏、再开一局、手动存档）。
- **③ 选择页**：窄的**文字标签侧边栏**（约 130px，不要更宽），两个入口「💬 对话 / 📚 模板库」，底部显示当前账号。侧边栏在工作区内也常驻，用于切换两个工作区。
- **④a 对话工作区**、**④b 模板工作区**：见下。

## 组件与布局

### 对话工作区（chat-first）

- 聊天流为主，阅读区宽、居中。
- 角色卡 / 存档 / 背包放在**可收起**的次级栏（不再是常驻大三栏）。
- **JSON 调试面板收进折叠区**，默认折叠，联调时展开。
- 顶部工具条：`📚 选模板` 按钮 + 自动模式开关（复用 `/api/auto`、`/api/auto/step`）+ 当前模板标识。
- 保留现有对话/流式/自动逻辑，仅重排容器与视觉。

### 选模板弹窗（小弹窗）

- 对话页点 `📚 选模板` 打开，居中小型模态。
- 已有模板走 **grid 布局**卡片。
- 含「不用模板」项并**默认选中**；顶部/角标有**当前选择标识**。
- 可**清除已选模板**，清除后回到"不用模板"。
- 确认后：把 selected_template_id 存入会话，影响开局与续写。

### 模板工作区

- 左侧：**上传小说文件解析情节**。表单含来源标题 + 文件选择，调 `POST /api/templates/import`，展示解析阶段进度（分块 → 聚类 → 提取骨架）。
- 右侧：**已有模板 grid 卡片列表**（`GET /api/templates`），每卡显示来源标题 + 情节节点数等摘要。
- 点击模板卡片 → **详情大弹窗**（独立于选模板弹窗）：约占屏幕 **80%、居中、四周留白**、带模态遮罩。展示 `GET /api/templates/{id}` 返回的 style_bible / 情节节点(beats) / 角色骨架(skeleton)。

## 数据流

```
登录: 前端 → POST /api/users/ensure → 绑定 user_id
存档: 前端 → GET /api/players?user_id / POST /api/load|save|new-game (现有)
对话: 前端 → POST /api/action (SSE 流式，现有) / /api/auto* (现有)
模板导入: 前端上传 → POST /api/templates/import → import_novel → 返回 template_id
模板列表: 前端 → GET /api/templates → list_templates
模板详情: 前端 → GET /api/templates/{id} → style_bible + beats + skeleton
模板选择: 前端选中 → 随 /api/reset 或 /api/new-game 透传 selected_template_id
情节注入: reset/开局/续写时，若有 selected_template_id → suggest_plot_beats(query=章节意图) → 注入故事推进
```

## 后端改动

### 1. 模板列表能力（新增，当前缺失）

- `StoryTemplate/TemplateRepository.py`：新增 `list_templates() -> list[dict]`，返回 `[{id, source_title, beat_count, ...}]`（`SELECT` 模板表 + 关联计数）。
- `StoryTemplate/StoryTemplateService.py`：新增 `list_templates()` 透传 `self._repo.list_templates()`。

### 2. 把 StoryTemplateService 接进会话

- `web_session.py`：在依赖装配处用 `StoryTemplate/factory.build_story_template_service(...)` 构造服务并持有引用（目前 `Graph/dependencies.py:59` 只有 `story_template_service: StoryTemplateService | None = None` 占位）。
- 新增会话方法：`list_templates()`、`import_template(source_title, text, user_id)`、`get_template_detail(template_id)`、`set_selected_template(template_id | None)`。
- `reset()` 扩展：接受 `selected_template_id`，存入 `config`/会话状态；开局/续写在构造故事推进时，若有选中模板则调 `suggest_plot_beats` 注入情节节点。selected_template_id 也进 `export_runtime_snapshot` 以便存档。

### 3. 新增 HTTP 端点（`web_server.py`）

- `GET /api/templates` → `{templates: [...]}`（session.list_templates）
- `GET /api/templates/{id}` → `{style_bible, beats, skeleton}`（session.get_template_detail）
- `POST /api/templates/import` → body `{source_title, text, user_id}` → `{template_id}`（session.import_template）
- `/api/reset`、`/api/new-game` 的 `_build_reset_kwargs` 增加 `selected_template_id` 透传（可为 null = 清除）。
- 文件上传：前端把文本内容读出后以 JSON 传（沿用现有 `_read_json_body`），避免引入 multipart 解析。大文件的体积/超时后续再优化，不在本次范围。

## 前端改动（拆成多文件模块）

现有 `app.js`（62KB 单文件）随新增页面会更臃肿，本次**拆分为模块**（保持无构建、原生 ES Module `<script type="module">`）：

- `frontend/js/router.js` — hash 路由、页面切换
- `frontend/js/api.js` — 统一的后端调用封装（含现有 SSE 流式）
- `frontend/js/pages/entry.js` — 入口过渡页
- `frontend/js/pages/login.js` — 登录 + 存档中心
- `frontend/js/pages/chat.js` — 对话工作区（迁移现有对话/自动/JSON 逻辑）
- `frontend/js/pages/templates.js` — 模板工作区（上传解析 + grid 列表 + 详情大弹窗）
- `frontend/js/components/templatePickerModal.js` — 对话页选模板小弹窗
- `frontend/js/state.js` — 共享会话状态（user_id、当前存档、selected_template_id）
- `frontend/index.html` — 精简为路由挂载点
- `frontend/styles.css` — 重排，保留现有仙侠视觉基调，去掉三栏拥挤布局

拆分时逐块迁移现有逻辑，保证对话/流式/存档功能不回退。

## 错误处理

- 未连接账号时访问工作区 → 重定向回登录页。
- 模板导入失败（LLM/DB 异常）→ 弹窗提示，保留已填表单。
- 模板列表/详情为空 → grid 显示空态占位。
- 数据库未配置（`save_store is None`）→ 沿用现有 `_require_save_store` 报错语义。
- selected_template_id 指向已删除模板 → 注入时忽略、回退无模板。

## 测试

- 后端：`TemplateRepository.list_templates` 单测（含空表）；`StoryTemplateService.list_templates` 透传测试；新端点走现有 handler 测试模式（`GET /api/templates`、`GET /api/templates/{id}`、`POST /api/templates/import`）。
- 情节注入：`reset(selected_template_id=...)` 时 `suggest_plot_beats` 被调用、结果注入故事状态的单测。
- 前端：无构建环境，手动验收——四页流程跳转、对话不回退、模板上传/列表/详情弹窗、选模板弹窗的默认态/清除态。

## 非目标（YAGNI）

- 密码认证（沿用轻量账号名）。
- multipart 大文件上传与断点续传。
- 模板删除/编辑 UI（本次只做导入 + 查看 + 选择）。
- 模板对情节影响的高级策略（只做 `suggest_plot_beats` 基础注入）。
