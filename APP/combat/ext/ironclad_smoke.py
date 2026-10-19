"""Smoke sphere mechanisms (owner 2026-09-28, auto-ironclad worker: the Smoke sphere is owned by this worker for
every fielded character -- see the coordinator's ownership message; Shi Xunyun also has Ashen Blindfold/Dense
Veil, which just target the Smoke Veil/Blind the Line actions and need no separate work here).

The authority never split "Smoke Responses" into three mechanic ids even though the printed text gives Blind the
Line, Follow the Soot and Slip the Chimney Path three different Action Types (Reaction, Bonus Action, Bonus
Action). authority/typed_mechanics/reviewed_final.d/ironclad.json narrows the shared SMOKE_BASE_SMOKE_RESPONSES
mechanic down to Blind the Line (the one true Reaction, so it compiles as one through the normal pipeline); this
module builds the other two directly as their own actions.

It also builds Smoke Trace's own placement as a manual, no-economy action: the printed trigger is "once per
round, when one of seven very different things happens inside your Smoke Veil or along a sightline through it"
(a creature moves 5 feet, makes an attack roll, spends CP, breathes/speaks, Fire damage is dealt, an object is
carried through the smoke, or a creature Hides/turns Invisible). This engine has no generic per-event trigger
matcher broad enough to cover all seven safely within this task's scope, so placing a trace is offered as a
free (EconomyKind.NONE) player action instead of firing automatically off those events -- an honest
simplification, not a silent invention, and noted on the action's own rider.
"""

from __future__ import annotations

from typing import Any

from . import hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import mark_condition_id

SMOKE_TRACE_ID = "SMOKE_BASE_SMOKE_TRACE"
SMOKE_RESPONSES_ID = "SMOKE_BASE_SMOKE_RESPONSES"
SMOKE_STEP_ID = "TAL_SMOKE_SMOKE_STEP"
BLACK_CHIMNEY_ROUTE_ID = "TAL_SMOKE_BLACK_CHIMNEY_ROUTE"
TRACE_ONCE_MARK = "Smoke Trace Placed This Round"


@hook("button_description")
def trace_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "mark" and eff.get("mark") == TRACE_ONCE_MARK for eff in effects):
        return ("No action, once per round: manually place smoke residue on a creature within 60 feet, lasting until the end of your next turn. "
                "Smoke Responses can use this residue. The table does not detect all printed triggers or enforce the active trace limit; place traces only when the rules below allow.\n\n"
                + printed_rule_text(SMOKE_TRACE_ID))
    return None


@hook("status_description")
def trace_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    cid = str(row.get("condition_id") or "")
    if not cid.startswith("condition:typed.mark.smoke_trace"):
        return None
    from ..status_text import printed_excerpt

    tracker = cid.startswith("condition:typed.mark.smoke_trace_placed_this_round.")
    return {"text": ("Smoke Trace was already placed this round; another placement is unavailable until this tracker expires. " if tracker else "")
                    + printed_excerpt(SMOKE_TRACE_ID), "source_ability": "Smoke Trace",
            "handling": "The table tracks the mark and prevents repeated placement. GM line: placement uses the printed environmental trigger; the table offers a free placement action and does not enforce the printed trace limit."}


@hook("compile_actions")
def _compile_actions(info: dict[str, Any]) -> list[ActionDefinition]:
    owned_ids = set(info["owned_ids"])
    if SMOKE_TRACE_ID not in owned_ids and SMOKE_RESPONSES_ID not in owned_ids:
        return []
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    made: list[ActionDefinition] = []

    if SMOKE_TRACE_ID in owned_ids:
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.smoke.place_trace", display_name="Place Smoke Trace",
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            parameters={"typed": {
                "effects": [
                    {"type": "mark", "mark": "Smoke Trace", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}},
                    # "Once per round" (owner 2026-09-28): a self-mark that clears at the start of the actor's next
                    # turn, checked via requires_absent_condition below -- also what keeps a NONE-economy (free)
                    # action from being an infinite loop for the AI, which would otherwise re-pick a costless,
                    # always-technically-legal action forever.
                    {"type": "mark", "mark": TRACE_ONCE_MARK, "applies_to": "self", "duration": {"kind": "until_start_of_next_turn"}},
                ],
                "numbers": numbers, "duration": {"kind": "instant"}, "riders": [
                    "Simplified from the printed once-per-round environmental triggers (5+ feet of movement, an "
                    "attack roll, the Magic action/CP/a spell slot/an explicit technique, breathing/speaking/a "
                    "breath weapon, Fire damage, an object burning/breaking/opening/closing/carried through the "
                    "smoke, or a successful Hide/turning Invisible) to a manual, no-action placement, since no "
                    "generic event-trigger coverage exists here for all seven. Range approximates \"inside your "
                    "Smoke Veil or through a line of sight that passes through it\"; the Proficiency-Bonus active "
                    "cap is not separately enforced.",
                ],
            }, "expected_damage": 0, "requires_absent_condition": mark_condition_id(TRACE_ONCE_MARK, actor_id)},
        ))

    if SMOKE_RESPONSES_ID in owned_ids:
        distance = 10
        if BLACK_CHIMNEY_ROUTE_ID in owned_ids:
            distance = 30  # inside the Smoke Domain; approximated as always active once owned (CL10+ prerequisite chain)
        elif SMOKE_STEP_ID in owned_ids:
            distance = 20 if int(numbers.get("cl") or 1) >= 5 else 15
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.smoke.slip_chimney", display_name="Slip the Chimney Path",
            owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {
                "effects": [
                    {"type": "spend_mark", "mark": "Smoke Trace", "applies_to": "self", "evidence": "Spend the Smoke Trace."},
                    {"type": "movement", "applies_to": "self", "distance_ft": distance, "duration": "instant",
                     "evidence": f"Move up to {distance} feet without provoking Opportunity Attacks from creatures inside your Smoke Veil."},
                    {"type": "reaction_denied", "applies_to": "self", "duration": "instant",
                     "evidence": "without provoking Opportunity Attacks (approximated as no Opportunity Attacks at all for this move, not only from creatures inside the veil)"},
                ],
                "numbers": numbers, "duration": {"kind": "instant"},
                "riders": ["This movement must begin or end in your Smoke Veil (not enforced -- GM adjudicates legality).",
                           f"Smoke Step/Black Chimney Route distance ({distance} ft) is baked in at compile time from owned talents, "
                           "since those talents' own modifiers cannot target an action this plug-in builds after the modifier pass runs."],
            }, "expected_damage": 0},
        ))
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.smoke.follow_soot", display_name="Follow the Soot",
            owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
            parameters={"typed": {
                "effects": [
                    {"type": "spend_mark", "mark": "Smoke Trace", "applies_to": "target", "evidence": "Spend the Smoke Trace."},
                    {"type": "rider", "evidence": "Until the start of your next turn, you know the direction to the traced target while it remains within 120 feet (no compass-direction/tracking readout on this table; GM adjudicates)."},
                ],
                "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
            }, "expected_damage": 0},
        ))
    return made


@hook('compile_action')
def response_allowance(action: Any, info: dict[str, Any]) -> Any:
    """Newly sealed bonus-action Responses share the reaction allowance."""
    import copy
    typed = action.parameters.get('typed') or {}
    source = str(action.source_definition_id)
    if not (source.endswith('.smoke.slip_chimney') or source.endswith('.smoke.follow_soot')):
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters['typed']['effects'].insert(0, {'type': 'response_use', 'group': 'smoke', 'name': 'Smoke Response'})
    return action.model_copy(update={'parameters': parameters})
