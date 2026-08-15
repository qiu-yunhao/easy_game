from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

from datatypes import ScoredDoc, VectorDoc

"""向量存储抽象。纯基础设施，不含业务语义；只接收现成向量，不依赖 embedding。"""

DocWithVector = tuple[VectorDoc, list[float]]


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, rows: Sequence[DocWithVector]) -> None:
        """按 doc_id 幂等写入（文档 + 向量）。"""

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredDoc]:
        """余弦最近邻检索，可按 metadata 过滤，返回带分的结果。"""

    @abstractmethod
    def delete(self, ids: Sequence[str]) -> None:
        """按 doc_id 删除。"""
