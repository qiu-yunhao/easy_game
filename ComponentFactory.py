from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from importlib import import_module
from typing import TYPE_CHECKING, Callable

from GameplayTuning import SceneEndTuning

if TYPE_CHECKING:
    from Actor.ActorAgent import ActorAgent
    from Actor.L1ActorAgent import L1ActorAgent
    from Actor.L2ActorAgent import L2ActorAgent
    from actor_create_agent import ActorCreateAgent
    from Director.DirectorAgent import DirectorAgent
    from Director.DirectorFormatter import DirectorFormatter
    from History.HistorySummarizerAgent import HistorySummarizerAgent
    from Narrator.NarratorAgent import NarratorAgent
    from PlayerControl.PlayerIntentPlannerAgent import PlayerIntentPlannerAgent
    from PlayerControl.SemanticParserAgent import SemanticParserAgent
    from PlayerWriter.PlayerWriterAgent import PlaywrightAgent
    from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter
    from SceneEnd.SceneEndHeuristics import SceneEndPolicy
    from Scheduler.SchedulerPolicy import SchedulerPolicy
    from SupportingSceneIntentPolicy import SupportingSceneIntentPolicy
    from StylisticPolish import StylisticPolishAgent


def _build_from_module(module_name: str, class_name: str, *args: object, **kwargs: object) -> object:
    return getattr(import_module(module_name), class_name)(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class ComponentFactoryConfig:
    director_formatter_builder: Callable[[], "DirectorFormatter"] = partial(_build_from_module, "Director.DirectorFormatter", "DirectorFormatter")
    playwright_formatter_builder: Callable[[], "PlaywrightFormatter"] = partial(_build_from_module, "PlayerWriter.PlayerWriterFormatter", "PlaywrightFormatter")
    scheduler_policy_builder: Callable[[], "SchedulerPolicy"] = partial(_build_from_module, "Scheduler.SchedulerPolicy", "HeuristicSchedulerPolicy")
    scene_end_policy_builder: Callable[[SceneEndTuning], "SceneEndPolicy"] = partial(_build_from_module, "SceneEnd.SceneEndHeuristics", "HeuristicSceneEndPolicy")


class ComponentFactory:
    def __init__(self, config: ComponentFactoryConfig | None = None) -> None:
        self.config = config or ComponentFactoryConfig()

    def _build_component(self, module_name: str, class_name: str, **kwargs: object) -> object:
        return _build_from_module(module_name, class_name, **kwargs)

    def _build_formatter_agent(
        self, module_name: str, class_name: str, formatter_builder: Callable[[], object], **kwargs: object
    ) -> object:
        formatter = kwargs.pop("formatter", None) or formatter_builder()
        return self._build_component(module_name, class_name, formatter=formatter, component_factory=self, **kwargs)

    def build_actor_agent(self, **kwargs: object) -> "ActorAgent":
        return self._build_component("Actor.ActorAgent", "ActorAgent", **kwargs)

    def build_l2_actor_agent(self, **kwargs: object) -> "L2ActorAgent":
        policy = kwargs.pop("supporting_scene_intent_policy", None) or self.build_supporting_scene_intent_policy()
        return self._build_component(
            "Actor.L2ActorAgent",
            "L2ActorAgent",
            supporting_scene_intent_policy=policy,
            **kwargs,
        )

    def build_l1_actor_agent(self, **kwargs: object) -> "L1ActorAgent":
        return self._build_component("Actor.L1ActorAgent", "L1ActorAgent", **kwargs)

    def build_actor_create_agent(self, **kwargs: object) -> "ActorCreateAgent":
        return self._build_component("actor_create_agent", "ActorCreateAgent", **kwargs)

    def build_semantic_parser_agent(self, **kwargs: object) -> "SemanticParserAgent":
        return self._build_component("PlayerControl.SemanticParserAgent", "SemanticParserAgent", **kwargs)

    def build_player_intent_planner_agent(self, **kwargs: object) -> "PlayerIntentPlannerAgent":
        return self._build_component("PlayerControl.PlayerIntentPlannerAgent", "PlayerIntentPlannerAgent", **kwargs)

    def build_narrator_agent(self, **kwargs: object) -> "NarratorAgent":
        return self._build_component("Narrator.NarratorAgent", "NarratorAgent", **kwargs)

    def build_history_summarizer_agent(self, **kwargs: object) -> "HistorySummarizerAgent":
        return self._build_component("History.HistorySummarizerAgent", "HistorySummarizerAgent", **kwargs)

    def build_stylistic_polish_agent(self, **kwargs: object) -> "StylisticPolishAgent":
        return self._build_component("StylisticPolish", "StylisticPolishAgent", **kwargs)

    def build_scheduler_policy(self) -> "SchedulerPolicy":
        return self.config.scheduler_policy_builder()

    def build_supporting_scene_intent_policy(self) -> "SupportingSceneIntentPolicy":
        return self._build_component("SupportingSceneIntentPolicy", "SupportingSceneIntentPolicy")

    def build_scene_end_policy(self, tuning: SceneEndTuning | None = None) -> "SceneEndPolicy":
        return self.config.scene_end_policy_builder(tuning or SceneEndTuning())

    def build_director_agent(self, **kwargs: object) -> "DirectorAgent":
        return self._build_formatter_agent(
            "Director.DirectorAgent", "DirectorAgent", self.config.director_formatter_builder, **kwargs
        )

    def build_playwright_agent(self, **kwargs: object) -> "PlaywrightAgent":
        return self._build_formatter_agent(
            "PlayerWriter.PlayerWriterAgent", "PlaywrightAgent", self.config.playwright_formatter_builder, **kwargs
        )
