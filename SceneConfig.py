from typing import NotRequired, TypedDict

class SceneConfig(TypedDict):
    scene_id: str
    default_location_id: str
    default_on_stage: list[str]
    entry_conditions: list[str]
    exit_conditions: list[str]
    narration_style_preset: NotRequired[str]
