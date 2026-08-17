from __future__ import annotations

from typing import Any

from datatypes import VectorDoc, template_scope_prefix
from StoryTemplate.TemplateSchema import (
    PlotBeat, PlotSkeletonNode, StyleBible,
)

"""对外 Facade：编排导入流水线 + 4 个检索接口。子模块只经本类使用。

模板全局共享（用户拍板）：user_id 仅透传存库作归属，不进向量前缀、不参与检索过滤；
向量片段按 template_id 隔离（前缀 tmpl:{tid}:）。
"""


class StoryTemplateService:
    def __init__(
        self, *, chunker, extract_agent, clustering, repository, vector_store, embedding,
    ) -> None:
        self._chunker = chunker
        self._extract = extract_agent
        self._clustering = clustering
        self._repo = repository
        self._vector_store = vector_store
        self._embedding = embedding

    def import_novel(self, *, source_title: str, text: str, user_id: int = 0) -> int:
        chunks = self._chunker.chunk(text)
        # Level1 逐块信号（真 LLM 串行）。
        signals = self._extract.map_chunks(chunks)

        # Level2 向量聚合：桥段去重 + 角色合并。
        event_signals = [s for s in signals if s.get("is_event")]
        beat_texts = [s["event_summary"] for s in event_signals if s.get("event_summary")]
        beat_clusters = self._clustering.dedup_beats(beat_texts) if beat_texts else []
        beat_reps = [beat_texts[c[0]] for c in beat_clusters]

        char_pairs = [(c.get("name", ""), c.get("behavior", ""))
                      for s in signals for c in s.get("characters", [])]
        names = [p[0] for p in char_pairs]
        behaviors = [p[1] for p in char_pairs]
        char_clusters: list[list[int]] = []
        if names:
            char_vecs = self._clustering.embed(
                [f"{n} {b}" for n, b in char_pairs]
            )
            char_clusters = self._clustering.merge_characters(names, char_vecs)
        name_clusters = [[names[i] for i in cluster] for cluster in char_clusters]
        # 行为样本按同一聚类分组，与 name_clusters 一一对应，保住「该角色的名字↔该角色的行为」绑定。
        behavior_clusters = [[behaviors[i] for i in cluster] for cluster in char_clusters]

        # Level3 全局归并（四类各 1 次 LLM）。
        style_bible = self._extract.reduce_style(signals)
        characters = self._extract.reduce_characters(name_clusters, behavior_clusters)
        beats = self._extract.reduce_beats(beat_reps)
        skeleton = self._extract.reduce_skeleton(event_signals)

        # 落 MySQL 4 表。
        template_id = self._repo.save_template(
            user_id=user_id, source_title=source_title,
            style_bible=style_bible, characters=characters, beats=beats, skeleton=skeleton,
        )

        # 原文片段入向量库（按 template_id 隔离，全局共享无 per-player 前缀）。
        prefix = template_scope_prefix(template_id)
        docs = [
            VectorDoc(
                doc_id=f"{prefix}{chunk.chunk_id}",
                doc_type="style_passage",
                text=chunk.text,
                metadata={
                    "template_id": template_id, "order_index": chunk.order_index,
                },
            )
            for chunk in chunks if chunk.text.strip()
        ]
        if docs:
            vectors = self._embedding.encode([d.text for d in docs])
            self._vector_store.upsert(list(zip(docs, vectors)))
        return template_id

    def get_style_bible(self, template_id: int) -> StyleBible:
        return self._repo.get_style_bible(template_id)

    def suggest_plot_beats(self, template_id: int, *, query: str, top_k: int = 5) -> list[PlotBeat]:
        beats = self._repo.get_beats(template_id)
        q = (query or "").strip()
        if not q:
            return beats[:top_k]
        hits = [b for b in beats
                if q in b["label"] or q in b["summary"] or any(q in t for t in b["tags"])]
        return (hits or beats)[:top_k]

    def next_skeleton_nodes(self, template_id: int, *, chapter_hint: str) -> list[PlotSkeletonNode]:
        nodes = self._repo.get_skeleton(template_id)
        matched = [n for n in nodes if n["maps_to_chapter_hint"] == chapter_hint]
        return matched or nodes[:1]

    def search_style_passages(self, template_id: int, *, query: str, top_k: int = 5) -> list[str]:
        vec = self._embedding.encode([query])[0]
        scored = self._vector_store.search(
            vec, top_k=top_k,
            filters={"template_id": str(template_id), "doc_type": "style_passage"},
        )
        return [s.doc.text for s in scored]
