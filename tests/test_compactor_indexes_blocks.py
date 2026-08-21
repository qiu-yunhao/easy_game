from History.AsyncMemoryCompactor import AsyncMemoryCompactor
from History.HistoryManager import HistoryManager
from Memory.store import MemoryStore


class _RecordingRecall:
    def __init__(self):
        self.indexed = []

    def index_memory_blocks(self, blocks, *, user_id, player_id):
        self.indexed.append((list(blocks), user_id, player_id))


def _store(trigger=30):
    return MemoryStore(history_manager=HistoryManager(compression_trigger_size=trigger))


def _snapshot(n):
    history = [
        {"turn": t, "actor": "hero", "mode": "speak", "content": f"l{t}", "on_stage": ["hero"], "location_id": "loc"}
        for t in range(1, n + 1)
    ]
    return {
        "plot": {"chapter_id": "c1", "scene_id": "s1", "chapter_goal": "", "plot_flags": {}},
        "scene": {"location_id": "loc", "on_stage": ["hero"], "time_tag": "", "beat": "", "tension": 0.0, "focus_character": ""},
        "runtime": {"turn_index": n, "last_actor": "", "last_mode": ""},
        "history": history,
        "memory": {"last_compressed_turn": 0, "scene_memory": {"compressed_blocks": []}},
        "scene_plan": {"must_happen": [], "must_not_happen": []},
        "characters": {},
        "director_brief": {"who_should_respond": []},
    }


def test_compactor_indexes_new_blocks_on_success():
    recall = _RecordingRecall()
    compactor = AsyncMemoryCompactor(
        memory_store=_store(),
        recall_service=recall,
        user_id=1,
        player_id=1,
    )
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        compactor.take_pending()
        assert recall.indexed
        blocks, uid, pid = recall.indexed[0]
        assert blocks and uid == 1 and pid == 1
    finally:
        compactor.stop()


def test_compactor_without_recall_still_works():
    compactor = AsyncMemoryCompactor(memory_store=_store())
    compactor.start()
    try:
        compactor.enqueue(_snapshot(5))
        compactor.join()
        assert compactor.take_pending() is not None
    finally:
        compactor.stop()
