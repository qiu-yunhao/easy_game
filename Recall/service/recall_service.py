from __future__ import annotations

from typing import Any, Protocol, Sequence

from datatypes import ScoredDoc, VectorDoc
from Recall.indexing.scene_indexer import build_scene_docs

"""回忆子系统服务层：编排「索引」与「查询」两条主链路。

本层不自研 embedding / 向量库 / 检索算法，全部靠依赖注入组合基础模块——
索引期用 EmbeddingModel + VectorStore，查询期用 HybridRetrieval。业务只面向
本服务的两个入口，不关心底层是 pgvector 还是别的后端，便于测试注入 fake。
"""


class _Embedding(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class _VectorStore(Protocol):
    def upsert(self, rows: Sequence[tuple[VectorDoc, list[float]]]) -> None: ...


class _Hybrid(Protocol):
    def search(
        self,
        query: str,
        *,
        top_k: int = ...,
        filters: dict[str, Any] | None = ...,
        weights: Any | None = ...,
        fetch_k: int = ...,
    ) -> list[ScoredDoc]: ...


class RecallService:
    """回忆索引与查询的统一编排入口。

    - 索引：把「已结束的幕」批量转成 VectorDoc → embed → upsert（幂等）。
    - 查询：粗召回（scene_summary 定位相关幕）→ 细召回（幕内 act_chunk 取片段）。
    """

    def __init__(
        self,
        *,
        embedding: _Embedding,
        vector_store: _VectorStore,
        hybrid: _Hybrid,
    ) -> None:
        self._embedding = embedding
        self._vector_store = vector_store
        self._hybrid = hybrid

    def index_completed_scenes(
        self,
        scenes: Sequence[dict[str, Any]],
        *,
        user_id: int,
        player_id: int,
        chunk_size: int = 4,
    ) -> None:
        """把一批已结束的幕批量索引进向量库。

        每项 scene 需含 history / scene_memory / scene_id / chapter_id。逐幕调
        build_scene_docs 生成双粒度 VectorDoc，汇总后一次性 embed 并 upsert；
        doc_id 带租户前缀且稳定，重复索引同一幕不会产生重复行（幂等）。
        空输入直接返回，不触发无谓的编码与写库。
        """
        docs: list[VectorDoc] = []
        for scene in scenes:
            docs.extend(
                build_scene_docs(
                    history=scene["history"],
                    scene_memory=scene["scene_memory"],
                    scene_id=scene["scene_id"],
                    chapter_id=scene["chapter_id"],
                    user_id=user_id,
                    player_id=player_id,
                    chunk_size=chunk_size,
                )
            )
        if not docs:
            return
        vectors = self._embedding.encode([doc.text for doc in docs])
        rows = list(zip(docs, vectors))
        self._vector_store.upsert(rows)

    def query_recall(
        self,
        query: str,
        *,
        user_id: int,
        player_id: int,
        top_k: int = 10,
        coarse_k: int = 5,
    ) -> list[ScoredDoc]:
        """自然语言回忆查询：粗召回定位相关幕，再在幕内细召回行动片段。

        两阶段设计：先用 scene_summary 粗粒度快速圈定「哪几幕相关」，再仅在这些
        命中的幕内检索 act_chunk 细粒度片段，避免直接在海量片段上做全量检索。
        所有检索都强制带租户键（user_id/player_id）过滤，杜绝跨玩家串味。
        粗召回落空则直接返回空，不发起细召回。
        """
        tenant_filters = {"user_id": user_id, "player_id": player_id}

        # 1) 粗召回：在整幕摘要里定位相关的幕。
        coarse = self._hybrid.search(
            query,
            top_k=coarse_k,
            filters={**tenant_filters, "doc_type": "scene_summary"},
        )
        scene_ids = self._ordered_scene_ids(coarse)
        if not scene_ids:
            return []

        # 2) 细召回：逐个命中幕，在幕内检索行动片段。
        # PgVectorStore 的 filters 为单值等值，scene_id 是集合，故按幕分别查再合并。
        results: list[ScoredDoc] = []
        seen: set[str] = set()
        for scene_id in scene_ids:
            fine = self._hybrid.search(
                query,
                top_k=top_k,
                filters={**tenant_filters, "doc_type": "act_chunk", "scene_id": scene_id},
            )
            for scored in fine:
                if scored.doc.doc_id in seen:
                    continue
                seen.add(scored.doc.doc_id)
                results.append(scored)

        # 合并多幕结果后按分数降序，截断到 top_k。
        results.sort(key=lambda s: s.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _ordered_scene_ids(coarse: Sequence[ScoredDoc]) -> list[str]:
        """从粗召回结果里按命中顺序抽取去重后的 scene_id 列表。"""
        ordered: list[str] = []
        seen: set[str] = set()
        for scored in coarse:
            scene_id = scored.doc.metadata.get("scene_id")
            if not scene_id or scene_id in seen:
                continue
            seen.add(scene_id)
            ordered.append(scene_id)
        return ordered
