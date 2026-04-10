from __future__ import annotations

from History.GameMemory import (
    CompressedHistoryBlock,
    HistoryItem,
    MemoryState,
    ScoredHistoryItem,
    empty_memory_state,
)
from LazyImport import LazySymbol


HistoryManager = LazySymbol("History.HistoryManager", "HistoryManager")
HistorySummarizerAgent = LazySymbol(
    "History.HistorySummarizerAgent",
    "HistorySummarizerAgent",
)

__all__ = [
    "CompressedHistoryBlock",
    "HistoryItem",
    "HistoryManager",
    "HistorySummarizerAgent",
    "MemoryState",
    "ScoredHistoryItem",
    "empty_memory_state",
]
