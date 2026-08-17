from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Optional, Protocol

"""幕结束时的异步索引器：非阻塞入队 + 后台线程消费。

为什么异步：bge 编码耗时，若在玩家动作主流程里同步 embed+upsert 会卡住交互。
故幕结束时只把单幕数据 put 进队列即返回，由后台 worker 线程串行消费——
消费前用防重日志查重（同一幕可能被流式/工具多路径触发），索引成功后落标；
索引失败不落标，保证下次仍可重试。单 worker 串行，天然无并发写冲突。
"""

_logger = logging.getLogger(__name__)


class _RecallService(Protocol):
    def index_completed_scenes(
        self, scenes, *, user_id: int, player_id: int, chunk_size: int = ...
    ) -> None: ...


class _IndexLog(Protocol):
    def is_indexed(self, *, player_id: int, scene_id: str) -> bool: ...
    def mark_indexed(self, *, player_id: int, scene_id: str) -> None: ...


class AsyncSceneIndexer:
    def __init__(self, *, recall_service: _RecallService, index_log: _IndexLog) -> None:
        self._service = recall_service
        self._log = index_log
        self._queue: "queue.Queue[Optional[dict[str, Any]]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> None:
        """启动后台 worker 线程（守护线程，随主进程退出）。"""
        if self._started:
            return
        self._started = True
        self._worker = threading.Thread(target=self._run, name="recall-indexer", daemon=True)
        self._worker.start()

    def enqueue(self, scene: dict[str, Any], *, user_id: int, player_id: int) -> None:
        """把一幕的提取结果非阻塞入队，立即返回，不阻塞调用方。"""
        self._queue.put({"scene": scene, "user_id": user_id, "player_id": player_id})

    def join(self) -> None:
        """阻塞直到队列中已入队的任务全部消费完（供测试与关闭前排空）。"""
        self._queue.join()

    def stop(self) -> None:
        """排空队列并停止 worker（投递哨兵 None 让 worker 退出）。"""
        if not self._started:
            return
        self._queue.join()
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._started = False

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return  # 收到哨兵，退出 worker。
                self._process(task)
            except Exception:  # 单幕失败不拖垮 worker，记日志后继续下一幕。
                _logger.exception("回忆索引后台任务失败")
            finally:
                self._queue.task_done()

    def _process(self, task: dict[str, Any]) -> None:
        scene = task["scene"]
        user_id = task["user_id"]
        player_id = task["player_id"]
        scene_id = scene["scene_id"]
        # 消费前查重：同一幕被多路径重复入队时只索引一次。
        if self._log.is_indexed(player_id=player_id, scene_id=scene_id):
            return
        # 索引成功后才落标；失败会向上抛到 _run 记日志，不写日志以便重试。
        self._service.index_completed_scenes(
            [scene], user_id=user_id, player_id=player_id
        )
        self._log.mark_indexed(player_id=player_id, scene_id=scene_id)
