from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserAccount(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    players: Mapped[list["PlayerSlot"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class StoryCharacterTemplate(TimestampMixin, Base):
    __tablename__ = "story_character_templates"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    occupation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="actor")
    default_avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_runtime_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_dialogue_flags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    starter_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    player_story_characters: Mapped[list["PlayerStoryCharacter"]] = relationship(back_populates="template")
    player_actor_interactions: Mapped[list["PlayerActorInteraction"]] = relationship(back_populates="template")

    __table_args__ = (
        Index(
            "ix_story_character_template_name_occupation_kind",
            "display_name",
            "occupation",
            "template_kind",
            unique=True,
        ),
    )


class PlayerSlot(TimestampMixin, Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    narration_style_preset: Mapped[str] = mapped_column(String(64), nullable=False)
    player_character_id: Mapped[str] = mapped_column(String(64), nullable=False)
    current_story_node_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    current_scene_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    current_scene_location_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    current_scene_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_scene_time_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    current_scene_beat: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    inventory_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    attributes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    player_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scene_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    story_initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_handoff_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_snapshot_id: Mapped[int | None] = mapped_column(BIGINT_PK, nullable=True)

    user: Mapped[UserAccount] = relationship(back_populates="players")
    world_state: Mapped["PlayerWorldState | None"] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
        uselist=False,
    )
    story_characters: Mapped[list["PlayerStoryCharacter"]] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
    )
    actor_interactions: Mapped[list["PlayerActorInteraction"]] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
    )
    quests: Mapped[list["PlayerQuest"]] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
    )
    save_snapshots: Mapped[list["PlayerSaveSnapshot"]] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
        order_by="PlayerSaveSnapshot.id.desc()",
    )


class PlayerWorldState(TimestampMixin, Base):
    __tablename__ = "player_world_states"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    world_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plot_flags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scene_flags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    player: Mapped[PlayerSlot] = relationship(back_populates="world_state")


class PlayerStoryCharacter(TimestampMixin, Base):
    __tablename__ = "player_story_characters"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("story_character_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_character_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_layer: Mapped[str] = mapped_column(String(16), nullable=False, default="L1")
    has_met: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    affection_score: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    life_status: Mapped[str] = mapped_column(String(32), nullable=False, default="alive")
    is_on_stage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_offstage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dialogue_flags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    runtime_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    profile_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    player: Mapped[PlayerSlot] = relationship(back_populates="story_characters")
    template: Mapped[StoryCharacterTemplate | None] = relationship(back_populates="player_story_characters")

    __table_args__ = (
        Index("ix_player_story_character_player_actor", "player_id", "actor_character_id", unique=True),
    )


class PlayerActorInteraction(TimestampMixin, Base):
    __tablename__ = "player_actor_interactions"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("story_character_templates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    favor_score: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    interaction_flags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    interaction_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    met_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    player: Mapped[PlayerSlot] = relationship(back_populates="actor_interactions")
    template: Mapped[StoryCharacterTemplate] = relationship(back_populates="player_actor_interactions")


class PlayerQuest(TimestampMixin, Base):
    __tablename__ = "player_quests"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
    )
    quest_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="story")
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    player: Mapped[PlayerSlot] = relationship(back_populates="quests")

    __table_args__ = (
        Index("ix_player_quest_player_key", "player_id", "quest_key", unique=True),
    )


class PlayerSaveSnapshot(Base):
    __tablename__ = "player_save_snapshots"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    save_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    save_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    game_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    character_profiles_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scene_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    session_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    world_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    player: Mapped[PlayerSlot] = relationship(back_populates="save_snapshots")


class RecallIndexLog(Base):
    """回忆索引防重日志：记录「某玩家的某一幕」是否已索引进向量库。

    幕结束时即时索引可能被多条路径触发（流式动作、工具动作等），且索引本身是
    异步后台执行的，故需要一张日志表按 (player_id, scene_id) 唯一去重——索引成功
    后才写入，失败不写，保证下次仍可重试。不建反向关系以免改动 PlayerSlot。
    """

    __tablename__ = "recall_index_log"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(String(128), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("uq_recall_index_log_player_scene", "player_id", "scene_id", unique=True),
    )
