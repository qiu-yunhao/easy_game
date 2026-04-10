from __future__ import annotations

from typing import cast

from Narrator.NarratorTypes import NarrationStylePreset


NARRATION_STYLE_GUIDANCE: dict[str, str] = {
    "xianxia_default": (
        "Use restrained xianxia prose with light classical cadence. "
        "Keep the motion grounded, image-rich, and concise."
    ),
    "light_novel": (
        "Use brisk, readable light-novel prose. "
        "Keep emotions legible and motion easy to follow."
    ),
    "epic": (
        "Use solemn, cinematic epic prose. "
        "Keep the scale elevated, but do not invent new facts."
    ),
}


DEFAULT_NARRATION_STYLE_PRESET: NarrationStylePreset = "xianxia_default"


def resolve_narration_style_preset(style_preset: str | None) -> NarrationStylePreset:
    candidate = str(style_preset or "").strip()
    if candidate in NARRATION_STYLE_GUIDANCE:
        return cast(NarrationStylePreset, candidate)
    return DEFAULT_NARRATION_STYLE_PRESET


def resolve_narration_style_guidance(style_preset: str) -> str:
    return NARRATION_STYLE_GUIDANCE[resolve_narration_style_preset(style_preset)]
