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
        # sentence-transformers 5.x 起改名为 get_embedding_dimension，旧名将废弃。
        getter = getattr(
            self._model, "get_embedding_dimension", None
        ) or self._model.get_sentence_embedding_dimension
        return int(getter())

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,  # 归一化，配合余弦检索
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]
