from session_bootstrap import build_graph_dependencies


def test_history_manager_constants_fixed():
    deps = build_graph_dependencies("heuristic")
    assert deps.history_manager.compression_trigger_size == 30
    assert deps.history_manager.summary_horizon_turns == 45


def test_compactor_attached_and_started():
    deps = build_graph_dependencies("heuristic")
    assert deps.memory_store is not None
    assert deps.memory_compactor is not None
    deps.memory_compactor.stop()
