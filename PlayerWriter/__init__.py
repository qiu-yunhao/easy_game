from __future__ import annotations

from LazyImport import LazySymbol
from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter


PlaywrightAgent = LazySymbol("PlayerWriter.PlayerWriterAgent", "PlaywrightAgent")

__all__ = [
    "PlaywrightAgent",
    "PlaywrightFormatter",
]
