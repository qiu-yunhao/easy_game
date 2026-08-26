from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# 判重只看最近这么多条历史;自动模式的复读通常是紧邻上一两拍的回滚。
_DEFAULT_LOOKBACK = 3
# bigram Jaccard 相似度阈值:>= 视为近乎复述。0.82 经验值,逐字重复=1.0,
# 正常推进(换地点/新动作)一般落在 0.5 以下,留足余量避免误伤。
_DEFAULT_THRESHOLD = 0.82

_PUNCT_WS = re.compile(r"[\s，。、；：？！…—·「」『』“”\"'（）()《》〈〉,.;:?!\-]+")


def _normalize(text: str) -> str:
    return _PUNCT_WS.sub("", str(text or "")).strip()


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ba, bb = _bigrams(na), _bigrams(nb)
    if not ba or not bb:
        return 0.0
    inter = len(ba & bb)
    union = len(ba | bb)
    return inter / union if union else 0.0


def is_duplicate_act(
    content: str,
    recent_history: Sequence[Mapping[str, Any]],
    *,
    lookback: int = _DEFAULT_LOOKBACK,
    threshold: float = _DEFAULT_THRESHOLD,
) -> bool:
    """新动作 content 是否与最近若干条 history 近乎复述。

    空 content 或空历史直接判否;仅比对 history 项的 `content` 文本。
    """
    candidate = _normalize(content)
    if not candidate:
        return False
    recent = list(recent_history)[-lookback:] if lookback > 0 else list(recent_history)
    for item in recent:
        prior = item.get("content", "") if isinstance(item, Mapping) else ""
        if _similarity(content, prior) >= threshold:
            return True
    return False


DEDUP_CORRECTION = (
    "Your previous draft merely restated an action already present in recent_history. "
    "Discard that repetition. Produce a DIFFERENT, concrete next turn that advances the "
    "scene: commit to a pending decision and show its consequence, move to a new place, "
    "trigger an event, or engage another on-stage character. Do not re-narrate prior beats."
)
