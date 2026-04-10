from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from Persistence.Models import (
    PlayerActorInteraction,
    PlayerQuest,
    PlayerSaveSnapshot,
    PlayerSlot,
    PlayerStoryCharacter,
    PlayerWorldState,
    StoryCharacterTemplate,
)
from Persistence.store_common import SNAPSHOT_VERSION, clean_text, clone_json
from Persistence.store_snapshot import (
    build_actor_interaction_records,
    build_player_quest_records,
    build_player_attributes,
    build_plot_flags_payload,
    build_scene_flags_payload,
    build_story_character_records,
    build_world_state_payload,
    player_character_id_from_snapshot,
    player_profile_from_snapshot,
    require_snapshot_value,
)


def apply_snapshot_to_player_row(player: PlayerSlot, session_snapshot: dict[str, Any]) -> None:
    session_meta = require_snapshot_value(session_snapshot, "session", dict)
    state = require_snapshot_value(session_snapshot, "state", dict)
    plot = state.get("plot", {})
    scene = state.get("scene", {})
    player.mode = clean_text(session_meta.get("mode"), player.mode or "agent-first")
    player.narration_style_preset = clean_text(
        session_meta.get("narration_style_preset"),
        player.narration_style_preset or "xianxia_default",
    )
    player.player_character_id = player_character_id_from_snapshot(session_snapshot)
    player.current_story_node_id = clean_text(plot.get("scene_id"), clean_text(plot.get("chapter_id")))
    player.current_scene_id = clean_text(plot.get("scene_id"))
    player.current_scene_location_id = clean_text(scene.get("location_id"))
    player.current_scene_index = int(plot.get("current_scene_index", 0) or 0)
    player.current_scene_time_tag = clean_text(scene.get("time_tag"))
    player.current_scene_beat = clean_text(scene.get("beat"))
    player.inventory_json = clone_json(player_profile_from_snapshot(session_snapshot).get("backpack", []))
    player.attributes_json = build_player_attributes(session_snapshot)
    player.player_profile_json = player_profile_from_snapshot(session_snapshot)
    player.scene_state_json = clone_json(scene)
    player.story_initialized = bool(session_meta.get("story_initialized", False))
    player.last_handoff_reason = clean_text(session_meta.get("last_handoff_reason"))


def upsert_story_character_templates(db: Session, templates: list[dict[str, Any]]) -> list[StoryCharacterTemplate]:
    rows: list[StoryCharacterTemplate] = []
    for raw in templates:
        if not isinstance(raw, dict):
            continue
        display_name = clean_text(raw.get("display_name") or raw.get("name"))
        occupation = clean_text(raw.get("occupation"))
        template_kind = clean_text(raw.get("template_kind") or raw.get("story_layer") or raw.get("agent_type"), "actor")
        if template_kind not in {"actor", "L2", "L1"}:
            template_kind = "actor"
        template_key = clean_text(raw.get("template_key") or raw.get("character_id"))
        if not template_key and display_name:
            display_slug = display_name.replace(" ", "_").lower()
            occupation_slug = occupation.replace(" ", "_").lower() or "general"
            template_key = f"{template_kind}:{display_slug}:{occupation_slug}"
        display_name = clean_text(raw.get("display_name") or raw.get("name"), template_key)
        if not template_key or not display_name:
            continue
        row = db.scalar(select(StoryCharacterTemplate).where(StoryCharacterTemplate.template_key == template_key))
        if row is None and template_kind == "actor":
            row = db.scalar(
                select(StoryCharacterTemplate).where(
                    StoryCharacterTemplate.display_name == display_name,
                    StoryCharacterTemplate.occupation == (occupation or None),
                    StoryCharacterTemplate.template_kind == "actor",
                )
            )
        if row is None:
            row = StoryCharacterTemplate(template_key=template_key, display_name=display_name)
            db.add(row)
        row.display_name = display_name
        row.occupation = occupation or None
        row.template_kind = template_kind
        row.default_avatar_url = clean_text(raw.get("default_avatar_url")) or None
        row.default_profile_json = clone_json(raw.get("default_profile_json", {}))
        row.default_runtime_json = clone_json(raw.get("default_runtime_json", {}))
        row.default_dialogue_flags_json = clone_json(raw.get("default_dialogue_flags_json", []))
        row.starter_enabled = bool(raw.get("starter_enabled", False))
        rows.append(row)
    return rows


def seed_starter_story_characters(db: Session, player_id: int) -> None:
    templates = list(
        db.scalars(
            select(StoryCharacterTemplate)
            .where(
                StoryCharacterTemplate.starter_enabled.is_(True),
                StoryCharacterTemplate.template_kind.in_(("L1", "L2")),
            )
            .order_by(StoryCharacterTemplate.id.asc())
        )
    )
    if not templates:
        return
    existing = {
        row.actor_character_id: row
        for row in db.scalars(select(PlayerStoryCharacter).where(PlayerStoryCharacter.player_id == player_id))
    }
    for template in templates:
        if template.template_key in existing:
            continue
        db.add(
            PlayerStoryCharacter(
                player_id=player_id,
                template_id=template.id,
                actor_character_id=template.template_key,
                display_name=template.display_name,
                avatar_url=template.default_avatar_url,
                agent_layer=template.template_kind,
                has_met=False,
                affection_score=0,
                life_status=clean_text(template.default_runtime_json.get("life_status"), "alive"),
                is_on_stage=False,
                is_active=True,
                is_offstage=template.template_kind == "L1",
                dialogue_flags_json=clone_json(template.default_dialogue_flags_json),
                runtime_state_json=clone_json(template.default_runtime_json),
                profile_snapshot_json=clone_json(template.default_profile_json),
                first_seen_turn=None,
                last_seen_turn=None,
            )
        )


def upsert_world_state(db: Session, player_id: int, session_snapshot: dict[str, Any]) -> None:
    row = db.scalar(select(PlayerWorldState).where(PlayerWorldState.player_id == player_id))
    if row is None:
        row = PlayerWorldState(player_id=player_id)
        db.add(row)
    row.world_state_json = build_world_state_payload(session_snapshot)
    row.plot_flags_json = build_plot_flags_payload(session_snapshot)
    row.scene_flags_json = build_scene_flags_payload(session_snapshot)


def upsert_story_characters(db: Session, player_id: int, session_snapshot: dict[str, Any]) -> None:
    records = build_story_character_records(session_snapshot)
    if not records:
        return
    existing_rows = {
        row.actor_character_id: row
        for row in db.scalars(select(PlayerStoryCharacter).where(PlayerStoryCharacter.player_id == player_id))
    }
    templates = {row.template_key: row for row in db.scalars(select(StoryCharacterTemplate))}
    for record in records:
        actor_character_id = record["actor_character_id"]
        row = existing_rows.get(actor_character_id)
        if row is None:
            matched_template = templates.get(actor_character_id)
            row = PlayerStoryCharacter(
                player_id=player_id,
                actor_character_id=actor_character_id,
                display_name=record["display_name"],
                template_id=matched_template.id if matched_template is not None else None,
                agent_layer=clean_text(record.get("agent_layer"), "L2"),
            )
            db.add(row)
            existing_rows[actor_character_id] = row
        row.display_name = record["display_name"]
        row.avatar_url = record["avatar_url"]
        row.agent_layer = clean_text(record.get("agent_layer"), row.agent_layer or "L2")
        row.has_met = bool(record["has_met"])
        row.affection_score = record["affection_score"]
        row.life_status = record["life_status"]
        row.is_on_stage = bool(record["is_on_stage"])
        row.is_active = bool(record.get("is_active", True))
        row.is_offstage = bool(record.get("is_offstage", False))
        row.dialogue_flags_json = clone_json(record["dialogue_flags_json"])
        row.runtime_state_json = clone_json(record["runtime_state_json"])
        row.profile_snapshot_json = clone_json(record["profile_snapshot_json"])
        row.first_seen_turn = record["first_seen_turn"]
        row.last_seen_turn = record["last_seen_turn"]


def upsert_actor_interactions(db: Session, player_id: int, session_snapshot: dict[str, Any]) -> None:
    records = build_actor_interaction_records(session_snapshot)
    if not records:
        return

    templates = list(db.scalars(select(StoryCharacterTemplate)))
    templates_by_key = {row.template_key: row for row in templates}
    templates_by_identity = {
        (row.display_name, row.occupation or "", row.template_kind): row
        for row in templates
    }
    existing_rows = {
        row.template_id: row
        for row in db.scalars(select(PlayerActorInteraction).where(PlayerActorInteraction.player_id == player_id))
    }

    for record in records:
        template_key = clean_text(record.get("template_key"), clean_text(record.get("actor_character_id")))
        display_name = clean_text(record.get("display_name"), template_key)
        occupation = clean_text(record.get("occupation"))
        template = templates_by_key.get(template_key) or templates_by_identity.get((display_name, occupation, "actor"))
        if template is None:
            template = StoryCharacterTemplate(
                template_key=template_key,
                display_name=display_name,
                occupation=occupation or None,
                template_kind="actor",
                default_profile_json=clone_json(record.get("profile_snapshot_json", {})),
            )
            db.add(template)
            db.flush()
            templates_by_key[template_key] = template
            templates_by_identity[(display_name, occupation, "actor")] = template

        row = existing_rows.get(template.id)
        if row is None:
            row = PlayerActorInteraction(
                player_id=player_id,
                template_id=template.id,
            )
            db.add(row)
            existing_rows[template.id] = row

        row.favor_score = record["favor_score"]
        row.interaction_flags_json = clone_json(record["interaction_flags_json"])
        row.interaction_state_json = clone_json(record["interaction_state_json"])
        row.met_count = int(record.get("met_count", 0) or 0)
        row.last_seen_turn = record.get("last_seen_turn")


def upsert_player_quests(db: Session, player_id: int, session_snapshot: dict[str, Any]) -> None:
    records = build_player_quest_records(session_snapshot)
    existing_rows = {
        row.quest_key: row
        for row in db.scalars(select(PlayerQuest).where(PlayerQuest.player_id == player_id))
    }
    active_keys = {str(record["quest_key"]) for record in records}

    for record in records:
        quest_key = str(record["quest_key"])
        row = existing_rows.get(quest_key)
        if row is None:
            row = PlayerQuest(player_id=player_id, quest_key=quest_key)
            db.add(row)
            existing_rows[quest_key] = row

        row.category = clean_text(record.get("category"), row.category or "story")
        row.title = clean_text(record.get("title"), quest_key)
        row.description = clean_text(record.get("description"))
        row.status = clean_text(record.get("status"), "active")
        row.sort_order = int(record.get("sort_order", 0) or 0)
        row.progress_json = clone_json(record.get("progress_json", {}))
        row.source_json = clone_json(record.get("source_json", {}))
        row.completed_at = None

    for quest_key, row in existing_rows.items():
        if quest_key in active_keys:
            continue
        if clean_text(row.source_json.get("source")) != "runtime_snapshot":
            continue
        row.status = "inactive"


def insert_snapshot(
    db: Session, *, player_id: int, session_snapshot: dict[str, Any], save_kind: str, save_label: str | None
) -> PlayerSaveSnapshot:
    snapshot_row = PlayerSaveSnapshot(
        player_id=player_id,
        save_kind=clean_text(save_kind, "manual"),
        save_label=clean_text(save_label) or None,
        snapshot_version=SNAPSHOT_VERSION,
        game_state_json=clone_json(require_snapshot_value(session_snapshot, "state", dict)),
        character_profiles_json=clone_json(require_snapshot_value(session_snapshot, "character_profiles", dict)),
        scene_config_json=clone_json(require_snapshot_value(session_snapshot, "scene_config", dict)),
        session_config_json=clone_json(require_snapshot_value(session_snapshot, "session", dict)),
        world_state_json=build_world_state_payload(session_snapshot),
    )
    db.add(snapshot_row)
    db.flush()
    return snapshot_row
