from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Literal

from BaseAgent import AgentMessage, BaseAgent
from CharacterProfile import CharacterProfile
from CharacterRosterTools import CharacterRosterToolRuntime
from GameState import GameState, SceneCandidate
from PlayerWriter.PlaywriterSchema import (
    CHAPTER_EXPANSION_RESPONSE_SCHEMA,
    SCENE_CANDIDATES_RESPONSE_SCHEMA,
    STORY_OUTLINE_BRIEF_RESPONSE_SCHEMA,
    STORY_PREMISE_RESPONSE_SCHEMA,
)
from PlayerWriter.PlayerWriterFormatter import PlaywrightFormatter
from PlayerWriter.StoryTemplateGuidance import (
    build_template_query,
    format_beat_guidance,
    format_skeleton_guidance,
)
from SceneConfig import SceneConfig

if TYPE_CHECKING:
    from ComponentFactory import ComponentFactory


logger = logging.getLogger(__name__)


PLAYWRIGHT_SYSTEM_PROMPT = """
You are the Playwright Agent in an open-world xianxia roleplay game.
You may be asked to define the story premise, sketch the brief chapter outline,
expand the current chapter, or produce concrete next-scene candidates.

Constraints:
- Do not write dialogue.
- Do not pick the next speaker directly.
- Return strict JSON only.
- Keep each step scoped to the requested planning layer.
- Keep the story exploration-led: travel, factions, ruins, cultivation growth, and meaningful choice.
- The game's only fixed long-term objective is cultivation and longevity, not a predetermined mystery plot.
- Each chapter corresponds to one major cultivation realm.
- Do not leave required fields blank. Required strings must contain concrete content.
- When `loaded_tool_skills` is provided, inspect those skill modules first and follow their tool definitions instead of inventing your own.
- Before proposing new supporting roles or role upgrades, inspect the provided `character_roster_snapshot`.
- If `character_roster_snapshot` shows that L1 or L2 capacity is full, reuse an existing role or downgrade the function instead of silently over-creating.
"""


class PlaywrightAgent(BaseAgent):
    def __init__(
        self,
        formatter: PlaywrightFormatter | None = None,
        component_factory: "ComponentFactory" | None = None,
        **kwargs: Any,
    ) -> None:
        character_roster_tool_runtime = kwargs.pop("character_roster_tool_runtime", None)
        super().__init__(
            system_prompt=PLAYWRIGHT_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.7),
            max_tokens=kwargs.pop("max_tokens", 1400),
            **kwargs,
        )
        if component_factory is None:
            from ComponentFactory import ComponentFactory

            component_factory = ComponentFactory()
        self.component_factory = component_factory
        self.formatter = formatter or self.component_factory.build_playwright_formatter()
        self.character_roster_tool_runtime: CharacterRosterToolRuntime | None = character_roster_tool_runtime

    def bind_character_roster_tool_runtime(
        self,
        tool_runtime: CharacterRosterToolRuntime | None,
    ) -> None:
        self.character_roster_tool_runtime = tool_runtime

    def _resolve_template_guidance(
        self,
        game_state: GameState,
        history: list[AgentMessage] | None,
        template_service,
        *,
        layer: Literal["chapter", "scene"],
    ) -> str:
        """检索选定情节模板并格式化为软指导；任何缺失/故障静默降级为空串。

        service 缺失或 selected_template_id<=0（含非法值）时跳过；检索抛异常时记日志、
        返回 ""，绝不阻断规划——空串会让 formatter 不加 reference_* 字段，逐字节退化为纯 LLM。
        """
        if template_service is None:
            return ""
        try:
            template_id = int(game_state["plot"].get("selected_template_id", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if template_id <= 0:
            return ""
        query = build_template_query(game_state, history)
        try:
            if layer == "chapter":
                nodes = template_service.next_skeleton_nodes(template_id, chapter_hint=query)
                return format_skeleton_guidance(nodes)
            beats = template_service.suggest_plot_beats(template_id, query=query, top_k=5)
            return format_beat_guidance(beats)
        except Exception:
            logger.exception("story template retrieval failed; degrading to pure LLM planning")
            return ""

    def _execute_with_retry(
        self,
        *,
        instruction: str,
        correction: str,
        history: list[AgentMessage] | None,
        response_format: dict[str, Any],
        normalize: Callable[[dict[str, Any]], Any],
        is_complete: Callable[[Any], bool],
        missing_fields: Callable[[Any], list[str]],
        error_prefix: str,
    ) -> Any:
        last_payload: Any = None
        for attempt in range(2):
            attempt_instruction = instruction
            if attempt == 1:
                attempt_instruction = f"{instruction}\n\nCorrection: {correction}"
            result = self.command(
                instruction=attempt_instruction,
                history=history,
                response_format=response_format,
            )
            normalized = normalize(result)
            last_payload = normalized
            if is_complete(normalized):
                return normalized

        missing = missing_fields(last_payload)
        raise RuntimeError(
            f"{error_prefix} Missing or empty fields: {', '.join(missing) or 'unknown'}."
        )

    def _story_premise_is_complete(self, payload: dict[str, str]) -> bool:
        return bool(
            str(payload.get("story_premise", "") or "").strip()
            and str(payload.get("exploration_drive", "") or "").strip()
        )

    def _missing_story_premise_fields(self, payload: dict[str, str]) -> list[str]:
        missing: list[str] = []
        for field in ("story_premise", "exploration_drive"):
            if not str(payload.get(field, "") or "").strip():
                missing.append(field)
        return missing

    def _story_outline_brief_is_complete(
        self,
        payload: list[dict[str, Any]],
        *,
        desired_count: int,
    ) -> bool:
        if len(payload) < desired_count:
            return False
        first = payload[0]
        return bool(
            str(first.get("chapter_id", "") or "").strip()
            and str(first.get("title", "") or "").strip()
            and str(first.get("main_goal", "") or "").strip()
            and str(first.get("summary", "") or "").strip()
        )

    def _missing_story_outline_brief_fields(
        self,
        payload: list[dict[str, Any]],
        *,
        desired_count: int,
    ) -> list[str]:
        if not payload:
            return ["story_outline"]
        missing: list[str] = []
        if len(payload) < desired_count:
            missing.append(f"story_outline_count<{desired_count}")
        for index, chapter in enumerate(payload[:desired_count]):
            for field in ("chapter_id", "title", "main_goal", "summary"):
                if not str(chapter.get(field, "") or "").strip():
                    missing.append(f"story_outline[{index}].{field}")
        return missing

    def _chapter_expansion_is_complete(self, payload: dict[str, Any]) -> bool:
        return bool(
            str(payload.get("chapter_title", "") or "").strip()
            and str(payload.get("chapter_goal", "") or "").strip()
            and str(payload.get("chapter_overview", "") or "").strip()
            and list(payload.get("exploration_hooks", []))
            and list(payload.get("key_locations", []))
        )

    def _missing_chapter_expansion_fields(self, payload: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for field in ("chapter_title", "chapter_goal", "chapter_overview"):
            if not str(payload.get(field, "") or "").strip():
                missing.append(field)
        if not list(payload.get("exploration_hooks", [])):
            missing.append("exploration_hooks")
        if not list(payload.get("key_locations", [])):
            missing.append("key_locations")
        return missing

    def _scene_candidates_are_complete(self, payload: list[SceneCandidate]) -> bool:
        if not payload:
            return False
        first = payload[0]
        return bool(
            str(first.get("candidate_id", "") or "").strip()
            and str(first.get("location_id", "") or "").strip()
            and str(first.get("beat", "") or "").strip()
            and str(first.get("scene_goal", "") or "").strip()
            and str(first.get("exit_condition", "") or "").strip()
        )

    def _missing_scene_candidate_fields(self, payload: list[SceneCandidate]) -> list[str]:
        if not payload:
            return ["candidates"]
        missing: list[str] = []
        first = payload[0]
        for field in ("candidate_id", "location_id", "beat", "scene_goal", "exit_condition"):
            if not str(first.get(field, "") or "").strip():
                missing.append(f"candidates[0].{field}")
        return missing

    def plan_story_premise(
        self,
        game_state: GameState,
        scene_config: SceneConfig,
        character_profiles: dict[str, CharacterProfile],
        history: list[AgentMessage] | None = None,
    ) -> dict[str, str]:
        instruction = self.formatter.build_story_premise_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
        )
        return self._execute_with_retry(
            instruction=instruction,
            correction=(
                "Return non-empty values for `story_premise` and `exploration_drive`. "
                "Stay concise and keep the scope at the premise layer only."
            ),
            history=history,
            response_format=STORY_PREMISE_RESPONSE_SCHEMA,
            normalize=lambda result: self.formatter.normalize_story_premise(result),
            is_complete=self._story_premise_is_complete,
            missing_fields=self._missing_story_premise_fields,
            error_prefix="PlaywrightAgent returned an incomplete story premise.",
        )

    def plan_story_outline_brief(
        self,
        game_state: GameState,
        scene_config: SceneConfig,
        character_profiles: dict[str, CharacterProfile],
        desired_chapter_count: int = 3,
        history: list[AgentMessage] | None = None,
    ) -> list[dict[str, Any]]:
        instruction = self.formatter.build_story_outline_brief_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            desired_chapter_count=desired_chapter_count,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
        )
        return self._execute_with_retry(
            instruction=instruction,
            correction=(
                f"Return a non-empty `story_outline` with exactly {desired_chapter_count} future chapters. "
                "Each chapter needs `chapter_id`, `title`, `main_goal`, and `summary`. "
                "Do not repeat already planned chapters."
            ),
            history=history,
            response_format=STORY_OUTLINE_BRIEF_RESPONSE_SCHEMA,
            normalize=lambda result: self.formatter.normalize_story_outline_brief(
                result,
                game_state=game_state,
                desired_chapter_count=desired_chapter_count,
                character_profiles=character_profiles,
            ),
            is_complete=lambda payload: self._story_outline_brief_is_complete(
                payload,
                desired_count=desired_chapter_count,
            ),
            missing_fields=lambda payload: self._missing_story_outline_brief_fields(
                payload,
                desired_count=desired_chapter_count,
            ),
            error_prefix="PlaywrightAgent returned an incomplete story outline brief.",
        )

    def expand_current_chapter(
        self,
        game_state: GameState,
        scene_config: SceneConfig,
        character_profiles: dict[str, CharacterProfile],
        history: list[AgentMessage] | None = None,
        template_service=None,
    ) -> dict[str, Any]:
        current_outline = next(
            (
                chapter
                for chapter in game_state["plot"].get("story_outline", [])
                if str(chapter.get("chapter_id", "") or "").strip()
                == str(game_state["plot"].get("chapter_id", "") or "").strip()
            ),
            {},
        )
        template_guidance = self._resolve_template_guidance(
            game_state, history, template_service, layer="chapter"
        )
        instruction = self.formatter.build_chapter_expansion_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            template_guidance=template_guidance,
        )
        return self._execute_with_retry(
            instruction=instruction,
            correction=(
                "Return non-empty values for `chapter_title`, `chapter_goal`, `chapter_overview`, "
                "`exploration_hooks`, and `key_locations`."
            ),
            history=history,
            response_format=CHAPTER_EXPANSION_RESPONSE_SCHEMA,
            normalize=lambda result: self.formatter.normalize_chapter_expansion(
                result,
                default_title=str(current_outline.get("title", "") or "").strip(),
                default_goal=str(current_outline.get("main_goal", "") or "").strip(),
                default_overview=str(current_outline.get("summary", "") or "").strip(),
            ),
            is_complete=self._chapter_expansion_is_complete,
            missing_fields=self._missing_chapter_expansion_fields,
            error_prefix="PlaywrightAgent returned an incomplete chapter expansion.",
        )

    def generate_scene_candidates(
        self,
        game_state: GameState,
        scene_config: SceneConfig,
        character_profiles: dict[str, CharacterProfile],
        history: list[AgentMessage] | None = None,
        template_service=None,
    ) -> list[SceneCandidate]:
        template_guidance = self._resolve_template_guidance(
            game_state, history, template_service, layer="scene"
        )
        instruction = self.formatter.build_scene_candidates_instruction(
            game_state=game_state,
            scene_config=scene_config,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
            template_guidance=template_guidance,
        )
        return self._execute_with_retry(
            instruction=instruction,
            correction=(
                "Return 2 or 3 concrete scene candidates in `candidates`. "
                "Each candidate needs `candidate_id`, `label`, `location_id`, `beat`, `scene_goal`, "
                "`must_happen`, `must_not_happen`, `dramatic_curve`, `character_objectives`, "
                "`exit_condition`, and `notes`."
            ),
            history=history,
            response_format=SCENE_CANDIDATES_RESPONSE_SCHEMA,
            normalize=lambda result: self.formatter.normalize_scene_candidates(
                result,
                on_stage=game_state["scene"]["on_stage"],
                fallback_location=str(game_state["scene"]["location_id"] or "").strip(),
            ),
            is_complete=self._scene_candidates_are_complete,
            missing_fields=self._missing_scene_candidate_fields,
            error_prefix="PlaywrightAgent returned incomplete scene candidates.",
        )
