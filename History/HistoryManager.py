from __future__ import annotations

from typing import Any

from GameState import GameState
from History.GameMemory import HistoryItem, MemoryState, empty_memory_state
from History.HistoryCompression import (
    build_compression_chunks,
    build_history_score_payload,
    build_raw_block,
    build_summary_block,
    heuristic_chunk_summary,
    heuristic_score_items,
    merge_scores_with_history,
    summarize_chunk_payload,
)
from History.HistoryInference import (
    build_director_memory,
    build_playwright_memory,
    build_scene_memory_from_blocks,
    build_scheduler_memory,
)
from History.HistorySummarizerAgent import HistorySummarizerAgent


class HistoryManager:
    def __init__(
        self,
        summarizer_agent: HistorySummarizerAgent | None = None,
        compression_trigger_size: int = 30,
        summary_horizon_turns: int = 45,
        scheduler_round_window: int = 4,
    ) -> None:
        self.summarizer_agent = summarizer_agent
        self.compression_trigger_size = compression_trigger_size
        self.summary_horizon_turns = summary_horizon_turns
        self.scheduler_round_window = scheduler_round_window

    def should_refresh(self, state: GameState) -> bool:
        current_turn = state["runtime"]["turn_index"]
        has_blocks = bool(state["memory"]["scene_memory"]["compressed_blocks"])

        if current_turn == 0 and not has_blocks:
            return True
        if self.get_uncompressed_history_count(state) >= self.compression_trigger_size:
            return True
        if state["runtime"].get("scene_finished", False):
            return True
        return False

    def get_uncompressed_history_items(self, state: GameState) -> list[HistoryItem]:
        last_compressed_turn = state["memory"]["last_compressed_turn"]
        return [item for item in state["history"] if item["turn"] > last_compressed_turn]

    def get_uncompressed_history_count(self, state: GameState) -> int:
        return len(self.get_uncompressed_history_items(state))

    def build_memory(self, state: GameState) -> MemoryState:
        base_memory = state.get("memory") or empty_memory_state()
        existing_blocks = list(base_memory["scene_memory"]["compressed_blocks"])
        new_history_items = self.get_uncompressed_history_items(state)
        compressed_blocks = list(existing_blocks)

        if new_history_items:
            score_payload = build_history_score_payload(state, new_history_items)
            score_items = self._score_history_items(new_history_items, score_payload)
            scored_items = merge_scores_with_history(new_history_items, score_items)
            chunks = build_compression_chunks(scored_items)

            for chunk in chunks:
                bucket = chunk[0]["importance_bucket"]
                if bucket == "high":
                    compressed_blocks.append(build_raw_block(chunk))
                else:
                    summary_result = self._summarize_chunk(state, chunk)
                    compressed_blocks.append(build_summary_block(chunk, summary_result))

        scene_memory = build_scene_memory_from_blocks(
            state,
            compressed_blocks,
            self.summary_horizon_turns,
        )
        playwright_memory = build_playwright_memory(state, scene_memory)
        director_memory = build_director_memory(state, scene_memory)
        scheduler_memory = build_scheduler_memory(
            state,
            scene_memory,
            self.scheduler_round_window,
        )
        last_compressed_turn = (
            compressed_blocks[-1]["turn_end"]
            if compressed_blocks
            else base_memory["last_compressed_turn"]
        )

        return {
            "last_compressed_turn": last_compressed_turn,
            "scene_memory": scene_memory,
            "playwright_memory": playwright_memory,
            "director_memory": director_memory,
            "scheduler_memory": scheduler_memory,
        }

    def _score_history_items(
        self,
        history_items: list[HistoryItem],
        score_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.summarizer_agent is None:
            return heuristic_score_items(history_items)
        try:
            return self.summarizer_agent.score_history_items(score_payload)
        except (KeyError, TypeError, ValueError):
            return heuristic_score_items(history_items)

    def _summarize_chunk(
        self,
        state: GameState,
        chunk: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.summarizer_agent is None:
            return heuristic_chunk_summary(chunk)
        payload = summarize_chunk_payload(state, chunk)
        try:
            return self.summarizer_agent.summarize_chunk(payload)
        except (KeyError, TypeError, ValueError):
            return heuristic_chunk_summary(chunk)
