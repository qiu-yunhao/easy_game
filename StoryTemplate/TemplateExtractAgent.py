from __future__ import annotations

import uuid
from typing import Any

from BaseAgent import BaseAgent
from PromptUtils import render_json_instruction
from StoryTemplate.TemplateChunker import Chunk
from StoryTemplate.TemplateSchema import (
    CharacterArchetype, ChunkSignal, PlotBeat, PlotSkeletonNode, StyleBible,
    empty_style_bible,
    CHARACTER_ARCHETYPE_RESPONSE_SCHEMA, CHUNK_SIGNAL_RESPONSE_SCHEMA,
    PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
    STYLE_BIBLE_RESPONSE_SCHEMA,
)

"""分层归并提取：Level1 逐块信号（真 LLM，串行）+ Level3 四类全局归并。

继承 BaseAgent 复用 JSON 模式与截断修复。第一版串行；map_chunks 签名预留
「块列表 → 信号列表」，后续换并行不动调用方。归并入参已由 Service 侧用
Clustering 预处理（去重/合并），本层只负责「文字 → 结构化」的 LLM 提炼。
"""

EXTRACT_SYSTEM_PROMPT = """
你是小说模板提取助手。从给定中文小说片段中提炼结构化信息，只返回严格 JSON。
不要照抄原文长句；风格标签要抽象概括；桥段概要去掉专有名词只留冲突结构。
"""


class TemplateExtractAgent(BaseAgent):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("system_prompt", EXTRACT_SYSTEM_PROMPT)
        kwargs.setdefault("temperature", 0.4)
        super().__init__(**kwargs)

    def map_chunks(self, chunks: list[Chunk]) -> list[ChunkSignal]:
        signals: list[ChunkSignal] = []
        for chunk in chunks:
            raw = self.command(
                instruction=render_json_instruction(
                    "提炼此片段的风格标签、手法、出场角色及行为，判断是否含关键情节事件：",
                    {"chunk_text": chunk.text[:3000]},
                ),
                response_format=CHUNK_SIGNAL_RESPONSE_SCHEMA,
            )
            signals.append({
                "chunk_id": chunk.chunk_id,
                "order_index": chunk.order_index,
                "style_tone_tags": list(raw.get("style_tone_tags", [])),
                "style_devices": list(raw.get("style_devices", [])),
                "characters": list(raw.get("characters", [])),
                "is_event": bool(raw.get("is_event", False)),
                "event_summary": str(raw.get("event_summary", "") or ""),
            })
        return signals

    def reduce_style(self, signals: list[ChunkSignal]) -> StyleBible:
        tone_votes = [t for s in signals for t in s.get("style_tone_tags", [])]
        device_votes = [d for s in signals for d in s.get("style_devices", [])]
        raw = self.command(
            instruction=render_json_instruction(
                "综合以下各章风格投票与世界观线索，产出统一的风格圣经与世界观设定：",
                {"tone_votes": tone_votes, "device_votes": device_votes},
            ),
            response_format=STYLE_BIBLE_RESPONSE_SCHEMA,
        )
        result = empty_style_bible()
        for key in result:
            if key in raw:
                result[key] = raw[key]  # type: ignore[literal-required]
        return result

    def reduce_characters(
        self, name_clusters: list[list[str]], behaviors: list[str],
    ) -> list[CharacterArchetype]:
        raw = self.command(
            instruction=render_json_instruction(
                "把以下角色簇（同一角色的多个名字样本）与行为样本归并成角色原型：",
                {"name_clusters": name_clusters, "behavior_samples": behaviors},
            ),
            response_format=CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
        )
        return [self._as_character(c) for c in raw.get("characters", [])]

    def reduce_beats(self, beat_summaries: list[str]) -> list[PlotBeat]:
        raw = self.command(
            instruction=render_json_instruction(
                "把以下去重后的桥段片段抽象成可复用的情节桥段（去专有名词，只留冲突结构）：",
                {"beat_samples": beat_summaries},
            ),
            response_format=PLOT_BEAT_RESPONSE_SCHEMA,
        )
        beats: list[PlotBeat] = []
        for b in raw.get("beats", []):
            beats.append({
                "beat_id": uuid.uuid4().hex[:12],
                "label": str(b.get("label", "") or ""),
                "tags": list(b.get("tags", [])),
                "summary": str(b.get("summary", "") or ""),
                "dramatic_function": str(b.get("dramatic_function", "") or ""),
                "reusable_conflict": str(b.get("reusable_conflict", "") or ""),
            })
        return beats

    def reduce_skeleton(self, event_signals: list[ChunkSignal]) -> list[PlotSkeletonNode]:
        ordered = sorted(event_signals, key=lambda s: s.get("order_index", 0))
        raw = self.command(
            instruction=render_json_instruction(
                "把以下按顺序排列的关键事件归并成主线骨架节点（A→B→C）：",
                {"events": [s.get("event_summary", "") for s in ordered]},
            ),
            response_format=PLOT_SKELETON_RESPONSE_SCHEMA,
        )
        nodes: list[PlotSkeletonNode] = []
        for idx, n in enumerate(raw.get("nodes", [])):
            nodes.append({
                "node_id": uuid.uuid4().hex[:12],
                "order_index": idx,
                "title": str(n.get("title", "") or ""),
                "event_summary": str(n.get("event_summary", "") or ""),
                "preconditions": list(n.get("preconditions", [])),
                "maps_to_chapter_hint": str(n.get("maps_to_chapter_hint", "") or ""),
            })
        return nodes

    @staticmethod
    def _as_character(c: dict[str, Any]) -> CharacterArchetype:
        return {
            "name": str(c.get("name", "") or ""),
            "role_summary": str(c.get("role_summary", "") or ""),
            "persona": list(c.get("persona", [])),
            "speech_style": str(c.get("speech_style", "") or ""),
            "secrets": list(c.get("secrets", [])),
            "signature_relations": list(c.get("signature_relations", [])),
            "suggested_layer": str(c.get("suggested_layer", "") or ""),
        }
