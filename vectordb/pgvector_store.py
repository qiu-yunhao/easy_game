from __future__ import annotations

from typing import Any, Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete as sa_delete,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from datatypes import ScoredDoc, VectorDoc
from vectordb.interface import DocWithVector, VectorStore

"""VectorStore 的 pgvector 实现。

向量列 vector(dim)（默认 512，对齐 bge），索引 HNSW + vector_cosine_ops（COSINE）。
doc_id 作主键保证幂等 upsert；行内含租户前缀（由调用方在 doc_id 里带上）。
metadata 存 JSONB，支持按 user_id/player_id/doc_type 等键过滤。
"""


class PgVectorStore(VectorStore):
    def __init__(self, database_url: str, *, table: str = "vector_docs", dim: int = 512) -> None:
        self.dim = dim
        self.engine = create_engine(database_url, future=True)
        self.metadata = MetaData()
        self.table = Table(
            table,
            self.metadata,
            Column("doc_id", String(256), primary_key=True),
            Column("doc_type", String(64), nullable=False),
            Column("text", Text, nullable=False),
            Column("meta", JSONB, nullable=False),
            Column("embedding", Vector(dim), nullable=False),
        )
        # HNSW + 余弦，与 bge 的 512 维/COSINE 对齐。
        self.hnsw_index = Index(
            f"{table}_embedding_hnsw",
            self.table.c.embedding,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
        with self.engine.begin() as conn:
            conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))
        self.metadata.create_all(self.engine)

    def reset(self) -> None:
        """删表重建，仅供测试用。"""
        self.metadata.drop_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))
        self.metadata.create_all(self.engine)

    def upsert(self, rows: Sequence[DocWithVector]) -> None:
        if not rows:
            return
        values = [
            {
                "doc_id": doc.doc_id,
                "doc_type": doc.doc_type,
                "text": doc.text,
                "meta": dict(doc.metadata),
                "embedding": vector,
            }
            for doc, vector in rows
        ]
        stmt = pg_insert(self.table).values(values)
        # 主键冲突则更新，保证同 doc_id 幂等（不产生重复行）。
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.table.c.doc_id],
            set_={
                "doc_type": stmt.excluded.doc_type,
                "text": stmt.excluded.text,
                "meta": stmt.excluded.meta,
                "embedding": stmt.excluded.embedding,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredDoc]:
        # 余弦距离操作符 <=>，distance 越小越近；score = 1 - distance。
        distance = self.table.c.embedding.cosine_distance(query_vector).label("distance")
        stmt = self.table.select().add_columns(distance)
        if filters:
            for key, value in filters.items():
                if key == "doc_type":
                    # doc_type 是顶层列而非 meta 键，按列等值过滤。
                    stmt = stmt.where(self.table.c.doc_type == str(value))
                else:
                    # 其余键按 JSONB 等值过滤：meta ->> key = value
                    stmt = stmt.where(self.table.c.meta[key].astext == str(value))
        stmt = stmt.order_by(distance).limit(top_k)
        with self.engine.connect() as conn:
            result = conn.execute(stmt).mappings().all()
        scored: list[ScoredDoc] = []
        for row in result:
            doc = VectorDoc(
                doc_id=row["doc_id"],
                doc_type=row["doc_type"],
                text=row["text"],
                metadata=dict(row["meta"]),
            )
            scored.append(ScoredDoc(doc=doc, score=1.0 - float(row["distance"])))
        return scored

    def delete(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        with self.engine.begin() as conn:
            conn.execute(sa_delete(self.table).where(self.table.c.doc_id.in_(list(ids))))
