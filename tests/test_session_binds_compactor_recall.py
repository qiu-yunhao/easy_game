from session_bootstrap import build_graph_dependencies


def test_bootstrap_provider_has_summary_horizon():
    deps = build_graph_dependencies("heuristic", interactive=False)
    provider = deps.actor_memory_provider
    # provider window must match the history manager horizon (45)
    assert getattr(provider, "_summary_horizon_turns", None) == deps.history_manager.summary_horizon_turns
