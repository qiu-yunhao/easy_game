from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial

from GameState import GameState
from Graph.graph_compile import compile_graph_with_nodes
from Graph.narration_nodes import chapter_intro_node, story_intro_node
from Graph.nodes import (
    GraphDependencies,
    beat_resolution_node,
    chapter_expansion_node,
    director_node,
    refresh_history_node,
    scene_candidates_node,
    scheduler_node,
    story_cast_construction_node,
    story_outline_brief_node,
    story_outline_revision_node,
    story_premise_node,
)
from Graph.transition_nodes import chapter_archive_node, chapter_transition_node, scene_transition_node


STORY_AUTHORING_NODES = (
    ("story_premise", story_premise_node),
    ("story_outline_draft", story_outline_brief_node),
    ("story_cast_construction", story_cast_construction_node),
    ("story_outline_revision", story_outline_revision_node),
)
CHAPTER_PREPARATION_NODES = (
    ("chapter_expansion", chapter_expansion_node),
    ("chapter_intro", chapter_intro_node),
    ("refresh_history", refresh_history_node),
    ("scene_candidates", scene_candidates_node),
)
SCENE_DIRECTION_NODES = (("director", director_node), ("scheduler", scheduler_node))
TRANSITION_NODES = (
    ("scene_transition", scene_transition_node),
    ("chapter_archive", chapter_archive_node),
    ("chapter_transition", chapter_transition_node),
)


def _bind_graph_nodes(deps: GraphDependencies, *node_order):
    return [(name, partial(node, deps=deps)) for name, node in node_order]


def _compile_bound_nodes(deps: GraphDependencies, *node_order):
    return compile_graph_with_nodes(_bind_graph_nodes(deps, *node_order))


def _run_story_steps(state: GameState, deps: GraphDependencies, *steps):
    for step in steps:
        state = step(state, deps)
    return state


def build_story_authoring_subgraph(deps: GraphDependencies):
    return _compile_bound_nodes(deps, *STORY_AUTHORING_NODES)


def build_story_setup_subgraph(deps: GraphDependencies):
    story_authoring_subgraph = build_story_authoring_subgraph(deps)
    return compile_graph_with_nodes(
        [
            ("story_authoring_subgraph", story_authoring_subgraph.invoke),
            ("story_intro", partial(story_intro_node, deps=deps)),
        ]
    )


def build_chapter_preparation_subgraph(deps: GraphDependencies):
    return _compile_bound_nodes(deps, *CHAPTER_PREPARATION_NODES)


def build_scene_direction_subgraph(deps: GraphDependencies):
    return _compile_bound_nodes(deps, *SCENE_DIRECTION_NODES)


def build_transition_subgraph(deps: GraphDependencies):
    return _compile_bound_nodes(deps, *TRANSITION_NODES)


def build_chapter_runtime_subgraph(deps: GraphDependencies):
    return compile_graph_with_nodes(
        [
            ("chapter_preparation_subgraph", build_chapter_preparation_subgraph(deps).invoke),
            ("scene_direction_subgraph", build_scene_direction_subgraph(deps).invoke),
            ("beat_resolution", partial(beat_resolution_node, deps=deps)),
            ("transition_subgraph", build_transition_subgraph(deps).invoke),
        ]
    )


def prepare_story_setup(state: GameState, deps: GraphDependencies) -> GameState:
    return _run_story_steps(
        state,
        deps,
        *(node for _, node in STORY_AUTHORING_NODES),
        story_intro_node,
    )


def prepare_chapter_turn(state: GameState, deps: GraphDependencies) -> GameState:
    expanded_state = chapter_expansion_node(state, deps)
    with ThreadPoolExecutor(max_workers=2) as executor:
        intro_future = executor.submit(chapter_intro_node, expanded_state, deps)
        scene_candidates_future = executor.submit(scene_candidates_node, expanded_state, deps)
        intro_state = intro_future.result()
        scene_candidates_state = scene_candidates_future.result()

    return _run_story_steps(
        {
            **intro_state,
            "characters": scene_candidates_state.get(
                "characters",
                intro_state.get("characters", expanded_state.get("characters", {})),
            ),
            "plot": scene_candidates_state["plot"],
            "scene": scene_candidates_state["scene"],
            "scene_plan": scene_candidates_state["scene_plan"],
            "runtime": {
                **intro_state["runtime"],
                "eligible_actors": list(
                    scene_candidates_state["runtime"].get(
                        "eligible_actors",
                        intro_state["runtime"].get("eligible_actors", []),
                    )
                ),
                "scene_candidates": list(scene_candidates_state["runtime"].get("scene_candidates", [])),
            },
        },
        deps,
        refresh_history_node,
        director_node,
        scheduler_node,
    )


def initialize_story_session(state: GameState, deps: GraphDependencies) -> GameState:
    return prepare_chapter_turn(prepare_story_setup(state, deps), deps)


def resolve_story_turn(state: GameState, deps: GraphDependencies) -> GameState:
    return _run_story_steps(
        state,
        deps,
        beat_resolution_node,
        *(node for _, node in TRANSITION_NODES),
    )


def plan_story_round(state: GameState, deps: GraphDependencies) -> GameState:
    return resolve_story_turn(initialize_story_session(state, deps), deps)


def build_game_graph(deps: GraphDependencies):
    return compile_graph_with_nodes(
        [
            ("story_setup_subgraph", build_story_setup_subgraph(deps).invoke),
            ("chapter_runtime_subgraph", build_chapter_runtime_subgraph(deps).invoke),
        ]
    )
