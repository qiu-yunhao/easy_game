export type BackpackItem = {
  id: string;
  name: string;
  quantity: number;
};

export type AgentType = "actor" | "L2" | "L1";
export type StoryLayer = "player" | "actor" | "L2" | "L1";
export type CharacterStorageMode = "player_bound_instance" | "shared_template";

export type L2AgentProfile = {
  core_drive: string;
  judgement_preference: string[];
  behavior_rule: string[];
  speech_style: string[];
  personality_tags: string[];
};

export type L1AgentProfile = {
  core_conflict: string;
  outer_goal: string;
  inner_need: string;
  contradiction_axes: string[];
  relationship_pressure: string[];
};

export type LayerAssignment = {
  mentioned_in_player_backstory: boolean;
  plot_significance: "core" | "supporting" | "replaceable";
  relationship_depth: "deep" | "functional" | "unknown";
  long_term_plot_significance: boolean;
  can_promote_to_l1: boolean;
  assignment_reason: string;
};

export type CharacterMemoryConfig = {
  long_term_limit: number;
  short_term_limit: number;
  player_memory_limit: number;
  long_term_depth: "full" | "compact";
  player_memory_depth: "full" | "compact";
};

export type PlayerProfileState = {
  character_id: string;
  name: string;
  gender: string;
  race: string;
  background: string;
  spiritual_root: string;
  realm: string;
  main_technique: string;
  persona: string[];
  base_style: string;
  story_role?: string;
  introduction_hint?: string;
  occupation: string;
  agent_type: AgentType;
  story_layer: StoryLayer;
  storage_mode: CharacterStorageMode;
  is_active: boolean;
  is_offstage: boolean;
  l2_profile?: L2AgentProfile;
  l1_profile?: L1AgentProfile;
  layer_assignment: LayerAssignment;
  memory_profile: CharacterMemoryConfig;
  base_relationship: Record<string, number>;
  secrets: string[];
  backpack: BackpackItem[];
};

export const DEFAULT_PLAYER_PROFILE: PlayerProfileState = {
  character_id: "player",
  name: "New Disciple",
  gender: "",
  race: "human",
  background: "",
  spiritual_root: "mixed_root",
  realm: "qi_refining_1",
  main_technique: "basic_breathing_art",
  persona: [],
  base_style: "",
  occupation: "",
  agent_type: "actor",
  story_layer: "player",
  storage_mode: "player_bound_instance",
  is_active: true,
  is_offstage: false,
  layer_assignment: {
    mentioned_in_player_backstory: false,
    plot_significance: "supporting",
    relationship_depth: "unknown",
    long_term_plot_significance: false,
    can_promote_to_l1: false,
    assignment_reason: "",
  },
  memory_profile: {
    long_term_limit: 3,
    short_term_limit: 30,
    player_memory_limit: 3,
    long_term_depth: "compact",
    player_memory_depth: "compact",
  },
  base_relationship: {},
  secrets: [],
  backpack: [],
};

export function createInitialPlayerProfileState(
  overrides: Partial<PlayerProfileState> = {},
): PlayerProfileState {
  return {
    ...DEFAULT_PLAYER_PROFILE,
    ...overrides,
    layer_assignment: {
      ...DEFAULT_PLAYER_PROFILE.layer_assignment,
      ...(overrides.layer_assignment || {}),
    },
    memory_profile: {
      ...DEFAULT_PLAYER_PROFILE.memory_profile,
      ...(overrides.memory_profile || {}),
    },
    backpack: Array.isArray(overrides.backpack)
      ? overrides.backpack.map((item) => {
          const parsedQuantity = Number(item.quantity || 0);
          return {
            id: item.id,
            name: item.name,
            quantity: Number.isFinite(parsedQuantity) && parsedQuantity > 0 ? parsedQuantity : 1,
          };
        })
      : [...DEFAULT_PLAYER_PROFILE.backpack],
  };
}
