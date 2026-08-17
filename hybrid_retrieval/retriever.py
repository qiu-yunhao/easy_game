from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence

from datatypes import ScoredDoc
from hybrid_retrieval.rerank import RerankWeights, rerank
from hybrid_retrieval.rrf import rrf_fuse

"""端到端混合检索入口。

流程：query 经 embedding → 稠密 KNN；稀疏（关键词）检索 → 两路排名 RRF 融合 →
三因子重排 → 返回 ScoredDoc。业务层只传 query + 参数，不关心内部流程。
稀疏检索以可注入的回调声明，避免第二层绑死某个具体后端。

稀疏回调可返回两种形态（向后兼容）：
- list[str]：仅 doc_id 排名，融合时只能命中稠密已取回的文档；
- list[ScoredDoc]：带完整文档，融合时可为「仅稀疏命中」的文档补取，不再丢弃。
"""

SparseSearch = Callable[..., Sequence[str] | Sequence[ScoredDoc]]


class _Embedding(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class _VectorStore(Protocol):
    def search(
        self, query_vector: list[float], *, top_k: int = ..., filters: dict[str, Any] | None = ...
    ) -> list[ScoredDoc]: ...


class HybridRetrieval:
    def __init__(
        self,
        *,
        embedding: _Embedding,
        vector_store: _VectorStore,
        sparse_search: SparseSearch | None = None,
    ) -> None:
        self._embedding = embedding
        self._vector_store = vector_store
        self._sparse_search = sparse_search

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        weights: RerankWeights | None = None,
        fetch_k: int = 50,
    ) -> list[ScoredDoc]:
        # 1) 稠密：query → 向量 → KNN
        query_vec = self._embedding.encode([query])[0]
        dense_hits = self._vector_store.search(query_vec, top_k=fetch_k, filters=filters)
        dense_ids = [h.doc.doc_id for h in dense_hits]
        by_id: dict[str, ScoredDoc] = {h.doc.doc_id: h for h in dense_hits}

        # 2) 稀疏：关键词检索（可选）。回调可返回 doc_id 或完整 ScoredDoc；
        #    若返回完整文档，则登记进 by_id，供「仅稀疏命中」的文档在融合后补取。
        sparse_ids: list[str] = []
        if self._sparse_search is not None:
            for item in self._sparse_search(query, top_k=fetch_k, filters=filters):
                if isinstance(item, ScoredDoc):
                    sparse_ids.append(item.doc.doc_id)
                    by_id.setdefault(item.doc.doc_id, item)
                else:
                    sparse_ids.append(item)

        # 3) RRF 融合两路排名
        fused = rrf_fuse([dense_ids, sparse_ids], k=60)

        # 4) 组装 ScoredDoc + 三因子，交给重排
        candidates: list[ScoredDoc] = []
        for doc_id, rrf_score in fused:
            hit = by_id.get(doc_id)
            if hit is None:
                continue  # 仅稀疏命中且稀疏未带回文档实体：无法 hydrate，跳过。
            importance = float(hit.doc.metadata.get("importance", 0.0) or 0.0)
            recency = float(hit.doc.metadata.get("recency", 0.0) or 0.0)
            candidates.append(
                ScoredDoc(
                    doc=hit.doc,
                    score=rrf_score,
                    factors={
                        "relevance": rrf_score,
                        "recency": recency,
                        "importance": importance,
                    },
                )
            )
        reranked = rerank(candidates, weights=weights)
        return reranked[:top_k]
