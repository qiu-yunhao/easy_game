from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from Narrator.NarrationPresets import DEFAULT_NARRATION_STYLE_PRESET, NARRATION_STYLE_GUIDANCE
import web_server
import web_session
from StoryTemplate.factory import build_story_template_service

try:
    from Persistence.Store import GameSaveStore
    PERSISTENCE_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:
    GameSaveStore = None  # type: ignore[assignment]
    PERSISTENCE_IMPORT_ERROR = exc


PROJECT_ROOT = Path(__file__).resolve().parent
DOTENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_matching_quotes(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"} else value


def load_project_dotenv(dotenv_path: Path = PROJECT_ROOT / ".env") -> None:
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].strip() if line.lower().startswith("export ") else line
        line = line[5:].strip() if line.lower().startswith("$env:") else line
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), _strip_matching_quotes(value.strip())
        if DOTENV_KEY_PATTERN.match(key):
            os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动互动叙事前端和 API 服务。")
    parser.add_argument("--host", default="127.0.0.1", help="绑定的主机地址。")
    parser.add_argument("--port", type=int, default=8000, help="绑定的端口。")
    parser.add_argument(
        "--database-url",
        default=os.getenv("STAGEBOUND_DATABASE_URL", ""),
        help="数据库连接串。推荐 MySQL DSN，例如 mysql+pymysql://user:pass@host:3306/stagebound。",
    )
    parser.add_argument(
        "--recall-database-url",
        default=os.getenv("STAGEBOUND_RECALL_DATABASE_URL", ""),
        help="回忆(RAG)库连接串，需 Postgres（pgvector/pg_trgm），如 "
        "postgresql+psycopg://user:pass@host:5432/stagebound。留空则回忆功能不启用。",
    )
    parser.add_argument(
        "--mode",
        choices=("heuristic", "agent-first", "live"),
        default="agent-first",
        help="场景规划与解析的运行模式。",
    )
    parser.add_argument("--player-character", default="player", help="网页会话中由玩家控制的角色 id。")
    parser.add_argument(
        "--narration-style-preset",
        choices=tuple(NARRATION_STYLE_GUIDANCE),
        default=DEFAULT_NARRATION_STYLE_PRESET,
        help="旁白子图使用的文风预设。",
    )
    return parser.parse_args()


def _setup_recall(session, *, save_database, recall_url: str, embedding=None) -> object | None:
    """按需组装并绑定回忆栈到会话，返回已启动的索引器（未启用则 None）。

    触发条件：同时具备 save 库与非空 recall 连接串。用 DataAccess 收敛多库混排
    （存档=MySQL、回忆=Postgres），交 build_recall_stack 组装 RecallService +
    AsyncSceneIndexer；绑定到会话后启动后台索引 worker。任何异常都不拖垮主服务，
    降级为「回忆未启用」。返回的索引器供关闭时 stop()。
    """
    from db import DataAccess
    from Recall.service import build_recall_stack

    access = DataAccess(save_database=save_database, recall_url=recall_url)
    if not access.has_recall():
        return None
    factory_kwargs = {}
    if embedding is not None:
        factory_kwargs["embedding_factory"] = lambda: embedding
    service, indexer = build_recall_stack(access, **factory_kwargs)
    if service is None or indexer is None:
        return None
    session.bind_recall_service(service)
    session.bind_recall_indexer(indexer)
    indexer.start()  # 启动后台 worker：幕结束入队 → 串行 embed+upsert。
    return indexer


def _maybe_setup_story_template(session, *, mysql_url: str, pg_url: str, embedding=None) -> None:
    if not (str(mysql_url).strip() and str(pg_url).strip()):
        return
    service = build_story_template_service(
        mysql_url=str(mysql_url).strip(), pg_url=str(pg_url).strip(),
        embedding=embedding,
    )
    session.bind_story_template_service(service)


def main() -> int:
    load_project_dotenv()
    args = parse_args()
    try:
        session = web_session.WebGameSession(
            web_session.SessionConfig(
                mode=args.mode,
                player_character=args.player_character,
                narration_style_preset=args.narration_style_preset,
            )
        )
    except RuntimeError as exc:
        print(f"Stagebound 控制台启动失败：{exc}", flush=True)
        if args.mode in {"agent-first", "live"}:
            print("Agent-First 模式需要可用且已配置的 LLM 后端。", flush=True)
        return 1

    save_store = None
    save_database = None
    if str(args.database_url or "").strip():
        if GameSaveStore is None:
            missing_module = getattr(PERSISTENCE_IMPORT_ERROR, "name", "sqlalchemy")
            print(f"Stagebound 数据库依赖缺失：{missing_module}", flush=True)
            print(f"当前解释器：{sys.executable}", flush=True)
            print("请先在当前环境安装：python -m pip install sqlalchemy pymysql", flush=True)
            return 1
        try:
            from db import Database

            # 显式建一个存档 Database，供 GameSaveStore 与 DataAccess 共用同一连接来源。
            save_database = Database(str(args.database_url).strip())
            save_store = GameSaveStore(save_database)
            save_store.create_schema()
        except ModuleNotFoundError as exc:
            print(f"Stagebound 数据库初始化失败：缺少依赖 {exc.name}", flush=True)
            print(f"当前解释器：{sys.executable}", flush=True)
            print("请先在当前环境安装：python -m pip install sqlalchemy pymysql", flush=True)
            return 1
        except Exception as exc:
            print(f"Stagebound 数据库初始化失败：{exc}", flush=True)
            return 1

    # 回忆栈与情节模板共用同一个 bge 实例：首次真正需要时才加载权重（保住「没配就不加载」），
    # 之后两条路径复用，避免重复 Loading weights。
    _shared_embedding: list = []

    def _get_shared_embedding():
        if not _shared_embedding:
            from embedding import BgeEmbeddingModel

            _shared_embedding.append(BgeEmbeddingModel())
        return _shared_embedding[0]

    # 回忆栈：需存档库 + 非空 recall 连接串（Postgres）。启动失败仅降级，不拖垮主服务。
    recall_indexer = None
    recall_url = str(args.recall_database_url or "").strip()
    if save_database is not None and recall_url:
        try:
            recall_indexer = _setup_recall(
                session, save_database=save_database, recall_url=recall_url,
                embedding=_get_shared_embedding(),
            )
        except Exception as exc:
            print(f"Stagebound 回忆功能初始化失败（已降级为未启用）：{exc}", flush=True)
            recall_indexer = None

    template_mysql = os.environ.get("MYSQL_URL", "")
    template_pg = os.environ.get("PG_URL", "")
    template_enabled = False
    try:
        template_embedding = (
            _get_shared_embedding()
            if str(template_mysql).strip() and str(template_pg).strip()
            else None
        )
        _maybe_setup_story_template(
            session, mysql_url=template_mysql, pg_url=template_pg,
            embedding=template_embedding,
        )
        template_enabled = bool(str(template_mysql).strip() and str(template_pg).strip())
    except Exception as exc:  # noqa: BLE001 - 模板库故障仅降级,不拖垮主服务
        print(f"情节模板：启动失败已降级 -> {exc}", flush=True)

    server = web_server.StageboundHTTPServer(
        (args.host, args.port),
        web_server.StageboundRequestHandler,
        session,
        save_store=save_store,
    )
    print(f"Stagebound 控制台已启动：http://{args.host}:{args.port}")
    print(f"运行模式：{args.mode}")
    print(f"玩家角色：{args.player_character}")
    print("数据库模式：未启用（仅内存会话）" if save_store is None else f"数据库模式：已启用 -> {args.database_url}")
    print("回忆模式：未启用" if recall_indexer is None else f"回忆模式：已启用 -> {recall_url}")
    print("情节模板：未启用" if not template_enabled else "情节模板：已启用")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if recall_indexer is not None:
            recall_indexer.stop()  # 排空队列并停止后台 worker。
        server.server_close()
    return 0


__all__ = [
    "load_project_dotenv",
    "main",
    "parse_args",
]


if __name__ == "__main__":
    raise SystemExit(main())
