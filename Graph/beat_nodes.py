from __future__ import annotations

from typing import TYPE_CHECKING

from GameState import GameState
from Graph.hookable_node import HookableNode
from Graph.hooks import HookRegistry
from Graph.narration_nodes import (
    director_lead_in_node,
    director_wrap_up_node,
    narration_subgraph_node,
)
from Graph.nodes import (
    actor_node,
    cultivation_progress_node,
    scene_end_node,
)

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


class DirectorLeadInNode(HookableNode):
    name = "director_lead_in"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return director_lead_in_node(state, self._deps)


class ActorNode(HookableNode):
    name = "actor"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return actor_node(state, self._deps)


class NarrationNode(HookableNode):
    name = "narration"

    def __init__(
        self,
        deps: "GraphDependencies",
        hook_registry: HookRegistry,
        *,
        force_flush: bool = False,
    ) -> None:
        super().__init__(hook_registry)
        self._deps = deps
        self._force_flush = force_flush

    def run(self, state: GameState) -> GameState:
        return narration_subgraph_node(state, self._deps, force_flush=self._force_flush)


class CultivationProgressNode(HookableNode):
    name = "cultivation_progress"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return cultivation_progress_node(state, self._deps)


class SceneEndNode(HookableNode):
    name = "scene_end"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return scene_end_node(state, self._deps)


class DirectorWrapUpNode(HookableNode):
    name = "director_wrap_up"

    def __init__(self, deps: "GraphDependencies", hook_registry: HookRegistry) -> None:
        super().__init__(hook_registry)
        self._deps = deps

    def run(self, state: GameState) -> GameState:
        return director_wrap_up_node(state, self._deps)
