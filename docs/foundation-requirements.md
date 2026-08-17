# 基础模块依赖说明

本项目基础模块体系（datatypes / db / vectordb / embedding / hybrid_retrieval）的运行与测试依赖。

## 系统依赖

- PostgreSQL 17 + pgvector 0.8.6
  - 启用扩展：`CREATE EXTENSION IF NOT EXISTS vector;`

## Python 包

| 包 | 用途 |
|----|------|
| SQLAlchemy>=2.0 | db 模块 engine/session 封装、vectordb 表定义 |
| psycopg[binary] | PostgreSQL 驱动（vectordb 连库） |
| pgvector | SQLAlchemy 的 Vector 列类型 + Python 适配 |
| sentence-transformers | 加载 bge-small-zh-v1.5（512 维，COSINE）；会带入 torch |

安装（国内建议用清华镜像加速 torch 下载）：

```bash
pip install "psycopg[binary]" pgvector
pip install sentence-transformers -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 测试库

- 连接串：`postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test`
- 首次运行 vectordb 集成测试前需建库并启用扩展：

```bash
psql -d postgres -c "CREATE DATABASE easygame_test;"
psql -d easygame_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## bge 模型下载

- embedding 集成测试首次运行会下载 `BAAI/bge-small-zh-v1.5`。
- 国内加速：设置环境变量 `HF_ENDPOINT=https://hf-mirror.com` 后再跑测试。

## 运行全部基础模块测试

```bash
# 纯逻辑 + 真 pgvector（不含 bge 下载）
python3 -m unittest \
  tests.test_datatypes tests.test_db_foundation tests.test_vectordb_pgvector \
  tests.test_embedding_interface tests.test_hybrid_rrf tests.test_hybrid_rerank \
  tests.test_hybrid_retriever tests.test_persistence_db_injection

# 真下载 bge 模型
HF_ENDPOINT=https://hf-mirror.com python3 -m unittest tests.test_embedding_bge
```

## StoryTemplate（小说模板提取）附加依赖

### 环境配置文件

运行时配置集中在项目根 `.env`（已 gitignore，不入库），模板见 `.env.example`。
`BaseAgent.py` 已 `load_dotenv()`，LLM 变量名固定为 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL_ID/LLM_TIMEOUT_SECONDS`。
StoryTemplate 的连接串从 `.env` 的 `MYSQL_URL/PG_URL` 读取，不再散落硬编码。

- LLM 用 **DeepSeek**：`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL_ID=deepseek-chat`，
  `LLM_API_KEY` 填 DeepSeek 控制台的 `sk-xxx`。

### 启动完备性检查

`env_bootstrap.ensure_environment()` 加载 `.env` 并做「变量存在 + 真实连通性探测」，
任一必需项缺失即 fail-fast 抛 `EnvironmentError`（带中文修复指引）。各 `require_*`
开关可跳过无关分组：

```bash
python3 -c "from env_bootstrap import ensure_environment; print(ensure_environment())"
```

### Python 包

| 包 | 用途 |
|----|------|
| pymysql | MySQL 驱动（`mysql+pymysql://`），供 StoryTemplate 4 张结构化分表 |

### MySQL 测试库

- 本机 Homebrew MySQL 8，root 免密；连接串 `mysql+pymysql://root@localhost:3306/easygame_test`。
- 首次运行前置：

```bash
pip install pymysql
mysql -u root -e "CREATE DATABASE IF NOT EXISTS easygame_test CHARACTER SET utf8mb4;"
```
