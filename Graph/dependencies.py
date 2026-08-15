from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from Actor import ActorAgent
from Actor.ActorCreateAgent import ActorCreateAgent
from CharacterProfile import CharacterProfile
from CharacterRepository import CharacterRepository
from ComponentFactory import ComponentFactory
from Director import DirectorAgent
from GameState import GameState
from GameplayTuning import GameplayTuning
from Graph.hooks import HookRegistry
from History import HistoryManager
from Narrator.NarratorAgent import NarratorAgent
from PlayerControl import PlayerInterface, SemanticParserAgent
from PlayerWriter import PlaywrightAgent
from SceneConfig import SceneConfig
from Scheduler.SchedulerPolicy import SchedulerPolicy
from SceneEnd.SceneEndHeuristics import SceneEndPolicy
from StylisticPolish import StylisticPolishAgent

if TYPE_CHECKING:
    from History.HistorySummarizerAgent import HistorySummarizerAgent
    from PlayerControl.PlayerIntentPlannerAgent import PlayerIntentPlannerAgent
    from PlayerControl.PlayerCommandTools import PlayerCommandToolRuntime
    from Memory.provider import ActorMemoryProvider


@dataclass(slots=True)
class GraphDependencies:
    scene_config: SceneConfig
    character_profiles: CharacterRepository | dict[str, CharacterProfile]
    playwright_agent: PlaywrightAgent | None = None
    actor_create_agent: ActorCreateAgent | None = None
    director_agent: DirectorAgent | None = None
    actor_agent: ActorAgent | None = None
    l2_actor_agent: ActorAgent | None = None
    l1_actor_agent: ActorAgent | None = None
    narrator_agent: NarratorAgent | None = None
    player_intent_planner_agent: "PlayerIntentPlannerAgent | None" = None
    semantic_parser_agent: SemanticParserAgent | None = None
    player_command_tools: "PlayerCommandToolRuntime | None" = None
    stylistic_polish_agent: StylisticPolishAgent | None = None
    history_summarizer_agent: "HistorySummarizerAgent | None" = None
    history_manager: HistoryManager | None = None
    scheduler_policy: SchedulerPolicy | None = None
    scene_end_policy: SceneEndPolicy | None = None
    player_interface: PlayerInterface | None = None
    gameplay_tuning: GameplayTuning = field(default_factory=GameplayTuning)
    component_factory: ComponentFactory = field(default_factory=ComponentFactory)
    agent_first: bool = False
    actor_create_signature: str = ""
    beat_execution_subgraph: Callable[[GameState], GameState] | None = None
    # 只读记忆工厂:Actor 读路径由它 build(actor_id, state) 出 memory_ctx。
    actor_memory_provider: "ActorMemoryProvider | None" = None
    hook_registry: HookRegistry = field(default_factory=HookRegistry)

    def __post_init__(self) -> None:
        # 统一把裸 dict 归一化为 CharacterRepository,保证单一写入口。
        if not isinstance(self.character_profiles, CharacterRepository):
            self.character_profiles = CharacterRepository(self.character_profiles)
