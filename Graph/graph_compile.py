from __future__ import annotations

from typing import Any, Callable

from GameState import GameState


NodeStep = Callable[[GameState], GameState]
LANGGRAPH_MISSING_MESSAGE = (
    "langgraph is not installed. Use the in-process fallback runners, "
    "or install langgraph before compiling the graph."
)


def compile_graph_with_nodes(
    node_order: list[tuple[str, NodeStep]],
    *,
    fallback_to_runner: bool = False,
) -> Any:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        if fallback_to_runner:
            def _run(state: GameState) -> GameState:
                for _, node in node_order:
                    state = node(state)
                return state

            return _run
        raise RuntimeError(LANGGRAPH_MISSING_MESSAGE) from exc

    graph = StateGraph(GameState)
    for name, node in node_order:
        graph.add_node(name, node)

    graph.set_entry_point(node_order[0][0])
    for current, nxt in zip(node_order, node_order[1:]):
        graph.add_edge(current[0], nxt[0])
    graph.add_edge(node_order[-1][0], END)
    compiled = graph.compile()
    return compiled.invoke if fallback_to_runner else compiled
