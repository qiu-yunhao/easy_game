from __future__ import annotations

import copy
import logging
import queue
import threading
from typing import Any, Optional

from GameState import GameState
from Memory.store import MemoryStore

"""后台记忆压缩守护线程：非阻塞入队 state 快照 + 后台线程串行压缩。

仿 Recall/service/async_indexer.py 的 AsyncSceneIndexer：单守护 worker 线程、
非阻塞 enqueue、join 阻塞到队列排空、stop 投递哨兵 None 退出。差异仅在业务：
本类不做防重日志，而是把压缩结果 (blocks, new_last) 放入锁保护的 pending 槽，
供轮首 take_pending 取走合并。enqueue 时深拷贝 state 做隔离，后台压缩不触碰源快照。
压缩失败仅记日志、不写 pending，下轮可重试（compact 幂等）。
"""

_logger = logging.getLogger(__name__)

_PendingResult = tuple[list[Any], int]  # (all_blocks, new_last_compressed_turn)


class AsyncMemoryCompactor:
    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        recall_service: Any = None,
        user_id: Optional[int] = None,
        player_id: Optional[int] = None,
    ) -> None:
        self._store = memory_store
        self._recall = recall_service
        self._user_id = user_id
        self._player_id = player_id
        self._queue: "queue.Queue[Optional[GameState]]" = queue.Queue()
        self._pending: Optional[_PendingResult] = None
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._started = False

    def set_tenant(self, *, user_id: Optional[int], player_id: Optional[int]) -> None:
        self._user_id = user_id
        self._player_id = player_id

    def set_recall_service(self, service: Any) -> None:
        self._recall = service

    def start(self) -> None:
        """启动后台 worker 线程（守护线程，随主进程退出）。"""
        if self._started:
            return
        self._started = True
        self._worker = threading.Thread(
            target=self._run, name="memory-compactor", daemon=True
        )
        self._worker.start()

    def enqueue(self, state: GameState) -> None:
        """把 state 快照非阻塞入队；深拷贝做隔离，立即返回不阻塞调用方。"""
        self._queue.put(copy.deepcopy(state))

    def join(self) -> None:
        """阻塞直到队列中已入队的任务全部消费完（供测试与关闭前排空）。"""
        self._queue.join()

    def take_pending(self) -> Optional[_PendingResult]:
        """取走并清空 pending 压缩结果；无结果返回 None。"""
        with self._lock:
            result = self._pending
            self._pending = None
            return result

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
            snapshot = self._queue.get()
            try:
                if snapshot is None:
                    return  # 收到哨兵，退出 worker。
                prior_cursor = int(snapshot["memory"]["last_compressed_turn"])
                blocks, new_last = self._store.compact(snapshot)
                self._index_new_blocks(blocks, prior_cursor)
                with self._lock:
                    self._pending = (blocks, new_last)
            except Exception:  # 失败不写 pending，记日志，下轮重试（compact 幂等）。
                _logger.exception("后台记忆压缩失败")
            finally:
                self._queue.task_done()

    def _index_new_blocks(self, blocks: list[Any], prior_cursor: int) -> None:
        if self._recall is None or self._user_id is None or self._player_id is None:
            return
        new_blocks = [b for b in blocks if int(b.get("turn_end", 0) or 0) > prior_cursor]
        if not new_blocks:
            return
        try:
            self._recall.index_memory_blocks(
                new_blocks, user_id=self._user_id, player_id=self._player_id
            )
        except Exception:  # 索引失败不影响压缩结果落地
            _logger.exception("memory_block 索引失败")
