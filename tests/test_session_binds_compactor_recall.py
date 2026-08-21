from session_bootstrap import build_graph_dependencies
from web_session import SessionConfig, WebGameSession


def test_bootstrap_provider_has_summary_horizon():
    deps = build_graph_dependencies("heuristic", interactive=False)
    provider = deps.actor_memory_provider
    # provider window must match the history manager horizon (45)
    assert getattr(provider, "_summary_horizon_turns", None) == deps.history_manager.summary_horizon_turns


def test_bind_recall_service_pushes_service_and_tenant_to_compactor():
    # heuristic mode + no player_profile skips story init but still builds real deps.
    session = WebGameSession(SessionConfig(mode="heuristic", player_profile=None))
    session.bind_save_context(user_id=7, player_id=3)

    service = object()
    session.bind_recall_service(service)

    compactor = session.deps.memory_compactor
    assert compactor is not None
    assert compactor._recall is service
    assert compactor._user_id == 7
    assert compactor._player_id == 3
