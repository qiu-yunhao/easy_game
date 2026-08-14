"""修炼领域插件。

- ``realms``:纯粹的境界数学(排序、归一化、突破识别、章节过渡要求),
  不依赖任何对话引擎代码,可被 PlayerWriter / SceneEnd / Graph 等自由复用。
- ``progression``:修炼推进的领域节点逻辑(``cultivation_progress_node``
  及其辅助),从对话引擎中抽出。运行期通过惰性导入接触旁白追加器,
  不在顶层依赖 Graph,从而与对话引擎保持解耦。

此处统一 re-export,保证既有 ``from Cultivation import xxx`` 全部兼容。
"""

from __future__ import annotations

from Cultivation.realms import (
    BREAKTHROUGH_TOKENS,
    DEFAULT_REALM,
    REALM_ORDER,
    build_chapter_transition_requirement,
    chapter_realm_sequence,
    detect_breakthrough_realm,
    has_reached_realm,
    next_major_realm,
    normalize_major_realm,
    normalize_realm_text,
    realm_at_offset,
    realm_index,
)
from Cultivation.progression import (
    CULTIVATION_SIGNAL_MARKERS,
    cultivation_progress_node,
    _build_cultivation_result_text,
    _looks_like_cultivation_turn,
    _sync_plot_cultivation_state,
)

__all__ = [
    "BREAKTHROUGH_TOKENS",
    "DEFAULT_REALM",
    "REALM_ORDER",
    "CULTIVATION_SIGNAL_MARKERS",
    "build_chapter_transition_requirement",
    "chapter_realm_sequence",
    "cultivation_progress_node",
    "detect_breakthrough_realm",
    "has_reached_realm",
    "next_major_realm",
    "normalize_major_realm",
    "normalize_realm_text",
    "realm_at_offset",
    "realm_index",
    "_build_cultivation_result_text",
    "_looks_like_cultivation_turn",
    "_sync_plot_cultivation_state",
]
