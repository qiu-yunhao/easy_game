from __future__ import annotations

import json
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from web_session import WebGameSession

if TYPE_CHECKING:
    from Persistence.Store import GameSaveStore


FRONTEND_ROOT = Path(__file__).resolve().parent / "frontend"


class StageboundHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        session: WebGameSession,
        save_store: GameSaveStore | None = None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.session = session
        self.save_store = save_store
        self.frontend_root = FRONTEND_ROOT
        self.session.bind_save_context(save_store=save_store)


class StageboundRequestHandler(BaseHTTPRequestHandler):
    server: StageboundHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._write_json(HTTPStatus.OK, self.server.session.get_state())
            return
        if parsed.path == "/api/players":
            user_id = self._as_int(parse_qs(parsed.query).get("user_id", [None])[0], field_name="user_id")
            self._write_json(HTTPStatus.OK, {"players": self.server.session.list_players_for_user(user_id)})
            return
        self._serve_frontend_asset(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        print(f"[Stagebound] 正在处理 {parsed.path}", flush=True)
        started_at = time.perf_counter()
        if parsed.path == "/api/action" and self._wants_event_stream():
            self._handle_action_stream(parsed.path, started_at)
            return
        try:
            status, payload = self._handle_post_api_request(parsed.path, self._read_json_body())
        except RuntimeError as exc:
            self._write_error_with_log(parsed.path, HTTPStatus.BAD_REQUEST, exc, started_at, label="请求失败")
            return
        except Exception as exc:
            self._write_error_with_log(parsed.path, HTTPStatus.INTERNAL_SERVER_ERROR, exc, started_at, label="未预期错误")
            return
        self._write_json_with_log(parsed.path, status, payload, started_at)

    def _wants_event_stream(self) -> bool:
        return "text/event-stream" in (self.headers.get("Accept", "") or "")

    def _handle_action_stream(self, path: str, started_at: float) -> None:
        try:
            payload = self._read_json_body()
        except RuntimeError as exc:
            self._write_error_with_log(path, HTTPStatus.BAD_REQUEST, exc, started_at, label="请求失败")
            return

        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            print("[Stagebound] 客户端在流开始前中断了连接。", flush=True)
            return

        def emit(entry: dict[str, Any]) -> None:
            self._write_sse_event("entry", entry)

        try:
            final_state = self.server.session.apply_player_action_streaming(
                str(payload.get("input", "")),
                emit,
            )
        except Exception as exc:
            self._write_sse_event("error", {"error": str(exc)})
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            print(f"[Stagebound] 流式行动失败：{path} -> {exc}，耗时 {elapsed_ms}ms", flush=True)
            return

        self._write_sse_event("done", final_state)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        print(f"[Stagebound] 已完成流式 {path}，耗时 {elapsed_ms}ms", flush=True)

    def _write_sse_event(self, event: str, data: dict[str, Any]) -> None:
        body = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            self.wfile.write(body.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            print("[Stagebound] 客户端在流写入过程中断了连接。", flush=True)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _bind_active_context(self, *, user_id: int, player_id: int | None) -> None:
        self.server.session.bind_save_context(
            save_store=self.server.save_store,
            user_id=user_id,
            player_id=player_id,
        )

    def _serve_frontend_asset(self, raw_path: str) -> None:
        relative_path = "index.html" if raw_path in {"", "/"} else raw_path.lstrip("/")
        candidate = (self.server.frontend_root / relative_path).resolve()
        try:
            candidate.relative_to(self.server.frontend_root.resolve())
        except ValueError:
            self._write_json(HTTPStatus.FORBIDDEN, {"error": "禁止越界访问路径。"})
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type, _ = mimetypes.guess_type(candidate.name)
        resolved_type = content_type or "application/octet-stream"
        if resolved_type.startswith("text/") or resolved_type == "application/javascript":
            resolved_type = f"{resolved_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", resolved_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(candidate.read_bytes())

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise RuntimeError("请求体必须是有效的 JSON。") from None
        if not isinstance(payload, dict):
            raise RuntimeError("JSON 请求体必须是一个对象。")
        return payload

    def _handle_post_api_request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        if path == "/api/users/ensure":
            user = self._require_save_store().ensure_user(
                username=str(payload.get("username", "") or ""),
                display_name=str(payload.get("display_name", "") or "") or None,
                password_hash=str(payload.get("password_hash", "") or "") or None,
            )
            self._bind_active_context(user_id=int(user["id"]), player_id=None)
            return HTTPStatus.OK, {"user": user}
        if path == "/api/action":
            return HTTPStatus.OK, self.server.session.apply_player_action(str(payload.get("input", "")))
        if path == "/api/reset":
            return HTTPStatus.OK, self.server.session.reset(**self._build_reset_kwargs(payload))
        if path == "/api/new-game":
            user_id = self._as_int(payload.get("user_id"), field_name="user_id")
            starter_story_templates = payload.get("starter_story_templates")
            if starter_story_templates is not None and not isinstance(starter_story_templates, list):
                raise RuntimeError("`starter_story_templates` 必须是一个 JSON 数组。")
            state = self.server.session.reset(**self._build_reset_kwargs(payload))
            result = self._require_save_store().create_new_game(
                user_id=user_id,
                slot_name=str(payload.get("slot_name", "") or "新存档"),
                session_snapshot=self.server.session.export_runtime_snapshot(),
                starter_story_templates=starter_story_templates,
                save_label=str(payload.get("save_label", "") or "") or None,
            )
            self._bind_active_context(user_id=user_id, player_id=int(result["player"]["id"]))
            return HTTPStatus.OK, {**result, "state": state}
        if path == "/api/save":
            user_id = self._as_int(payload.get("user_id"), field_name="user_id")
            player_id = self._as_int(payload.get("player_id"), field_name="player_id")
            result = self.server.session.save_player_session(
                user_id=user_id,
                player_id=player_id,
                save_kind=str(payload.get("save_kind", "") or "manual"),
                save_label=str(payload.get("save_label", "") or "") or None,
            )
            return HTTPStatus.OK, {**result, "state": self.server.session.get_state()}
        if path == "/api/load":
            user_id = self._as_int(payload.get("user_id"), field_name="user_id")
            player_id = self._as_int(payload.get("player_id"), field_name="player_id")
            return HTTPStatus.OK, self.server.session.load_player_session(user_id=user_id, player_id=player_id)
        return HTTPStatus.NOT_FOUND, {"error": "未知接口。"}

    def _require_save_store(self) -> GameSaveStore:
        if self.server.save_store is None:
            raise RuntimeError("数据库未配置，请先提供 --database-url 或 STAGEBOUND_DATABASE_URL。")
        return self.server.save_store

    def _build_reset_kwargs(self, payload: dict[str, Any]) -> dict[str, Any]:
        player_profile = payload.get("player_profile")
        if player_profile is not None and not isinstance(player_profile, dict):
            raise RuntimeError("`player_profile` 必须是一个 JSON 对象。")
        return {
            "mode": str(value) if (value := payload.get("mode")) is not None else None,
            "player_character": str(value) if (value := payload.get("player_character")) is not None else None,
            "player_profile": player_profile,
            "narration_style_preset": str(value) if (value := payload.get("narration_style_preset")) is not None else None,
        }

    def _as_int(self, value: Any, *, field_name: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"`{field_name}` 必须是整数。") from None

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> bool:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            print("[Stagebound] 客户端在响应写完前中断了连接。", flush=True)
            return False

    def _write_json_with_log(
        self,
        path: str,
        status: HTTPStatus,
        payload: dict[str, Any],
        started_at: float,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if self._write_json(status, payload):
            print(f"[Stagebound] 已完成 {path}，耗时 {elapsed_ms}ms", flush=True)
            return
        print(f"[Stagebound] {path} 的响应被客户端取消，耗时 {elapsed_ms}ms", flush=True)

    def _write_error_with_log(
        self,
        path: str,
        status: HTTPStatus,
        error: Exception,
        started_at: float,
        *,
        label: str,
    ) -> None:
        print(f"[Stagebound] {label}：{path} -> {error}", flush=True)
        self._write_json_with_log(path, status, {"error": str(error)}, started_at)
