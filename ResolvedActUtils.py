from __future__ import annotations

from typing import Any, Mapping

from GameState import ResolvedAct
from StoryStateUtils import clean_str_list, clean_text


VERBAL_ACT_MODES = {"speak", "interrupt"}


def _clean_mapping(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    return {
        str(key).strip(): value
        for key, value in values.items()
        if str(key).strip()
    }


def build_resolved_act_payload(
    *,
    actor: str | None,
    mode: str,
    target: str | None,
    content: Any,
    spoken_text: Any | None = None,
    nonverbal_action: Any | None = None,
    next_intent: Any = "",
    emotion_update: Mapping[str, Any] | None = None,
    relationship_update: Mapping[str, Any] | None = None,
    revealed_facts: list[Any] | None = None,
    triggered_plot_flags: Mapping[str, Any] | None = None,
    should_end_scene: bool = False,
    should_end_chapter: bool = False,
) -> ResolvedAct:
    resolved_mode = clean_text(mode, "speak")
    resolved_content = clean_text(content)
    resolved_spoken_text = clean_text(spoken_text) if spoken_text is not None else ""
    resolved_nonverbal_action = clean_text(nonverbal_action) if nonverbal_action is not None else ""

    if not resolved_spoken_text and not resolved_nonverbal_action and resolved_content:
        if resolved_mode in VERBAL_ACT_MODES:
            resolved_spoken_text = resolved_content
        else:
            resolved_nonverbal_action = resolved_content

    return {
        "actor": actor,
        "mode": resolved_mode,
        "target": target,
        "content": resolved_content,
        "spoken_text": resolved_spoken_text,
        "nonverbal_action": resolved_nonverbal_action,
        "next_intent": clean_text(next_intent),
        "emotion_update": _clean_mapping(emotion_update),
        "relationship_update": _clean_mapping(relationship_update),
        "revealed_facts": clean_str_list(revealed_facts),
        "triggered_plot_flags": {
            str(key).strip(): clean_text(value)
            for key, value in _clean_mapping(triggered_plot_flags).items()
            if clean_text(value)
        },
        "should_end_scene": bool(should_end_scene),
        "should_end_chapter": bool(should_end_chapter),
    }
