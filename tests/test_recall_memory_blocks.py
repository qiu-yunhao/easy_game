from datatypes import VectorDoc, ScoredDoc
from Recall.service.recall_service import RecallService


class _FakeHybrid:
    def __init__(self, docs):
        self._docs = docs

    def search(self, query, *, top_k=10, filters=None, weights=None, fetch_k=200):
        return [ScoredDoc(doc=d, score=1.0) for d in self._docs if d.metadata.get("doc_type_match", True)]


class _FakeEmbedding:
    def encode(self, texts):
        return [[0.0] for _ in texts]


class _FakeStore:
    def __init__(self):
        self.rows = []

    def upsert(self, rows):
        self.rows.extend(rows)


def _doc(turn_start, turn_end, on_stage_union):
    return VectorDoc(
        doc_id=f"u1:p1:memory_block:{turn_start}-{turn_end}",
        doc_type="memory_block",
        text="t",
        metadata={"turn_start": turn_start, "turn_end": turn_end, "on_stage_union": on_stage_union},
    )


def test_recall_excludes_visible_window_and_offstage():
    docs = [
        _doc(1, 3, ["hero"]),
        _doc(4, 6, ["npc"]),
        _doc(40, 45, ["hero"]),
    ]
    svc = RecallService(embedding=_FakeEmbedding(), vector_store=_FakeStore(), hybrid=_FakeHybrid(docs))
    results = svc.recall_memory_blocks(
        "q", user_id=1, player_id=1, actor_id="hero", window_start=40, top_k=10
    )
    ids = [r.doc.doc_id for r in results]
    assert ids == ["u1:p1:memory_block:1-3"]


def test_index_memory_blocks_upserts():
    store = _FakeStore()
    svc = RecallService(embedding=_FakeEmbedding(), vector_store=store, hybrid=_FakeHybrid([]))
    block = {
        "turn_start": 1, "turn_end": 2, "summary": "s", "key_points": ["k"],
        "actors": ["hero"], "raw_items": [{"turn": 1, "on_stage": ["hero"]}], "max_score": 0.5,
    }
    svc.index_memory_blocks([block], user_id=1, player_id=1)
    assert len(store.rows) == 1
    assert store.rows[0][0].doc_type == "memory_block"
