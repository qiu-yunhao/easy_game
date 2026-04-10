from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SceneEndTuning:
    minimum_tension_floor: float = 0.45
    completion_signal_weight: float = 0.45
    no_pending_response_weight: float = 0.15
    tension_reached_weight: float = 0.15
    closing_motion_weight: float = 0.10
    end_threshold: float = 0.65
    confidence_base: float = 0.45
    confidence_signal_scale: float = 0.5
    unresolved_confidence: float = 0.95
    actor_override_confidence: float = 0.90


@dataclass(frozen=True, slots=True)
class RelationshipTuning:
    minimum_delta: float = -1.0
    maximum_delta: float = 1.0
    reciprocity_base_factor: float = 0.60
    reciprocity_target_factor: float = 0.75
    reciprocity_interrupt_bonus: float = 0.10
    reciprocity_silence_factor: float = 0.35
    supportive_delta: float = 0.08
    confrontation_delta: float = -0.10
    interrupt_delta: float = -0.12
    action_delta: float = -0.08
    speak_delta: float = -0.06


@dataclass(frozen=True, slots=True)
class NarrationTuning:
    min_batch_actors: int = 2
    max_batch_actors: int = 3
    style_preset: str = "xianxia_default"


@dataclass(frozen=True, slots=True)
class GameplayTuning:
    scene_end: SceneEndTuning = field(default_factory=SceneEndTuning)
    relationship: RelationshipTuning = field(default_factory=RelationshipTuning)
    narration: NarrationTuning = field(default_factory=NarrationTuning)
