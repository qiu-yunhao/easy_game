from __future__ import annotations

from typing import Iterable


REALM_ORDER = [
    "炼气",
    "筑基",
    "金丹",
    "元婴",
    "化神",
    "炼虚",
    "合体",
    "大乘",
    "渡劫",
    "飞升",
]

DEFAULT_REALM = REALM_ORDER[0]
BREAKTHROUGH_TOKENS = (
    "突破",
    "破境",
    "晋升",
    "晋阶",
    "踏入",
    "迈入",
    "结成",
    "凝成",
    "成就",
    "证得",
)


def normalize_major_realm(value: str | None, fallback: str = DEFAULT_REALM) -> str:
    text = str(value or "").strip()
    for realm in REALM_ORDER:
        if realm in text:
            return realm
    return fallback


def normalize_realm_text(value: str | None, fallback: str = "炼气一层") -> str:
    text = str(value or "").strip()
    return text or fallback


def realm_index(value: str | None) -> int:
    major_realm = normalize_major_realm(value)
    try:
        return REALM_ORDER.index(major_realm)
    except ValueError:
        return 0


def next_major_realm(value: str | None) -> str:
    current_index = realm_index(value)
    if current_index >= len(REALM_ORDER) - 1:
        return REALM_ORDER[-1]
    return REALM_ORDER[current_index + 1]


def realm_at_offset(start_realm: str | None, offset: int) -> str:
    current_index = realm_index(start_realm)
    target_index = min(len(REALM_ORDER) - 1, max(0, current_index + offset))
    return REALM_ORDER[target_index]


def chapter_realm_sequence(start_realm: str | None, count: int) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    for offset in range(max(0, count)):
        realm_stage = realm_at_offset(start_realm, offset)
        sequence.append((realm_stage, next_major_realm(realm_stage)))
    return sequence


def has_reached_realm(current_realm: str | None, target_realm: str | None) -> bool:
    if not target_realm:
        return False
    return realm_index(current_realm) >= realm_index(target_realm)


def build_chapter_transition_requirement(current_realm: str | None, target_realm: str | None) -> str:
    current_stage = normalize_major_realm(current_realm)
    target_stage = normalize_major_realm(target_realm, fallback=current_stage)
    if current_stage == target_stage:
        return f"将{current_stage}修为打磨圆满，找到继续求道与求长生的下一条路。"
    return f"在本章内完成从{current_stage}迈向{target_stage}的突破准备，并在抵达{target_stage}后收束本章。"


def detect_breakthrough_realm(text: str | None, candidate_realms: Iterable[str]) -> str | None:
    content = str(text or "").strip()
    if not content:
        return None
    if not any(token in content for token in BREAKTHROUGH_TOKENS):
        return None
    for realm in candidate_realms:
        resolved = str(realm or "").strip()
        if resolved and resolved in content:
            return resolved
    return None
