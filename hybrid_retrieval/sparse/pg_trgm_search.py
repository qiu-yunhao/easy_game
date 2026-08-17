from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB

from datatypes import ScoredDoc, VectorDoc

"""稀疏检索的 pg_trgm 实现：基于三元组的中文子串/近似匹配。

本机无 zhparser 等中文分词扩展，改用 pg_trgm——它把文本切成字符三元组建 GIN 索引，
对中文按「字符 n-gram」而非「词」匹配，无需分词即可做子串检索。中文无空格，
word_similarity/similarity 对「短查询 in 长文本」常给 0；故用 ILIKE 子串做召回门槛
（GIN + gin_trgm_ops 会加速 LIKE/ILIKE），再用 similarity 做相对排序。返回带完整
文档实体的 ScoredDoc，供上层混合检索为「仅稀疏命中」的文档补取。与向量库共用同一
张表（读 text/meta 列），不自建数据，只按 doc_id 复用稠密侧写入的行。
"""


class PgTrgmSparseSearch:
    def __init__(self, database_url: str, *, table: str = "vector_docs") -> None:
        self.engine = create_engine(database_url, future=True)
        self.metadata = MetaData()
        # 复用向量库同名表，仅声明稀疏检索用到的列（doc_id/doc_type/text/meta）。
        self.table = Table(
            table,
            self.metadata,
            Column("doc_id", String(256), primary_key=True),
            Column("doc_type", String(64), nullable=False),
            Column("text", Text, nullable=False),
            Column("meta", JSONB, nullable=False),
            extend_existing=True,
        )
        self.trgm_index = Index(
            f"{table}_text_trgm",
            self.table.c.text,
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        )
        with self.engine.begin() as conn:
            conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            # 表由向量库负责建；此处只补建 trigram 索引（幂等）。
            self.trgm_index.create(conn, checkfirst=True)

    def __call__(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredDoc]:
        """按子串召回 + 三元组相似度排序，返回带完整文档的 ScoredDoc（降序）。

        召回门槛：text 含 query 子串（ILIKE，走 GIN trigram 索引）。排序：
        similarity(query, text) 降序，同分按 doc_id 稳定排序，避免结果抖动。
        query 空直接返回空。
        """
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        score = func.similarity(cleaned, self.table.c.text).label("score")
        # ILIKE 子串作召回门槛；% 需转义以免被当通配符（子串语义）。
        pattern = "%" + cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = (
            self.table.select()
            .add_columns(score)
            .where(self.table.c.text.ilike(pattern, escape="\\"))
        )
        if filters:
            for key, value in filters.items():
                stmt = stmt.where(self.table.c.meta[key].astext == str(value))
        stmt = stmt.order_by(score.desc(), self.table.c.doc_id).limit(top_k)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            ScoredDoc(
                doc=VectorDoc(
                    doc_id=row["doc_id"],
                    doc_type=row["doc_type"],
                    text=row["text"],
                    metadata=dict(row["meta"]),
                ),
                score=float(row["score"]),
            )
            for row in rows
        ]
