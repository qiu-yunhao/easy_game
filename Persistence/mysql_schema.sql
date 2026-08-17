CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_character_templates (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  template_key VARCHAR(128) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  occupation VARCHAR(128) NULL,
  template_kind VARCHAR(16) NOT NULL DEFAULT 'actor',
  default_avatar_url VARCHAR(255) NULL,
  default_profile_json JSON NOT NULL,
  default_runtime_json JSON NOT NULL,
  default_dialogue_flags_json JSON NOT NULL,
  starter_enabled TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_story_character_templates_key (template_key),
  UNIQUE KEY uq_story_character_templates_identity (display_name, occupation, template_kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS players (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  slot_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  mode VARCHAR(32) NOT NULL,
  narration_style_preset VARCHAR(64) NOT NULL,
  player_character_id VARCHAR(64) NOT NULL,
  current_story_node_id VARCHAR(128) NOT NULL DEFAULT '',
  current_scene_id VARCHAR(128) NOT NULL DEFAULT '',
  current_scene_location_id VARCHAR(128) NOT NULL DEFAULT '',
  current_scene_index INT NOT NULL DEFAULT 0,
  current_scene_time_tag VARCHAR(64) NOT NULL DEFAULT '',
  current_scene_beat VARCHAR(128) NOT NULL DEFAULT '',
  inventory_json JSON NOT NULL,
  attributes_json JSON NOT NULL,
  player_profile_json JSON NOT NULL,
  scene_state_json JSON NOT NULL,
  story_initialized TINYINT(1) NOT NULL DEFAULT 0,
  last_handoff_reason TEXT NOT NULL,
  last_saved_at DATETIME NULL,
  latest_snapshot_id BIGINT UNSIGNED NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_players_user_id (user_id),
  CONSTRAINT fk_players_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_world_states (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id BIGINT UNSIGNED NOT NULL,
  world_state_json JSON NOT NULL,
  plot_flags_json JSON NOT NULL,
  scene_flags_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_player_world_states_player_id (player_id),
  CONSTRAINT fk_player_world_states_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_story_characters (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id BIGINT UNSIGNED NOT NULL,
  template_id BIGINT UNSIGNED NULL,
  actor_character_id VARCHAR(128) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  avatar_url VARCHAR(255) NULL,
  agent_layer VARCHAR(16) NOT NULL DEFAULT 'L2',
  has_met TINYINT(1) NOT NULL DEFAULT 0,
  affection_score DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  life_status VARCHAR(32) NOT NULL DEFAULT 'alive',
  is_on_stage TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  is_offstage TINYINT(1) NOT NULL DEFAULT 0,
  dialogue_flags_json JSON NOT NULL,
  runtime_state_json JSON NOT NULL,
  profile_snapshot_json JSON NOT NULL,
  first_seen_turn INT NULL,
  last_seen_turn INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_player_story_characters_player_actor (player_id, actor_character_id),
  CONSTRAINT fk_player_story_characters_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
  CONSTRAINT fk_player_story_characters_template FOREIGN KEY (template_id) REFERENCES story_character_templates(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_actor_interactions (
  player_id BIGINT UNSIGNED NOT NULL,
  template_id BIGINT UNSIGNED NOT NULL,
  favor_score DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  interaction_flags_json JSON NOT NULL,
  interaction_state_json JSON NOT NULL,
  met_count INT NOT NULL DEFAULT 0,
  last_seen_turn INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_id, template_id),
  CONSTRAINT fk_player_actor_interactions_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
  CONSTRAINT fk_player_actor_interactions_template FOREIGN KEY (template_id) REFERENCES story_character_templates(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_quests (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id BIGINT UNSIGNED NOT NULL,
  quest_key VARCHAR(128) NOT NULL,
  category VARCHAR(32) NOT NULL DEFAULT 'story',
  title VARCHAR(128) NOT NULL,
  description TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  sort_order INT NOT NULL DEFAULT 0,
  progress_json JSON NOT NULL,
  source_json JSON NOT NULL,
  started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_player_quests_player_key (player_id, quest_key),
  CONSTRAINT fk_player_quests_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_save_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id BIGINT UNSIGNED NOT NULL,
  save_kind VARCHAR(32) NOT NULL DEFAULT 'manual',
  save_label VARCHAR(128) NULL,
  snapshot_version INT NOT NULL DEFAULT 1,
  game_state_json JSON NOT NULL,
  character_profiles_json JSON NOT NULL,
  scene_config_json JSON NOT NULL,
  session_config_json JSON NOT NULL,
  world_state_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_player_save_snapshots_player_id (player_id),
  CONSTRAINT fk_player_save_snapshots_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recall_index_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id BIGINT UNSIGNED NOT NULL,
  scene_id VARCHAR(128) NOT NULL,
  indexed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_recall_index_log_player_scene (player_id, scene_id),
  CONSTRAINT fk_recall_index_log_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
