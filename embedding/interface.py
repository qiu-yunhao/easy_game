from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

"""embedding 抽象。独立第一层，不依赖向量库/数据库/数据结构，便于注入与 mock。"""


class EmbeddingModel(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度（bge-small-zh-v1.5 为 512）。"""

    @abstractmethod
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """把一批文本编码为向量，按输入顺序返回。"""
