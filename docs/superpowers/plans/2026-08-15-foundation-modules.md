# 基础模块体系（Foundation Modules）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 easy_game 散落在业务模块里的公用能力剥离成分层基础模块（datatypes / db / vectordb / embedding + hybrid_retrieval），供上层业务单向向下依赖。

**Architecture:** 第一层四个纯基础模块互不依赖（datatypes 纯数据契约、db 封装 SQLAlchemy engine/session、vectordb 抽象 VectorStore + pgvector 实现、embedding 抽象 EmbeddingModel + bge 实现）；第二层 hybrid_retrieval 端到端（稠密+稀疏→RRF→三因子重排）只依赖第一层。面向接口 + 依赖注入，基础模块绝不反向依赖业务模块。

**Tech Stack:** Python 3.12、SQLAlchemy 2.0、PostgreSQL + pgvector 0.8.6（`vector(512)` + HNSW `vector_cosine_ops`）、psycopg、bge-small-zh-v1.5（sentence-transformers）、unittest（真集成测试：真连本地 pgvector + 真下载 bge）。

**测试约定：** 沿用项目现有 unittest 风格，外部依赖用 `sys.modules.setdefault` 打桩。真集成测试连本地 `postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test`，bge 真下载真编码。中文注释/docstring，按内容拆 commit 不 push。

---

## Task 0: 环境与依赖

**Files:**
- Create: `docs/foundation-requirements.md`

- [ ] **Step 1: 建测试库 + 启用 pgvector**

Run:
```bash
psql -d postgres -c "CREATE DATABASE easygame_test;"
psql -d easygame_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d easygame_test -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';"
```
Expected: 输出 `0.8.6`（库若已存在则 CREATE DATABASE 报错可忽略）。

- [ ] **Step 2: 安装 Python 依赖**

Run:
```bash
pip install "psycopg[binary]" pgvector sentence-transformers
```
Expected: 三个包安装成功（sentence-transformers 会带入 torch，体积较大）。

- [ ] **Step 3: 验证依赖可导入**

Run:
```bash
python3 -c "import psycopg, pgvector, sentence_transformers, sqlalchemy; print('ok')"
```
Expected: 输出 `ok`。

- [ ] **Step 4: 写依赖说明**

`docs/foundation-requirements.md`：
```markdown
# 基础模块依赖说明

## 系统依赖
- PostgreSQL 17 + pgvector 0.8.6（`CREATE EXTENSION vector`）

## Python 包
- SQLAlchemy>=2.0
- psycopg[binary]（PostgreSQL 驱动）
- pgvector（SQLAlchemy 的 Vector 类型 + Python 适配）
- sentence-transformers（加载 bge-small-zh-v1.5，512 维，COSINE）

## 测试库
- 连接串：postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test
- 首次运行前需建库并 CREATE EXTENSION vector（见上）。
```

- [ ] **Step 5: Commit**

```bash
git add docs/foundation-requirements.md
git commit -m "docs(foundation): 基础模块系统/Python依赖说明"
```

---

## Task 1: datatypes 基础模块

**Files:**
- Create: `datatypes/__init__.py`, `datatypes/tenancy.py`, `datatypes/documents.py`
- Test: `tests/test_datatypes.py`

- [ ] **Step 1: 写失败测试**

`tests/test_datatypes.py`：
```python
from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from datatypes.tenancy import template_prefix, tenant_prefix


class TenancyTest(unittest.TestCase):
    def test_tenant_prefix_格式(self):
        self.assertEqual(tenant_prefix(1, 2), "u1:p2:")

    def test_template_prefix_在租户前追加模板段(self):
        self.assertEqual(template_prefix(7, 1, 2), "tmpl:7:u1:p2:")


class VectorDocTest(unittest.TestCase):
    def test_vector_doc_保存核心字段与元数据(self):
        doc = VectorDoc(
            doc_id="u1:p2:s1:scene_summary",
            doc_type="scene_summary",
            text="正文",
            metadata={"user_id": 1, "player_id": 2},
        )
        self.assertEqual(doc.doc_id, "u1:p2:s1:scene_summary")
        self.assertEqual(doc.metadata["user_id"], 1)

    def test_scored_doc_携带总分与分项因子(self):
        doc = VectorDoc(doc_id="d1", doc_type="act_chunk", text="t", metadata={})
        scored = ScoredDoc(doc=doc, score=0.9, factors={"relevance": 0.8, "recency": 0.5})
        self.assertAlmostEqual(scored.score, 0.9)
        self.assertEqual(scored.factors["relevance"], 0.8)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_datatypes -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'datatypes'`）。

- [ ] **Step 3: 实现 tenancy**

`datatypes/tenancy.py`：
```python
from __future__ import annotations

"""租户前缀约定（集中一处，杜绝各模块各写一份）。

云端多用户下 scene_id 由 chapter+序号拼成、各玩家共用同一套，若不加租户前缀，
不同玩家的同名场景会生成相同 doc_id，upsert 时互相覆盖造成跨租户数据丢失。
这是既有 code review 踩过的致命坑，故统一在此提供，所有模块必须复用。
"""


def tenant_prefix(user_id: int, player_id: int) -> str:
    """返回 ``u{user}:p{player}:`` 形式的租户前缀。"""
    return f"u{user_id}:p{player_id}:"


def template_prefix(template_id: int, user_id: int, player_id: int) -> str:
    """模板层在租户前缀前再加 ``tmpl:{template_id}:`` 段，隔离多模板。"""
    return f"tmpl:{template_id}:{tenant_prefix(user_id, player_id)}"
```

- [ ] **Step 4: 实现 documents**

`datatypes/documents.py`：
```python
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
```

- [ ] **Step 5: 实现包导出**

`datatypes/__init__.py`：
```python
from datatypes.documents import ScoredDoc, VectorDoc
from datatypes.tenancy import template_prefix, tenant_prefix

__all__ = ["ScoredDoc", "VectorDoc", "template_prefix", "tenant_prefix"]
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m unittest tests.test_datatypes -v`
Expected: PASS（4 个测试）。

- [ ] **Step 7: Commit**

```bash
git add datatypes/ tests/test_datatypes.py
git commit -m "feat(datatypes): VectorDoc/ScoredDoc + 租户前缀约定"
```

---

## Task 2: db 基础模块

**Files:**
- Create: `db/__init__.py`, `db/config.py`, `db/database.py`
- Test: `tests/test_db_foundation.py`

- [ ] **Step 1: 写失败测试**

`tests/test_db_foundation.py`：
```python
from __future__ import annotations

import unittest

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

from db import Database, DatabaseConfig

Base = declarative_base()


class _Row(Base):
    __tablename__ = "db_foundation_probe"
    id = Column(Integer, primary_key=True)
    name = Column(String(32))


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        # 用内存 SQLite 验证通用封装本身，不依赖具体后端。
        self.db = Database(DatabaseConfig(database_url="sqlite+pysqlite:///:memory:"))

    def test_create_all_建表后可读写(self):
        self.db.create_all(Base.metadata)
        with self.db.session() as s:
            s.add(_Row(id=1, name="张三"))
            s.commit()
        with self.db.session() as s:
            row = s.get(_Row, 1)
            self.assertEqual(row.name, "张三")

    def test_session_异常时回滚(self):
        self.db.create_all(Base.metadata)
        with self.assertRaises(ValueError):
            with self.db.session() as s:
                s.add(_Row(id=2, name="李四"))
                raise ValueError("boom")
        with self.db.session() as s:
            self.assertIsNone(s.get(_Row, 2))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_db_foundation -v`
Expected: FAIL（`No module named 'db'`）。

- [ ] **Step 3: 实现 config**

`db/config.py`：
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DatabaseConfig:
    """数据库连接配置，从业务类抽出的通用参数。"""

    database_url: str
    echo: bool = False
    pool_size: int | None = None
    max_overflow: int | None = None
```

- [ ] **Step 4: 实现 Database**

`db/database.py`：
```python
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.config import DatabaseConfig

"""SQLAlchemy engine/session 的通用封装。

只做连接与会话管理，不含任何业务表逻辑——存档表、角色表等仍留在 Persistence。
业务模块通过注入 Database 复用同一连接来源，不再各自 create_engine。
"""


class Database:
    def __init__(self, config: DatabaseConfig | str) -> None:
        self.config = (
            DatabaseConfig(database_url=config) if isinstance(config, str) else config
        )
        kwargs: dict[str, object] = {"echo": self.config.echo, "future": True}
        # 池参数按需透传；SQLite 内存库不接受池参数，故仅在显式配置时传入。
        if self.config.pool_size is not None:
            kwargs["pool_size"] = self.config.pool_size
        if self.config.max_overflow is not None:
            kwargs["max_overflow"] = self.config.max_overflow
        self.engine: Engine = create_engine(self.config.database_url, **kwargs)
        self._session_factory = sessionmaker(
            self.engine, expire_on_commit=False, future=True
        )

    def create_all(self, metadata) -> None:
        """按传入的 MetaData 建表；建哪些表由调用方（业务模块）决定。"""
        metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """会话上下文：正常退出不自动提交（由调用方 commit），异常回滚，末尾关闭。"""
        session = self._session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

- [ ] **Step 5: 实现包导出**

`db/__init__.py`：
```python
from db.config import DatabaseConfig
from db.database import Database

__all__ = ["Database", "DatabaseConfig"]
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m unittest tests.test_db_foundation -v`
Expected: PASS（2 个测试）。

- [ ] **Step 7: Commit**

```bash
git add db/ tests/test_db_foundation.py
git commit -m "feat(db): DatabaseConfig + Database(engine/session 通用封装)"
```

---

## Task 3: vectordb 基础模块（真连 pgvector）

**Files:**
- Create: `vectordb/__init__.py`, `vectordb/interface.py`, `vectordb/pgvector_store.py`
- Test: `tests/test_vectordb_pgvector.py`

- [ ] **Step 1: 写失败测试（真集成）**

`tests/test_vectordb_pgvector.py`：
```python
from __future__ import annotations

import unittest

from datatypes import VectorDoc
from vectordb import PgVectorStore, VectorStore

_URL = "postgresql+psycopg://qiuyunhao.1@localhost:5432/easygame_test"


def _vec(seed: float) -> list[float]:
    # 造一个方向可控的 512 维向量：前若干位置分不同 seed，方便断言最近邻。
    v = [0.0] * 512
    v[0] = seed
    v[1] = 1.0 - seed
    return v


class PgVectorStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PgVectorStore(_URL, table="vectordb_probe", dim=512)
        cls.store.reset()  # 每次测试重建表，保证幂等

    def test_是_VectorStore_子类(self):
        self.assertIsInstance(self.store, VectorStore)

    def test_upsert_后能按余弦最近邻检索(self):
        docs = [
            (VectorDoc("u1:p2:a", "act_chunk", "甲", {"user_id": 1}), _vec(0.9)),
            (VectorDoc("u1:p2:b", "act_chunk", "乙", {"user_id": 1}), _vec(0.1)),
        ]
        self.store.upsert(docs)
        hits = self.store.search(_vec(0.85), top_k=1)
        self.assertEqual(hits[0].doc.doc_id, "u1:p2:a")

    def test_upsert_幂等不重复(self):
        doc = (VectorDoc("u9:p9:x", "act_chunk", "丙", {}), _vec(0.5))
        self.store.upsert([doc])
        self.store.upsert([doc])  # 同 id 再写一次
        hits = self.store.search(_vec(0.5), top_k=10)
        ids = [h.doc.doc_id for h in hits]
        self.assertEqual(ids.count("u9:p9:x"), 1)

    def test_按_metadata_过滤(self):
        self.store.upsert(
            [
                (VectorDoc("f:1", "act_chunk", "p1", {"player_id": 1}), _vec(0.3)),
                (VectorDoc("f:2", "act_chunk", "p2", {"player_id": 2}), _vec(0.3)),
            ]
        )
        hits = self.store.search(_vec(0.3), top_k=10, filters={"player_id": 2})
        self.assertTrue(all(h.doc.metadata.get("player_id") == 2 for h in hits))
        self.assertIn("f:2", [h.doc.doc_id for h in hits])

    def test_delete_按_id_删除(self):
        self.store.upsert([(VectorDoc("del:1", "act_chunk", "d", {}), _vec(0.42))])
        self.store.delete(["del:1"])
        hits = self.store.search(_vec(0.42), top_k=50)
        self.assertNotIn("del:1", [h.doc.doc_id for h in hits])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_vectordb_pgvector -v`
Expected: FAIL（`No module named 'vectordb'`）。

- [ ] **Step 3: 实现抽象接口**

`vectordb/interface.py`：
```python
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
```

- [ ] **Step 4: 实现 PgVectorStore**

`vectordb/pgvector_store.py`：
```python
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
                # JSONB 按键等值过滤：meta ->> key = value
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
```

- [ ] **Step 5: 实现包导出**

`vectordb/__init__.py`：
```python
from vectordb.interface import DocWithVector, VectorStore
from vectordb.pgvector_store import PgVectorStore

__all__ = ["DocWithVector", "PgVectorStore", "VectorStore"]
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m unittest tests.test_vectordb_pgvector -v`
Expected: PASS（5 个测试，真连 easygame_test）。

- [ ] **Step 7: Commit**

```bash
git add vectordb/ tests/test_vectordb_pgvector.py
git commit -m "feat(vectordb): VectorStore 抽象 + PgVectorStore(vector512/HNSW余弦)"
```

---

## Task 4: embedding 基础模块（真下载 bge）

**Files:**
- Create: `embedding/__init__.py`, `embedding/interface.py`, `embedding/bge_model.py`
- Test: `tests/test_embedding_bge.py`, `tests/test_embedding_interface.py`

- [ ] **Step 1: 写接口契约测试（mock，不下载）**

`tests/test_embedding_interface.py`：
```python
from __future__ import annotations

import unittest

from embedding import EmbeddingModel


class _FakeModel(EmbeddingModel):
    @property
    def dimension(self) -> int:
        return 4

    def encode(self, texts):
        return [[float(len(t))] * 4 for t in texts]


class EmbeddingInterfaceTest(unittest.TestCase):
    def test_可被_mock_实现供上层单测(self):
        model = _FakeModel()
        self.assertEqual(model.dimension, 4)
        vecs = model.encode(["ab", "abc"])
        self.assertEqual(vecs, [[2.0] * 4, [3.0] * 4])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 写真下载集成测试**

`tests/test_embedding_bge.py`：
```python
from __future__ import annotations

import unittest

from embedding import BgeEmbeddingModel


class BgeEmbeddingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 真加载 bge-small-zh-v1.5（首次会联网下载）。
        cls.model = BgeEmbeddingModel()

    def test_维度为_512(self):
        self.assertEqual(self.model.dimension, 512)

    def test_encode_返回每条文本一个_512_维向量(self):
        vecs = self.model.encode(["修仙者踏入洞府", "商人递来一张地图"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 512)

    def test_语义相近文本余弦相似度更高(self):
        import math

        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb)

        v = self.model.encode(["他在酒馆喝酒", "他于客栈饮酒", "剑气纵横三万里"])
        self.assertGreater(cos(v[0], v[1]), cos(v[0], v[2]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行确认失败**

Run: `python3 -m unittest tests.test_embedding_interface -v`
Expected: FAIL（`No module named 'embedding'`）。

- [ ] **Step 4: 实现抽象接口**

`embedding/interface.py`：
```python
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
```

- [ ] **Step 5: 实现 bge**

`embedding/bge_model.py`：
```python
from __future__ import annotations

from typing import Sequence

from embedding.interface import EmbeddingModel

"""bge-small-zh-v1.5 本地加载与编码（512 维，COSINE 语义）。

延迟导入 sentence_transformers：抽象接口层不应因为可选重依赖（torch）而无法导入，
只有真正实例化 bge 实现时才加载模型。encode 归一化以贴合 COSINE 检索。
"""

_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


class BgeEmbeddingModel(EmbeddingModel):
    def __init__(self, model_name: str = _DEFAULT_MODEL, *, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,  # 归一化，配合余弦检索
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]
```

- [ ] **Step 6: 实现包导出**

`embedding/__init__.py`：
```python
from embedding.bge_model import BgeEmbeddingModel
from embedding.interface import EmbeddingModel

__all__ = ["BgeEmbeddingModel", "EmbeddingModel"]
```

- [ ] **Step 7: 运行确认通过**

Run:
```bash
python3 -m unittest tests.test_embedding_interface -v
python3 -m unittest tests.test_embedding_bge -v
```
Expected: 两个都 PASS（bge 测试首次会下载模型）。

- [ ] **Step 8: Commit**

```bash
git add embedding/ tests/test_embedding_interface.py tests/test_embedding_bge.py
git commit -m "feat(embedding): EmbeddingModel 抽象 + bge-small-zh 实现"
```

---

## Task 5: hybrid_retrieval 第二层模块

**Files:**
- Create: `hybrid_retrieval/__init__.py`, `hybrid_retrieval/rrf.py`, `hybrid_retrieval/rerank.py`, `hybrid_retrieval/retriever.py`
- Test: `tests/test_hybrid_rrf.py`, `tests/test_hybrid_rerank.py`, `tests/test_hybrid_retriever.py`

- [ ] **Step 1: 写 RRF 失败测试**

`tests/test_hybrid_rrf.py`：
```python
from __future__ import annotations

import unittest

from hybrid_retrieval.rrf import rrf_fuse


class RrfTest(unittest.TestCase):
    def test_两条排名靠前的文档融合分更高(self):
        dense = ["a", "b", "c"]
        sparse = ["b", "a", "d"]
        fused = rrf_fuse([dense, sparse], k=60)
        # a、b 在两路都靠前，应排在只在单路出现的 c/d 之前
        top2 = [doc_id for doc_id, _ in fused[:2]]
        self.assertIn("a", top2)
        self.assertIn("b", top2)

    def test_单路缺失的文档仍可入榜(self):
        fused = dict(rrf_fuse([["a"], ["b"]], k=60))
        self.assertIn("a", fused)
        self.assertIn("b", fused)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_hybrid_rrf -v`
Expected: FAIL（`No module named 'hybrid_retrieval'`）。

- [ ] **Step 3: 实现 RRF**

`hybrid_retrieval/rrf.py`：
```python
from __future__ import annotations

from typing import Sequence

"""Reciprocal Rank Fusion：把多路排名合并为一个统一排名。

每个文档在某一路的贡献为 1/(k+rank)，k 越大越平滑（默认 60，业界常用）。
只依赖排名不依赖各路原始分，天然消除稠密/稀疏两路分数量纲不一致的问题。
"""


def rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
```

- [ ] **Step 4: 写 rerank 失败测试**

`tests/test_hybrid_rerank.py`：
```python
from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from hybrid_retrieval.rerank import RerankWeights, rerank


def _sd(doc_id, relevance, recency, importance):
    doc = VectorDoc(doc_id, "act_chunk", doc_id, {})
    return ScoredDoc(
        doc=doc,
        score=relevance,
        factors={"relevance": relevance, "recency": recency, "importance": importance},
    )


class RerankTest(unittest.TestCase):
    def test_按加权三因子重排(self):
        docs = [
            _sd("low_rel", relevance=0.2, recency=1.0, importance=1.0),
            _sd("high_rel", relevance=0.9, recency=0.1, importance=0.1),
        ]
        # 关联性权重压倒性时，high_rel 应排第一
        out = rerank(docs, weights=RerankWeights(relevance=1.0, recency=0.0, importance=0.0))
        self.assertEqual(out[0].doc.doc_id, "high_rel")

    def test_权重可覆盖偏向新近度(self):
        docs = [
            _sd("old", relevance=0.9, recency=0.0, importance=0.5),
            _sd("new", relevance=0.5, recency=1.0, importance=0.5),
        ]
        out = rerank(docs, weights=RerankWeights(relevance=0.1, recency=1.0, importance=0.0))
        self.assertEqual(out[0].doc.doc_id, "new")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: 实现 rerank**

`hybrid_retrieval/rerank.py`：
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from datatypes import ScoredDoc

"""三因子可配置重排：relevance（RRF 分）/ recency（时间新近）/ importance（重要度）。

权重由调用方传入，默认给一套均衡策略，业务可覆盖。重排只重算总分并排序，
分项因子保留在 ScoredDoc.factors 里，便于调试与透明化。
"""


@dataclass(slots=True)
class RerankWeights:
    relevance: float = 0.6
    recency: float = 0.2
    importance: float = 0.2


def rerank(docs: Sequence[ScoredDoc], *, weights: RerankWeights | None = None) -> list[ScoredDoc]:
    w = weights or RerankWeights()
    rescored: list[ScoredDoc] = []
    for d in docs:
        f = d.factors
        total = (
            w.relevance * f.get("relevance", 0.0)
            + w.recency * f.get("recency", 0.0)
            + w.importance * f.get("importance", 0.0)
        )
        rescored.append(ScoredDoc(doc=d.doc, score=total, factors=dict(f)))
    return sorted(rescored, key=lambda d: d.score, reverse=True)
```

- [ ] **Step 6: 写 retriever 端到端失败测试（用 fake 依赖，不触真库/模型）**

`tests/test_hybrid_retriever.py`：
```python
from __future__ import annotations

import unittest

from datatypes import ScoredDoc, VectorDoc
from hybrid_retrieval import HybridRetrieval
from hybrid_retrieval.rerank import RerankWeights


class _FakeEmbedding:
    @property
    def dimension(self):
        return 4

    def encode(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class _FakeVectorStore:
    def upsert(self, rows):
        pass

    def delete(self, ids):
        pass

    def search(self, query_vector, *, top_k=10, filters=None):
        return [
            ScoredDoc(VectorDoc("a", "act_chunk", "甲", {"importance": 0.9}), 0.95),
            ScoredDoc(VectorDoc("b", "act_chunk", "乙", {"importance": 0.1}), 0.90),
        ]


def _fake_sparse(query, *, top_k, filters=None):
    return ["b", "a"]


class HybridRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.retr = HybridRetrieval(
            embedding=_FakeEmbedding(),
            vector_store=_FakeVectorStore(),
            sparse_search=_fake_sparse,
        )

    def test_端到端返回_ScoredDoc_列表(self):
        out = self.retr.search("酒馆里发生了什么", top_k=2)
        self.assertTrue(all(isinstance(x, ScoredDoc) for x in out))
        self.assertLessEqual(len(out), 2)

    def test_权重可从调用方传入(self):
        out = self.retr.search(
            "酒馆里发生了什么",
            top_k=2,
            weights=RerankWeights(relevance=0.0, recency=0.0, importance=1.0),
        )
        # importance 权重独大时，metadata.importance 高的 a 排第一
        self.assertEqual(out[0].doc.doc_id, "a")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7: 实现 retriever**

`hybrid_retrieval/retriever.py`：
```python
from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence

from datatypes import ScoredDoc
from hybrid_retrieval.rerank import RerankWeights, rerank
from hybrid_retrieval.rrf import rrf_fuse

"""端到端混合检索入口。

流程：query 经 embedding → 稠密 KNN；稀疏（关键词）检索 → 两路排名 RRF 融合 →
三因子重排 → 返回 ScoredDoc。业务层只传 query + 参数，不关心内部流程。
稀疏检索以可注入的回调声明，避免第二层绑死某个具体后端。
"""

SparseSearch = Callable[..., Sequence[str]]


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
        by_id = {h.doc.doc_id: h for h in dense_hits}

        # 2) 稀疏：关键词检索（可选）
        sparse_ids: list[str] = []
        if self._sparse_search is not None:
            sparse_ids = list(self._sparse_search(query, top_k=fetch_k, filters=filters))

        # 3) RRF 融合两路排名
        fused = rrf_fuse([dense_ids, sparse_ids], k=60)

        # 4) 组装 ScoredDoc + 三因子，交给重排
        candidates: list[ScoredDoc] = []
        for doc_id, rrf_score in fused:
            hit = by_id.get(doc_id)
            if hit is None:
                continue  # 仅稀疏命中、稠密未取回的文档本轮跳过（细化留后续）
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
```

- [ ] **Step 8: 实现包导出**

`hybrid_retrieval/__init__.py`：
```python
from hybrid_retrieval.rerank import RerankWeights, rerank
from hybrid_retrieval.retriever import HybridRetrieval
from hybrid_retrieval.rrf import rrf_fuse

__all__ = ["HybridRetrieval", "RerankWeights", "rerank", "rrf_fuse"]
```

- [ ] **Step 9: 运行确认全部通过**

Run:
```bash
python3 -m unittest tests.test_hybrid_rrf tests.test_hybrid_rerank tests.test_hybrid_retriever -v
```
Expected: 全部 PASS。

- [ ] **Step 10: Commit**

```bash
git add hybrid_retrieval/ tests/test_hybrid_rrf.py tests/test_hybrid_rerank.py tests/test_hybrid_retriever.py
git commit -m "feat(hybrid_retrieval): RRF 融合 + 三因子重排 + 端到端检索入口"
```

---

## Task 6: Persistence 接线 db.Database

**Files:**
- Modify: `Persistence/Store.py:50-63`
- Test: `tests/test_persistence_db_injection.py`

- [ ] **Step 1: 写失败测试（注入 Database）**

`tests/test_persistence_db_injection.py`：
```python
from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from db import Database, DatabaseConfig
from Persistence.Store import GameSaveStore


class PersistenceInjectionTest(unittest.TestCase):
    def test_可注入_Database_并建表(self):
        db = Database(DatabaseConfig(database_url="sqlite+pysqlite:///:memory:"))
        store = GameSaveStore(db)
        store.create_schema()  # 不应抛异常，且复用注入的 engine
        self.assertIs(store.engine, db.engine)

    def test_向后兼容_仍可传_url(self):
        store = GameSaveStore("sqlite+pysqlite:///:memory:")
        store.create_schema()
        self.assertIsNotNone(store.engine)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_persistence_db_injection -v`
Expected: FAIL（`test_可注入_Database` 失败：GameSaveStore 尚不接受 Database）。

- [ ] **Step 3: 改造 GameSaveStore 构造函数**

修改 `Persistence/Store.py`，在文件顶部 import 区加入（第 7 行 sqlalchemy.orm import 之后）：
```python
from db import Database
```

把第 56-63 行的构造函数替换为：
```python
class GameSaveStore:
    def __init__(self, config: "SaveStoreConfig | str | Database") -> None:
        # 三种入参：注入的 Database（推荐，复用统一连接来源）、连接串、或旧配置对象。
        if isinstance(config, Database):
            self._database = config
            self.config = SaveStoreConfig(database_url=config.config.database_url)
        else:
            self.config = (
                SaveStoreConfig(database_url=config) if isinstance(config, str) else config
            )
            self._database = Database(
                DatabaseConfig(database_url=self.config.database_url, echo=self.config.echo)
            )
        self.engine: Engine = self._database.engine
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
```

并在文件顶部 import 区补上 `DatabaseConfig`（与 Database 同一行）：
```python
from db import Database, DatabaseConfig
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_persistence_db_injection -v`
Expected: PASS（2 个测试）。

- [ ] **Step 5: 回归现有持久化测试**

Run: `python3 -m unittest tests.test_persistence_save_load -v`
Expected: 全部 PASS（行为不变，仅换连接来源）。

- [ ] **Step 6: Commit**

```bash
git add Persistence/Store.py tests/test_persistence_db_injection.py
git commit -m "refactor(persistence): GameSaveStore 支持注入 db.Database(向后兼容)"
```

---

## Task 7: 全量回归

- [ ] **Step 1: 跑全部新模块测试**

Run:
```bash
python3 -m unittest tests.test_datatypes tests.test_db_foundation tests.test_vectordb_pgvector tests.test_embedding_interface tests.test_embedding_bge tests.test_hybrid_rrf tests.test_hybrid_rerank tests.test_hybrid_retriever tests.test_persistence_db_injection -v
```
Expected: 全部 PASS。

- [ ] **Step 2: 回归既有相关测试**

Run:
```bash
python3 -m unittest tests.test_persistence_save_load tests.test_recall_indexer -v
```
Expected: 全部 PASS（未破坏既有行为）。

---

## 依赖顺序与说明

- 严格按 Task 顺序执行：datatypes → db → vectordb → embedding → hybrid_retrieval → Persistence 接线。
- 第一层四模块互不依赖；hybrid_retrieval 只依赖 datatypes（rerank/retriever 用到 ScoredDoc/VectorDoc），vectordb/embedding 通过构造注入而非 import。
- 基础模块全程不 import 任何业务模块（Recall/Graph/GameState 等）。
- Recall 数据类型改依赖 datatypes、Recall 迁 pgvector、StoryTemplate 小说模板均为**后续独立 spec**，不在本计划范围。
