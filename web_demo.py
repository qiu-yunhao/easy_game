from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from Narrator.NarrationPresets import DEFAULT_NARRATION_STYLE_PRESET, NARRATION_STYLE_GUIDANCE
import web_server
import web_session

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
    if str(args.database_url or "").strip():
        if GameSaveStore is None:
            missing_module = getattr(PERSISTENCE_IMPORT_ERROR, "name", "sqlalchemy")
            print(f"Stagebound 数据库依赖缺失：{missing_module}", flush=True)
            print(f"当前解释器：{sys.executable}", flush=True)
            print("请先在当前环境安装：python -m pip install sqlalchemy pymysql", flush=True)
            return 1
        try:
            save_store = GameSaveStore(str(args.database_url).strip())
            save_store.create_schema()
        except ModuleNotFoundError as exc:
            print(f"Stagebound 数据库初始化失败：缺少依赖 {exc.name}", flush=True)
            print(f"当前解释器：{sys.executable}", flush=True)
            print("请先在当前环境安装：python -m pip install sqlalchemy pymysql", flush=True)
            return 1
        except Exception as exc:
            print(f"Stagebound 数据库初始化失败：{exc}", flush=True)
            return 1

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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


__all__ = [
    "load_project_dotenv",
    "main",
    "parse_args",
]


if __name__ == "__main__":
    raise SystemExit(main())
