from __future__ import annotations

from typing import TYPE_CHECKING, Any

from BaseAgent import BaseAgent
from CharacterRosterTools import CharacterRosterToolRuntime
from Director.DirectorBrief import DirectorBrief
from Director.DirectorFormatter import DirectorFormatter
from Director.DirectorRuntime import normalize_director_brief
from Director.DirectorSchema import DIRECTOR_RESPONSE_SCHEMA
from GameState import GameState

if TYPE_CHECKING:
    from ComponentFactory import ComponentFactory


DIRECTOR_SYSTEM_PROMPT = """
You are the Director Agent in a multi-character dialogue game.
Advance the current beat by deciding stage focus and pressure, not by writing dialogue.

Responsibilities:
1. Pick the current beat and beat goal.
2. Pick the focus character and target tension.
3. Decide whether interrupts are allowed.
4. Return who should respond next and any stage actions.
5. Decide whether a new environment should stay player-only or bring in an available ActorAgent.
6. Provide optional short narrative glue text:
   - `lead_in_text`: 1-2 sentences before the next core event, used for time-passing, atmosphere, or tension build-up.
   - `wrap_up_text`: 1-2 sentences after the current event stretch, used for aftermath, gaze shifts, or a natural handoff back to the player.
   - If the payload marks the beat as conflict-heavy, both fields become mandatory and must expand to 2-3 sentences each.

Constraints:
- Do not write character dialogue.
- `who_should_respond` lists the characters who react to the latest turn.
  The player has just acted, so it should normally name the on-stage NPCs who
  would naturally answer — do not queue the player alone to respond to their own
  action. Include the player only when the beat scripts them as a mid-sequence
  participant or when they are the sole character on stage.
- `response_groups` partitions `who_should_respond` into ordered sub-lists that control turn parallelism.
  Characters in the SAME sub-list react independently to the player's latest action and act at the same
  time; characters in DIFFERENT sub-lists act one sub-list after another, so a later sub-list can see what
  earlier ones said. Default to merging characters who are NOT answering each other into a single sub-list
  (they each react to the player, not to one another) so the turn resolves faster. Only split into separate
  sub-lists when one character must speak before another can react to them (a genuine causal chain), or when
  a focus character interrupts. Every id in `who_should_respond` must appear exactly once across the groups.
- Respect `scene_plan.must_happen` and `scene_plan.must_not_happen`.
- Treat role tiers differently:
  - L1 roles are major dramatic carriers. Prefer them when the beat needs conflict escalation, revelation, hard choices, or relationship turning points.
- NPC appearance after an environment change is optional, not automatic.
- If no extra role is needed, keep `stage_actions.enter` empty and let the scene remain as-is.
- `stage_actions.enter` may only use actor ids listed in `available_stage_candidates`.
- `stage_actions` may only use `enter`, `leave`, `suppress`, and `unsuppress`.
- When `loaded_tool_skills` is provided, inspect those skill modules first and follow their tool definitions instead of inventing your own.
- `lead_in_text` and `wrap_up_text` must not repeat the same sentence, and should not restate the exact action line verbatim.
- When conflict pressure is active, `lead_in_text` must focus on atmosphere and body language before the clash,
  while `wrap_up_text` must focus on emotional residue and scene afterglow after the clash.
- Do not let `wrap_up_text` end with system instructions such as asking the player to choose an action.
- Leave `lead_in_text` or `wrap_up_text` empty if no transition prose is needed.
- If you consider adding, upgrading, or reusing extra roles, inspect `character_roster_snapshot` first.
- Do not implicitly create a new L1 function when the roster snapshot shows that the layer is already at capacity.
- Return strict JSON only.
"""


class DirectorAgent(BaseAgent):
    def __init__(
        self,
        formatter: DirectorFormatter | None = None,
        component_factory: "ComponentFactory" | None = None,
        **kwargs: Any,
    ) -> None:
        character_roster_tool_runtime = kwargs.pop("character_roster_tool_runtime", None)
        super().__init__(
            system_prompt=DIRECTOR_SYSTEM_PROMPT,
            temperature=kwargs.pop("temperature", 0.4),
            max_tokens=kwargs.pop("max_tokens", 1000),
            **kwargs,
        )
        if component_factory is None:
            from ComponentFactory import ComponentFactory

            component_factory = ComponentFactory()
        self.component_factory = component_factory
        self.formatter = formatter or self.component_factory.build_director_formatter()
        self.character_roster_tool_runtime: CharacterRosterToolRuntime | None = character_roster_tool_runtime

    def bind_character_roster_tool_runtime(
        self,
        tool_runtime: CharacterRosterToolRuntime | None,
    ) -> None:
        self.character_roster_tool_runtime = tool_runtime

    def update_stage(
        self,
        state: GameState,
        character_profiles: dict[str, dict[str, Any]],
    ) -> DirectorBrief:
        instruction = self.formatter.build_instruction(
            state=state,
            character_profiles=character_profiles,
            character_roster_tool_runtime=self.character_roster_tool_runtime,
        )
        result = self.command(
            instruction=instruction,
            response_format=DIRECTOR_RESPONSE_SCHEMA,
        )
        allowed_actor_ids: list[str] = []
        for collection in (character_profiles.keys(), state["characters"].keys()):
            for character_id in collection:
                resolved_id = str(character_id).strip()
                if resolved_id and resolved_id not in allowed_actor_ids:
                    allowed_actor_ids.append(resolved_id)
        return normalize_director_brief(
            result,
            state["scene"]["on_stage"],
            allowed_actor_ids=allowed_actor_ids,
            character_profiles=character_profiles,
            player_character_id=state["player"].get("controlled_character"),
        )
