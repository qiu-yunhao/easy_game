from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, Sequence

from db.access import DataAccess

"""回忆栈工厂：把分层基础模块组装成可用的 RecallService + AsyncSceneIndexer。

设计要点（对齐「组装」需求）：
- 多库混排靠 DataAccess：回忆用的 pg 连接串从 access.recall_url() 取，
  防重日志复用 access.database()（与存档同为 MySQL）。
- 回忆库可选：access.has_recall() 为 False 时直接返回 (None, None)，
  上层据此跳过、服务器仅凭存档库照常启动。
- embedding 重且可选：默认 embedding_factory 懒加载 BgeEmbeddingModel
  （其内部再懒加载 torch/sentence-transformers），只有真正配置回忆库时才实例化；
  测试可注入 fake，避免下载模型 / 依赖 torch。
- 向量库 / 稀疏检索 / embedding 三个工厂均可注入，面向接口 + 依赖注入，便于测试。
"""


class _EmbeddingLike(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class _VectorStoreLike(Protocol):
    def upsert(self, rows: Any) -> None: ...
    def search(self, query_vector: list[float], *, top_k: int = ..., filters: Any = ...) -> Any: ...


# 三个可注入工厂：默认走真实实现，测试注入 fake。
EmbeddingFactory = Callable[[], _EmbeddingLike]
VectorStoreFactory = Callable[[str], _VectorStoreLike]
SparseSearchFactory = Callable[[str], Optional[Callable[..., Any]]]


def _default_embedding_factory() -> _EmbeddingLike:
    """默认 embedding：懒加载 bge（此处才 import，未配置回忆库时完全不触发）。"""
    from embedding import BgeEmbeddingModel

    return BgeEmbeddingModel()


def _default_vector_store_factory(url: str) -> _VectorStoreLike:
    from vectordb import PgVectorStore

    return PgVectorStore(url)


def _default_sparse_search_factory(url: str) -> Optional[Callable[..., Any]]:
    from hybrid_retrieval.sparse import PgTrgmSparseSearch

    return PgTrgmSparseSearch(url)


def build_recall_stack(
    access: DataAccess,
    *,
    embedding_factory: EmbeddingFactory = _default_embedding_factory,
    vector_store_factory: VectorStoreFactory = _default_vector_store_factory,
    sparse_search_factory: SparseSearchFactory = _default_sparse_search_factory,
) -> tuple[Optional[Any], Optional[Any]]:
    """组装回忆栈，返回 (RecallService, AsyncSceneIndexer)。

    回忆库未配置时返回 (None, None)——此时连 embedding 都不实例化（完全可选）。
    组装顺序：embedding + PgVectorStore + PgTrgmSparseSearch → HybridRetrieval →
    RecallService；再配 RecallIndexLogStore（存档库）→ AsyncSceneIndexer。
    索引器由调用方负责 start()，本工厂只组装不启动。
    """
    recall_url = access.recall_url()
    if recall_url is None:
        return None, None

    # 延迟到确认已配置回忆库后再组装，避免无谓地加载重依赖。
    from hybrid_retrieval import HybridRetrieval
    from Persistence.recall_index_log_store import RecallIndexLogStore
    from Recall.service.async_indexer import AsyncSceneIndexer
    from Recall.service.recall_service import RecallService

    embedding = embedding_factory()
    vector_store = vector_store_factory(recall_url)
    sparse_search = sparse_search_factory(recall_url)

    hybrid = HybridRetrieval(
        embedding=embedding,
        vector_store=vector_store,
        sparse_search=sparse_search,
    )
    service = RecallService(
        embedding=embedding,
        vector_store=vector_store,
        hybrid=hybrid,
    )
    index_log = RecallIndexLogStore(access.database())
    indexer = AsyncSceneIndexer(recall_service=service, index_log=index_log)
    return service, indexer
