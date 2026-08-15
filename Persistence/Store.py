from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db import Database, DatabaseConfig

from Persistence.Models import (
    Base,
    PlayerActorInteraction,
    PlayerQuest,
    PlayerSaveSnapshot,
    PlayerSlot,
    PlayerStoryCharacter,
    StoryCharacterTemplate,
    UserAccount,
)
from Persistence.store_common import SNAPSHOT_VERSION, clean_text, clone_json, utc_now
from Persistence.store_snapshot import (
    player_character_id_from_snapshot,
    serialize_actor_interaction,
    serialize_player,
    serialize_player_quest,
    serialize_snapshot,
    serialize_story_character,
    serialize_template,
    serialize_user,
)
from Persistence.store_sync import (
    apply_snapshot_to_player_row,
    insert_snapshot,
    seed_starter_story_characters,
    upsert_actor_interactions,
    upsert_player_quests,
    upsert_story_characters,
    upsert_story_character_templates,
    upsert_world_state,
)
from StoryStateUtils import (
    build_character_roster_decision_hints,
    build_character_roster_summary,
    matches_lookup,
    matches_roster_layer,
    normalize_lookup_text,
    normalize_roster_layer_filter,
)


@dataclass(slots=True)
class SaveStoreConfig:
    database_url: str
    echo: bool = False


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

    def _commit_and_refresh(self, db: Session, *rows: object) -> None:
        db.commit()
        for row in rows:
            db.refresh(row)

    def _save_player_snapshot(
        self,
        db: Session,
        player: PlayerSlot,
        session_snapshot: dict[str, object],
        *,
        save_kind: str,
        save_label: str | None,
        seed_starters: bool = False,
    ) -> PlayerSaveSnapshot:
        apply_snapshot_to_player_row(player, session_snapshot)
        if seed_starters:
            seed_starter_story_characters(db, player.id)
        upsert_world_state(db, player.id, session_snapshot)
        upsert_story_characters(db, player.id, session_snapshot)
        upsert_actor_interactions(db, player.id, session_snapshot)
        upsert_player_quests(db, player.id, session_snapshot)
        snapshot_row = insert_snapshot(
            db,
            player_id=player.id,
            session_snapshot=session_snapshot,
            save_kind=save_kind,
            save_label=save_label,
        )
        player.latest_snapshot_id = snapshot_row.id
        player.last_saved_at = utc_now()
        return snapshot_row

    def _player_slot_payload(self, player: PlayerSlot) -> dict[str, object]:
        return {"player_id": player.id, "slot_name": player.slot_name}

    def _serialize_player_story_characters(self, db: Session, player_id: int) -> list[dict[str, object]]:
        return [serialize_story_character(row) for row in self._story_character_rows(db, player_id)]

    def _serialize_player_actor_interactions(self, db: Session, player_id: int) -> list[dict[str, object]]:
        return [serialize_actor_interaction(row) for row in self._actor_interaction_rows(db, player_id)]

    def _serialize_player_quests(self, db: Session, player_id: int) -> list[dict[str, object]]:
        return [serialize_player_quest(row) for row in self._quest_rows(db, player_id)]

    def ensure_user(
        self,
        *,
        username: str,
        display_name: str | None = None,
        password_hash: str | None = None,
    ) -> dict[str, object]:
        resolved_username = clean_text(username)
        if not resolved_username:
            raise ValueError("username is required")
        resolved_display_name = clean_text(display_name, resolved_username)
        with self._session_factory() as db:
            user = db.scalar(select(UserAccount).where(UserAccount.username == resolved_username))
            if user is None:
                user = UserAccount(
                    username=resolved_username,
                    display_name=resolved_display_name,
                    password_hash=password_hash,
                    status="active",
                )
                db.add(user)
            else:
                user.display_name = resolved_display_name
                if password_hash:
                    user.password_hash = password_hash
            self._commit_and_refresh(db, user)
            return serialize_user(user)

    def upsert_story_character_templates(self, templates: list[dict[str, object]]) -> list[dict[str, object]]:
        if not isinstance(templates, list):
            raise ValueError("story character templates must be a list")
        with self._session_factory() as db:
            rows = upsert_story_character_templates(db, templates)
            self._commit_and_refresh(db, *rows)
            return [serialize_template(row) for row in rows]

    def list_players_for_user(self, user_id: int) -> list[dict[str, object]]:
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(PlayerSlot)
                    .where(PlayerSlot.user_id == user_id)
                    .order_by(
                        PlayerSlot.last_saved_at.is_(None),
                        PlayerSlot.last_saved_at.desc(),
                        PlayerSlot.id.desc(),
                    )
                )
            )
            return [serialize_player(row) for row in rows]

    def create_new_game(
        self,
        *,
        user_id: int,
        slot_name: str,
        session_snapshot: dict[str, object],
        starter_story_templates: list[dict[str, object]] | None = None,
        save_label: str | None = None,
    ) -> dict[str, object]:
        with self._session_factory() as db:
            user = self._require_user(db, user_id)
            if starter_story_templates:
                upsert_story_character_templates(db, starter_story_templates)
            player = PlayerSlot(
                user_id=user.id,
                slot_name=clean_text(slot_name, "new_save"),
                status="active",
                mode="heuristic",
                narration_style_preset="xianxia_default",
                player_character_id=player_character_id_from_snapshot(session_snapshot),
            )
            db.add(player)
            db.flush()
            snapshot_row = self._save_player_snapshot(
                db,
                player,
                session_snapshot,
                save_kind="new_game",
                save_label=save_label,
                seed_starters=True,
            )
            self._commit_and_refresh(db, player, snapshot_row)
            return {
                "player": serialize_player(player),
                "snapshot": serialize_snapshot(snapshot_row),
                "story_characters": self._serialize_player_story_characters(db, player.id),
                "actor_interactions": self._serialize_player_actor_interactions(db, player.id),
                "quests": self._serialize_player_quests(db, player.id),
            }

    def save_player_session(
        self,
        *,
        user_id: int,
        player_id: int,
        session_snapshot: dict[str, object],
        save_kind: str = "manual",
        save_label: str | None = None,
    ) -> dict[str, object]:
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            snapshot_row = self._save_player_snapshot(
                db,
                player,
                session_snapshot,
                save_kind=save_kind,
                save_label=save_label,
            )
            self._commit_and_refresh(db, player, snapshot_row)
            return {"player": serialize_player(player), "snapshot": serialize_snapshot(snapshot_row)}

    def load_player_session(self, *, user_id: int, player_id: int) -> dict[str, object]:
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            snapshot_row = self._resolve_latest_snapshot(db, player)
            if snapshot_row is None:
                raise ValueError("player has no saved snapshot to load")
            world_state = player.world_state
            return {
                "player": serialize_player(player),
                "snapshot": {
                    key: clone_json(value)
                    for key, value in (
                        ("session", snapshot_row.session_config_json),
                        ("state", snapshot_row.game_state_json),
                        ("character_profiles", snapshot_row.character_profiles_json),
                        ("scene_config", snapshot_row.scene_config_json),
                    )
                },
                "world_state": clone_json(world_state.world_state_json) if world_state is not None else {},
                "story_characters": self._serialize_player_story_characters(db, player.id),
                "actor_interactions": self._serialize_player_actor_interactions(db, player.id),
                "quests": self._serialize_player_quests(db, player.id),
                "save_snapshot": serialize_snapshot(snapshot_row),
            }

    def query_inventory(self, *, user_id: int, player_id: int) -> dict[str, object]:
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            items: list[dict[str, object]] = []
            for raw_item in list(player.inventory_json or []):
                if isinstance(raw_item, dict):
                    items.append(
                        {
                            "item_id": clean_text(raw_item.get("id")),
                            "item_name": clean_text(
                                raw_item.get("name"),
                                clean_text(raw_item.get("id"), "unknown_item"),
                            ),
                            "quantity": int(raw_item.get("quantity", 0) or 0),
                            "icon": clean_text(raw_item.get("icon")),
                        }
                    )
                else:
                    item_name = clean_text(raw_item)
                    if item_name:
                        items.append(
                            {
                                "item_id": item_name,
                                "item_name": item_name,
                                "quantity": 1,
                                "icon": "",
                            }
                        )
            return {**self._player_slot_payload(player), "items": items}

    def query_player_status(self, *, user_id: int, player_id: int) -> dict[str, object]:
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            return {
                **self._player_slot_payload(player),
                "player_profile": clone_json(player.player_profile_json),
                "attributes": clone_json(player.attributes_json),
                "scene": clone_json(player.scene_state_json),
                "story_initialized": player.story_initialized,
                "last_saved_at": player.last_saved_at.isoformat() if player.last_saved_at is not None else None,
            }

    def query_relation(self, *, user_id: int, player_id: int, target_name: str) -> dict[str, object]:
        normalized_target = normalize_lookup_text(target_name)
        if not normalized_target:
            raise ValueError("target_name is required")
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            for row in self._story_character_rows(db, player.id):
                candidates = (
                    row.actor_character_id,
                    row.display_name,
                    row.profile_snapshot_json.get("name") if isinstance(row.profile_snapshot_json, dict) else "",
                )
                if matches_lookup(normalized_target, *candidates):
                    return {
                        "player_id": player.id,
                        "actor_character_id": row.actor_character_id,
                        "display_name": row.display_name,
                        "score": float(row.affection_score),
                        "life_status": row.life_status,
                        "is_on_stage": row.is_on_stage,
                        "dialogue_flags": clone_json(row.dialogue_flags_json),
                        "source": "player_story_characters",
                    }

            templates = {template.id: template for template in db.scalars(select(StoryCharacterTemplate))}
            for row in self._actor_interaction_rows(db, player.id):
                template = templates.get(row.template_id)
                candidates = (
                    template.template_key if template is not None else "",
                    template.display_name if template is not None else "",
                    template.occupation if template is not None else "",
                )
                if matches_lookup(normalized_target, *candidates):
                    return {
                        "player_id": player.id,
                        "actor_character_id": template.template_key if template is not None else "",
                        "display_name": template.display_name if template is not None else target_name,
                        "score": float(row.favor_score),
                        "life_status": "",
                        "is_on_stage": False,
                        "dialogue_flags": clone_json(row.interaction_flags_json),
                        "source": "player_actor_interactions",
                    }
        raise ValueError(f"No relation record found for `{target_name}`.")

    def query_quests(self, *, user_id: int, player_id: int) -> dict[str, object]:
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            quests = [serialize_player_quest(row) for row in self._quest_rows(db, player.id) if row.status == "active"]
            return {**self._player_slot_payload(player), "quests": quests}

    def query_character_roster(
        self,
        *,
        user_id: int,
        player_id: int,
        layer_filter: str = "all",
    ) -> dict[str, object]:
        normalized_filter = normalize_roster_layer_filter(layer_filter)
        with self._session_factory() as db:
            player = self._require_player(db, user_id=user_id, player_id=player_id)
            story_rows = self._story_character_rows(db, player.id)
            interaction_rows = self._actor_interaction_rows(db, player.id)
            actor_templates = list(
                db.scalars(
                    select(StoryCharacterTemplate)
                    .where(StoryCharacterTemplate.template_kind == "actor")
                    .order_by(StoryCharacterTemplate.display_name.asc(), StoryCharacterTemplate.id.asc())
                )
            )

            characters: list[dict[str, object]] = []
            total_l1 = 0
            total_l2 = 0
            for row in story_rows:
                layer = clean_text(row.agent_layer, "L2")
                layer = layer if layer in {"L1", "L2"} else "L2"
                total_l1 += int(layer == "L1")
                total_l2 += int(layer == "L2")
                if not matches_roster_layer(layer, normalized_filter):
                    continue
                profile_snapshot = row.profile_snapshot_json if isinstance(row.profile_snapshot_json, dict) else {}
                characters.append(
                    {
                        "character_id": row.actor_character_id,
                        "display_name": row.display_name,
                        "layer": layer,
                        "agent_type": layer,
                        "storage_mode": "player_bound_instance",
                        "source_table": "player_story_characters",
                        "template_id": row.template_id,
                        "avatar_url": row.avatar_url,
                        "occupation": clean_text(profile_snapshot.get("occupation", "")),
                        "story_role": clean_text(profile_snapshot.get("story_role", "")),
                        "planned_chapter_ids": clone_json(profile_snapshot.get("planned_chapter_ids", [])),
                        "profile_source": clean_text(profile_snapshot.get("profile_source", "")),
                        "is_active": row.is_active,
                        "is_offstage": row.is_offstage,
                        "is_on_stage": row.is_on_stage,
                        "has_met": row.has_met,
                        "affection_score": float(row.affection_score),
                    }
                )

            interactions_by_template_id = {row.template_id: row for row in interaction_rows}
            total_actor = len(actor_templates)
            if matches_roster_layer("ActorAgent", normalized_filter):
                for template in actor_templates:
                    profile_snapshot = template.default_profile_json if isinstance(template.default_profile_json, dict) else {}
                    interaction = interactions_by_template_id.get(template.id)
                    characters.append(
                        {
                            "character_id": template.template_key,
                            "display_name": template.display_name,
                            "layer": "ActorAgent",
                            "agent_type": "actor",
                            "storage_mode": "shared_template",
                            "source_table": "story_character_templates",
                            "template_id": template.id,
                            "avatar_url": template.default_avatar_url,
                            "occupation": clean_text(template.occupation, clean_text(profile_snapshot.get("occupation", ""))),
                            "story_role": clean_text(profile_snapshot.get("story_role", "")),
                            "planned_chapter_ids": clone_json(profile_snapshot.get("planned_chapter_ids", [])),
                            "profile_source": clean_text(profile_snapshot.get("profile_source", "")),
                            "is_active": bool(profile_snapshot.get("is_active", True)),
                            "is_offstage": bool(profile_snapshot.get("is_offstage", False)),
                            "linked_to_player": interaction is not None,
                            "met_by_player": interaction is not None,
                            "met_count": int(interaction.met_count or 0) if interaction is not None else 0,
                            "favor_score": float(interaction.favor_score) if interaction is not None else 0.0,
                        }
                    )

            characters.sort(
                key=lambda item: (
                    str(item.get("layer", "")),
                    str(item.get("display_name", "")),
                    str(item.get("character_id", "")),
                )
            )
            summary = build_character_roster_summary(
                player_id=player.id,
                slot_name=player.slot_name,
                layer_filter=normalized_filter,
                total_l1=total_l1,
                total_l2=total_l2,
                total_actor=total_actor,
                filtered_total=len(characters),
            )
            return {
                **self._player_slot_payload(player),
                "summary": summary,
                "characters": characters,
                "decision_hints": build_character_roster_decision_hints(summary),
            }

    def _require_user(self, db: Session, user_id: int) -> UserAccount:
        user = db.get(UserAccount, user_id)
        if user is None:
            raise ValueError(f"user `{user_id}` does not exist")
        return user

    def _require_player(self, db: Session, *, user_id: int, player_id: int) -> PlayerSlot:
        player = db.get(PlayerSlot, player_id)
        if player is None or player.user_id != user_id:
            raise ValueError(f"player `{player_id}` does not belong to user `{user_id}`")
        return player

    def _resolve_latest_snapshot(self, db: Session, player: PlayerSlot) -> PlayerSaveSnapshot | None:
        if player.latest_snapshot_id is not None:
            snapshot_row = db.get(PlayerSaveSnapshot, player.latest_snapshot_id)
            if snapshot_row is not None:
                return snapshot_row
        return db.scalar(
            select(PlayerSaveSnapshot)
            .where(PlayerSaveSnapshot.player_id == player.id)
            .order_by(PlayerSaveSnapshot.id.desc())
        )

    def _story_character_rows(self, db: Session, player_id: int) -> list[PlayerStoryCharacter]:
        return list(
            db.scalars(
                select(PlayerStoryCharacter)
                .where(PlayerStoryCharacter.player_id == player_id)
                .order_by(PlayerStoryCharacter.id.asc())
            )
        )

    def _actor_interaction_rows(self, db: Session, player_id: int) -> list[PlayerActorInteraction]:
        return list(
            db.scalars(
                select(PlayerActorInteraction)
                .where(PlayerActorInteraction.player_id == player_id)
                .order_by(PlayerActorInteraction.template_id.asc())
            )
        )

    def _quest_rows(self, db: Session, player_id: int) -> list[PlayerQuest]:
        return list(
            db.scalars(
                select(PlayerQuest)
                .where(PlayerQuest.player_id == player_id)
                .order_by(PlayerQuest.sort_order.asc(), PlayerQuest.id.asc())
            )
        )
