from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

"""跨模块共享的纯数据契约：可检索文档与打分结果，无框架耦合。"""


@dataclass(frozen=True)
class VectorDoc:
    """一条可检索文档的通用表示。

    把 Recall 的 RecallDoc 泛化为通用类型：稳定字段只留 doc_id / doc_type /
    text，业务特有的 user_id/player_id/scene_id/importance 等下沉到 metadata，
    使向量库、混合检索、各业务层都能消费同一契约。
    """

    doc_id: str
    doc_type: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredDoc:
    """检索结果：文档 + 总分 + 分项因子（供重排透明可调）。"""

    doc: VectorDoc
    score: float
    factors: dict[str, float] = field(default_factory=dict)
