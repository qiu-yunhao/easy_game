from __future__ import annotations

import sys
import types
import unittest

openai_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - import shim
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs


openai_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", openai_stub)

from Graph.beat_subgraph import run_beat_loop


def _state(history_len: int = 0, *, on_stage=None, pending=None):
    return {
        "runtime": {
            "next_act": None,
            "pending_beat_actors": list(pending or []),
            "pending_response_groups": [],
            "beat_fallback_turns_remaining": 0,
        },
        "scene": {"on_stage": list(on_stage or [])},
        "player": {"enabled": False, "controlled_character": None},
        "history": [{"turn": i, "content": f"seed-{i}"} for i in range(history_len)],
    }


def _append(state, content):
    return {
        **state,
        "history": [*state["history"], {"turn": len(state["history"]), "content": content}],
    }


class RunBeatLoopStreamingTests(unittest.TestCase):
    def _make_steps(self, actor_lines):
        """Build scheduler/execution steps that emit one actor line per turn.

        The scheduler pops the next pending actor into next_act; the execution
        subgraph appends that actor's line to history and clears next_act.
        """
        lines = list(actor_lines)

        def scheduler_step(current):
            pending = current["runtime"].get("pending_beat_actors", [])
            if not pending:
                return current
            nxt, *rest = pending
            return {
                **current,
                "runtime": {
                    **current["runtime"],
                    "next_act": {"actor": nxt},
                    "pending_beat_actors": rest,
                },
            }

        def execution_subgraph(current):
            actor = current["runtime"]["next_act"]["actor"]
            content = lines.pop(0) if lines else f"{actor}-acts"
            nxt = _append(current, content)
            return {**nxt, "runtime": {**nxt["runtime"], "next_act": None}}

        return scheduler_step, execution_subgraph

    def test_no_callback_behaves_identically(self):
        scheduler_step, execution_subgraph = self._make_steps(["a-line", "b-line"])
        state = _state(pending=["a", "b"], on_stage=["a", "b"])
        result = run_beat_loop(
            state,
            deps=None,
            scheduler_step=scheduler_step,
            execution_subgraph=execution_subgraph,
            flush_step=lambda s: s,
            wrap_step=lambda s: s,
        )
        contents = [h["content"] for h in result["history"]]
        self.assertEqual(contents, ["a-line", "b-line"])

    def test_emits_each_committed_entry_once_in_order(self):
        scheduler_step, execution_subgraph = self._make_steps(["a-line", "b-line"])
        state = _state(pending=["a", "b"], on_stage=["a", "b"])
        emitted = []
        run_beat_loop(
            state,
            deps=None,
            scheduler_step=scheduler_step,
            execution_subgraph=execution_subgraph,
            flush_step=lambda s: s,
            wrap_step=lambda s: s,
            on_event=emitted.append,
        )
        self.assertEqual([e["content"] for e in emitted], ["a-line", "b-line"])

    def test_does_not_re_emit_seed_history(self):
        scheduler_step, execution_subgraph = self._make_steps(["a-line"])
        state = _state(history_len=3, pending=["a"], on_stage=["a"])
        emitted = []
        run_beat_loop(
            state,
            deps=None,
            scheduler_step=scheduler_step,
            execution_subgraph=execution_subgraph,
            flush_step=lambda s: s,
            wrap_step=lambda s: s,
            on_event=emitted.append,
        )
        self.assertEqual([e["content"] for e in emitted], ["a-line"])

    def test_flush_and_wrap_entries_are_emitted(self):
        scheduler_step, execution_subgraph = self._make_steps(["a-line"])
        state = _state(pending=["a"], on_stage=["a"])
        emitted = []
        run_beat_loop(
            state,
            deps=None,
            scheduler_step=scheduler_step,
            execution_subgraph=execution_subgraph,
            flush_step=lambda s: _append(s, "flush-line"),
            wrap_step=lambda s: _append(s, "wrap-line"),
            on_event=emitted.append,
        )
        self.assertEqual(
            [e["content"] for e in emitted],
            ["a-line", "flush-line", "wrap-line"],
        )


if __name__ == "__main__":
    unittest.main()
