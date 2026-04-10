from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Graph.nodes import GraphDependencies


def resolve_component(
    deps: "GraphDependencies",
    attr_name: str,
    builder_name: str,
    *,
    required_name: str,
) -> object | None:
    component = getattr(deps, attr_name)
    if component is None and deps.agent_first:
        component = getattr(deps.component_factory, builder_name)()
        setattr(deps, attr_name, component)
    if component is None and deps.agent_first:
        raise RuntimeError(f"Agent-first mode requires {required_name}, but none is available.")
    return component


def resolve_playwright_agent(deps: "GraphDependencies"):
    return resolve_component(
        deps,
        "playwright_agent",
        "build_playwright_agent",
        required_name="a PlaywrightAgent",
    )


def resolve_actor_create_agent(deps: "GraphDependencies"):
    return resolve_component(
        deps,
        "actor_create_agent",
        "build_actor_create_agent",
        required_name="an ActorCreateAgent",
    )


def resolve_narrator_agent(deps: "GraphDependencies"):
    return resolve_component(
        deps,
        "narrator_agent",
        "build_narrator_agent",
        required_name="a NarratorAgent",
    )


def resolve_stylistic_polish_agent(deps: "GraphDependencies"):
    return resolve_component(
        deps,
        "stylistic_polish_agent",
        "build_stylistic_polish_agent",
        required_name="a StylisticPolishAgent",
    )
