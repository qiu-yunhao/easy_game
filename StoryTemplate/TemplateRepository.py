from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text,
    insert, select,
)

from db import Database
from StoryTemplate.TemplateSchema import (
    CharacterArchetype, PlotBeat, PlotSkeletonNode, StyleBible, empty_style_bible,
)

"""4 张 MySQL 分表持久化，注入 db.Database（自持 MetaData，不污染他表）。

列表字段统一 JSON 文本编码存 Text 列（MySQL 5.7+ 无原生数组），读回解码。
主表 story_template 自增 template_id 作各从表外键。user_id 只存不过滤，默认 0=平台。
"""

_META = MetaData()

story_template = Table(
    "story_template", _META,
    Column("template_id", BigInteger().with_variant(Integer, "sqlite"),
           primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, default=0),
    Column("source_title", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

template_style_bible = Table(
    "template_style_bible", _META,
    Column("template_id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("narrative_voice", Text, nullable=False),
    Column("tone_tags", Text, nullable=False),
    Column("prose_rhythm", Text, nullable=False),
    Column("signature_devices", Text, nullable=False),
    Column("world_premise", Text, nullable=False),
    Column("cultivation_system", Text, nullable=False),
    Column("factions", Text, nullable=False),
    Column("key_locations", Text, nullable=False),
    Column("world_rules", Text, nullable=False),
    Column("lexicon", Text, nullable=False),
)

template_character = Table(
    "template_character", _META,
    Column("id", BigInteger().with_variant(Integer, "sqlite"),
           primary_key=True, autoincrement=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("name", String(128), nullable=False),
    Column("role_summary", Text, nullable=False),
    Column("persona", Text, nullable=False),
    Column("speech_style", Text, nullable=False),
    Column("secrets", Text, nullable=False),
    Column("signature_relations", Text, nullable=False),
    Column("suggested_layer", String(32), nullable=False),
)

template_plot_beat = Table(
    "template_plot_beat", _META,
    Column("beat_id", String(32), primary_key=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("label", String(128), nullable=False),
    Column("tags", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("dramatic_function", String(128), nullable=False),
    Column("reusable_conflict", Text, nullable=False),
)

template_plot_skeleton = Table(
    "template_plot_skeleton", _META,
    Column("node_id", String(32), primary_key=True),
    Column("template_id", Integer, nullable=False, index=True),
    Column("order_index", Integer, nullable=False),
    Column("title", String(255), nullable=False),
    Column("event_summary", Text, nullable=False),
    Column("preconditions", Text, nullable=False),
    Column("maps_to_chapter_hint", String(128), nullable=False),
)


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class TemplateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._metadata = _META

    def create_all(self) -> None:
        self._database.create_all(self._metadata)

    def save_template(
        self, *, user_id: int = 0, source_title: str,
        style_bible: StyleBible, characters: list[CharacterArchetype],
        beats: list[PlotBeat], skeleton: list[PlotSkeletonNode],
    ) -> int:
        with self._database.session() as db:
            result = db.execute(insert(story_template).values(
                user_id=user_id, source_title=source_title,
                created_at=datetime.now(timezone.utc),
            ))
            template_id = int(result.inserted_primary_key[0])

            db.execute(insert(template_style_bible).values(
                template_id=template_id,
                narrative_voice=style_bible["narrative_voice"],
                tone_tags=_dumps(style_bible["tone_tags"]),
                prose_rhythm=style_bible["prose_rhythm"],
                signature_devices=_dumps(style_bible["signature_devices"]),
                world_premise=style_bible["world_premise"],
                cultivation_system=style_bible["cultivation_system"],
                factions=_dumps(style_bible["factions"]),
                key_locations=_dumps(style_bible["key_locations"]),
                world_rules=_dumps(style_bible["world_rules"]),
                lexicon=_dumps(style_bible["lexicon"]),
            ))
            for c in characters:
                db.execute(insert(template_character).values(
                    template_id=template_id, name=c["name"],
                    role_summary=c["role_summary"], persona=_dumps(c["persona"]),
                    speech_style=c["speech_style"], secrets=_dumps(c["secrets"]),
                    signature_relations=_dumps(c["signature_relations"]),
                    suggested_layer=c["suggested_layer"],
                ))
            for b in beats:
                db.execute(insert(template_plot_beat).values(
                    beat_id=b["beat_id"], template_id=template_id, label=b["label"],
                    tags=_dumps(b["tags"]), summary=b["summary"],
                    dramatic_function=b["dramatic_function"],
                    reusable_conflict=b["reusable_conflict"],
                ))
            for n in skeleton:
                db.execute(insert(template_plot_skeleton).values(
                    node_id=n["node_id"], template_id=template_id,
                    order_index=n["order_index"], title=n["title"],
                    event_summary=n["event_summary"],
                    preconditions=_dumps(n["preconditions"]),
                    maps_to_chapter_hint=n["maps_to_chapter_hint"],
                ))
            db.commit()
            return template_id

    def get_style_bible(self, template_id: int) -> StyleBible:
        with self._database.session() as db:
            row = db.execute(select(template_style_bible).where(
                template_style_bible.c.template_id == template_id
            )).mappings().first()
        if row is None:
            return empty_style_bible()
        return {
            "narrative_voice": row["narrative_voice"],
            "tone_tags": json.loads(row["tone_tags"]),
            "prose_rhythm": row["prose_rhythm"],
            "signature_devices": json.loads(row["signature_devices"]),
            "world_premise": row["world_premise"],
            "cultivation_system": row["cultivation_system"],
            "factions": json.loads(row["factions"]),
            "key_locations": json.loads(row["key_locations"]),
            "world_rules": json.loads(row["world_rules"]),
            "lexicon": json.loads(row["lexicon"]),
        }

    def get_characters(self, template_id: int) -> list[CharacterArchetype]:
        with self._database.session() as db:
            rows = db.execute(select(template_character).where(
                template_character.c.template_id == template_id
            )).mappings().all()
        return [{
            "name": r["name"], "role_summary": r["role_summary"],
            "persona": json.loads(r["persona"]), "speech_style": r["speech_style"],
            "secrets": json.loads(r["secrets"]),
            "signature_relations": json.loads(r["signature_relations"]),
            "suggested_layer": r["suggested_layer"],
        } for r in rows]

    def get_beats(self, template_id: int) -> list[PlotBeat]:
        with self._database.session() as db:
            rows = db.execute(select(template_plot_beat).where(
                template_plot_beat.c.template_id == template_id
            )).mappings().all()
        return [{
            "beat_id": r["beat_id"], "label": r["label"], "tags": json.loads(r["tags"]),
            "summary": r["summary"], "dramatic_function": r["dramatic_function"],
            "reusable_conflict": r["reusable_conflict"],
        } for r in rows]

    def get_skeleton(self, template_id: int) -> list[PlotSkeletonNode]:
        with self._database.session() as db:
            rows = db.execute(select(template_plot_skeleton).where(
                template_plot_skeleton.c.template_id == template_id
            ).order_by(template_plot_skeleton.c.order_index)).mappings().all()
        return [{
            "node_id": r["node_id"], "order_index": r["order_index"], "title": r["title"],
            "event_summary": r["event_summary"],
            "preconditions": json.loads(r["preconditions"]),
            "maps_to_chapter_hint": r["maps_to_chapter_hint"],
        } for r in rows]
