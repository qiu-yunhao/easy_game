from __future__ import annotations

from typing import Literal, TypedDict

from CharacterProfile import CharacterProfile, normalize_l2_agent_profile
from StoryStateUtils import clean_text


SupportingSceneFunction = Literal["Help", "Block", "Buffer", "Inform"]


class SupportingSceneIntentDecision(TypedDict):
    should_act: bool
    scene_need_detected: bool
    drive_triggered: bool
    selected_function: SupportingSceneFunction
    rationale: list[str]


def _keyword_hits(text: str, phrases: list[str]) -> bool:
    normalized_text = clean_text(text)
    if not normalized_text:
        return False

    for phrase in phrases:
        normalized_phrase = clean_text(phrase)
        if not normalized_phrase:
            continue
        if normalized_phrase in normalized_text:
            return True
        chunks = [chunk for chunk in normalized_phrase.replace("，", " ").replace("、", " ").split() if len(chunk) >= 2]
        if chunks and any(chunk in normalized_text for chunk in chunks):
            return True
    return False


class SupportingSceneIntentPolicy:
    def decide(
        self,
        *,
        actor_profile: CharacterProfile,
        scene_need_detected: bool,
        player_action_text: str = "",
        scene_goal: str = "",
        beat_goal: str = "",
    ) -> SupportingSceneIntentDecision:
        l2_profile = normalize_l2_agent_profile(
            actor_profile.get("l2_profile", {}),
            fallback_story_role=clean_text(actor_profile.get("story_role", "")),
            fallback_persona=list(actor_profile.get("persona", [])),
            fallback_style=clean_text(actor_profile.get("base_style", "")),
        )
        combined_context = " ".join(
            part
            for part in (
                clean_text(player_action_text),
                clean_text(scene_goal),
                clean_text(beat_goal),
            )
            if clean_text(part)
        )
        drive_triggered = _keyword_hits(combined_context, [l2_profile["core_drive"], *l2_profile["judgement_preference"]])
        selected_function: SupportingSceneFunction = "Inform"
        rationale: list[str] = []

        if _keyword_hits(combined_context, ["阻拦", "盘查", "试探", "挡住", "拒绝"]):
            selected_function = "Block"
            rationale.append("场面信号更接近阻拦或设卡，L2 适合承担 Block 职能。")
        elif _keyword_hits(combined_context, ["安抚", "缓和", "打圆场", "稳住", "别冲动"]):
            selected_function = "Buffer"
            rationale.append("场面更需要缓和张力，L2 适合承担 Buffer 职能。")
        elif _keyword_hits(combined_context, ["告知", "线索", "解释", "消息", "传话", "规矩"]):
            selected_function = "Inform"
            rationale.append("场面更需要补信息，L2 适合承担 Inform 职能。")
        else:
            selected_function = "Help"
            rationale.append("没有明显阻拦或缓冲信号时，L2 默认先承担 Help 职能。")

        if drive_triggered:
            rationale.append("玩家动作或当前局势触发了该 L2 的核心驱动。")
        else:
            rationale.append("当前局势未明显触发核心驱动，优先按场面需求提供轻量支撑。")

        should_act = bool(
            scene_need_detected and (drive_triggered or selected_function in {"Inform", "Buffer", "Block"})
        )
        return {
            "should_act": should_act,
            "scene_need_detected": bool(scene_need_detected),
            "drive_triggered": drive_triggered,
            "selected_function": selected_function,
            "rationale": rationale,
        }
