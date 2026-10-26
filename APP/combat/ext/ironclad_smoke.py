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

from . import effect, hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..hook_queries import actor_action

SMOKE_TRACE_ID = "SMOKE_BASE_SMOKE_TRACE"
SMOKE_RESPONSES_ID = "SMOKE_BASE_SMOKE_RESPONSES"
SMOKE_STEP_ID = "TAL_SMOKE_SMOKE_STEP"
BLACK_CHIMNEY_ROUTE_ID = "TAL_SMOKE_BLACK_CHIMNEY_ROUTE"
SOOT_SCENT_TRAIL_ID = "TAL_SMOKE_SOOT_SCENT_TRAIL"
TRACE_CONDITION = "condition:typed.soot_scent_trace"
TRACE_ROUNDS = 10
TRACE_RANGE_FT = 120
# The placement clock's own evented condition: the round in which the owner placed a
# Smoke Trace. "Once per round" is tracked against the actual round identity (the way
# combat/ext/response_limits.py stores the shared Smoke Response allowance), so the limit
# is independent of the trace's own lifetime and of the Response allowance, and survives
# the owner's and other creatures' turns within the round.
ROUND_USE_CONDITION = "condition:typed.smoke_trace_round"


@hook("button_description")
def trace_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "smoke_trace_round_use" for eff in effects):
        return ("No action, once per round: manually place smoke residue on a creature within 60 feet, lasting until the end of your next turn. "
                "Smoke Responses can use this residue. At your Proficiency Bonus limit, choose an existing trace to end. The table does not detect all printed triggers; place traces only when the rules below allow.\n\n"
                + printed_rule_text(SMOKE_TRACE_ID))
    return None


@hook("status_description")
def trace_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    cid = str(row.get("condition_id") or "")
    if not (cid.startswith("condition:typed.mark.smoke_trace") or cid == ROUND_USE_CONDITION):
        return None
    from ..status_text import printed_excerpt

    tracker = cid == ROUND_USE_CONDITION
    return {"text": ("A Smoke Trace was already placed this round; another placement waits until the next round begins. " if tracker else "")
                    + printed_excerpt(SMOKE_TRACE_ID), "source_ability": "Smoke Trace",
            "handling": "The table records the round a Smoke Trace was placed and prevents a second placement until the next round begins. At your Proficiency Bonus limit, you choose an existing trace to end. GM line: placement uses the printed environmental trigger; the table offers a free placement action."}


def smoke_trace_mark_effect() -> dict[str, Any]:
    """Canonical placement row shared by normal Smoke Trace and Mirror Trail.

    Placement uses the typed mark executor, including duration/cap/application
    hooks. The once-per-round expenditure is a separate normal-action effect.
    Mirror's triggered placement does not depend on publication of that action.
    """
    return {"type": "mark", "mark": "Smoke Trace", "applies_to": "target", "cap_replacement": "owner",
            "duration": {"kind": "until_end_of_your_next_turn"}}


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
                    smoke_trace_mark_effect(),
                    # "Once per round" (MGR-T14 Ling): the placement clock is the current round number,
                    # recorded on the owner as evented, saved, owned state (the smoke_trace_round_use effect
                    # below) and admitted by the pure candidate_allowed query (trace_candidate). Round numbers,
                    # not a turn expiry, keep the limit -- so a placement made before the owner's turn still
                    # counts as this round's when that turn begins. This is also what keeps a NONE-economy
                    # (free) action from being an infinite loop for the AI, which would otherwise re-pick a
                    # costless, always-technically-legal action forever. The clock is independent of the
                    # Smoke Trace's own lifetime above (until the end of the owner's next turn) and of the
                    # shared Smoke Response allowance.
                    {"type": "smoke_trace_round_use", "applies_to": "self",
                     "evidence": "Record that the owner placed a Smoke Trace this round."},
                ],
                "numbers": numbers, "duration": {"kind": "instant"}, "riders": [
                    "Simplified from the printed once-per-round environmental triggers (5+ feet of movement, an "
                    "attack roll, the Magic action/CP/a spell slot/an explicit technique, breathing/speaking/a "
                    "breath weapon, Fire damage, an object burning/breaking/opening/closing/carried through the "
                    "smoke, or a successful Hide/turning Invisible) to a manual, no-action placement, since no "
                    "generic event-trigger coverage exists here for all seven. Range approximates \"inside your "
                    "Smoke Veil or through a line of sight that passes through it\". At the Proficiency-Bonus active "
                    "cap, choose an existing trace to end.",
                ],
            }, "expected_damage": 0},
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
                    {"type": "smoke_follow_soot", "extended": int("TAL_SMOKE_SOOT_SCENT_TRAIL" in owned_ids)},
                ],
                "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                "source": SMOKE_RESPONSES_ID,
            }, "expected_damage": 0},
        ))
    return made


@effect("soot_scent_trace")
def soot_scent_trace(ctx: Any, eff: dict[str, Any]) -> None:
    """Shared with smoke_tracking: the sole extended Follow the Soot result.

    The compiled smoke_follow_soot effect delegates here when Soot-Scent Trail
    is owned; this module alone owns its duration and optional escape.
    """
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    from .effect_durations import token
    from .condition_ownership import remove_instance

    # Match the ordinary result's refresh semantics, scoped to this target.
    # Other tracked creatures keep their own lifetime and escape choice.
    for iid, held in list(actor.conditions.items()):
        if (held.condition_id == TRACE_CONDITION and held.source_actor_id == actor.entity_id
                and held.data.get("target_id") == target.entity_id):
            remove_instance(engine, actor, iid, ctx.source)

    engine._apply_condition(actor, TRACE_CONDITION, ctx.source, actor.entity_id,
                            expires_on=token("start", actor.entity_id, actor.turns_started + TRACE_ROUNDS),
                            data={"target_id": target.entity_id, "range_ft": TRACE_RANGE_FT,
                                  "label": (f"Soot-Scent Trail: you know the direction to {target.display_name} "
                                            "within 120 feet for 1 minute. It may attempt a Dexterity "
                                            "(Stealth) check at the end of each turn to end this trace.")})


@hook("turn_end")
def soot_scent_escape(engine: Any, actor: Any) -> None:
    """The traced creature may escape with its ordinary Dexterity (Stealth) check."""
    from .. import ability_checks, save_dcs
    from ..typed_executor import check_modes
    from . import floored
    from .needle import ask, checkpoint_id

    if not actor.active:
        return
    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != TRACE_CONDITION or (condition.data or {}).get("target_id") != actor.entity_id:
                continue
            chosen = ask(engine, getattr(engine, "_active_intent", None),
                         checkpoint_id(engine, "soot_scent_escape", holder.entity_id, actor.entity_id),
                         actor, "choice:needle.soot_scent_escape", ["escape"],
                         automatic=True, allow_decline=True, target_id=actor.entity_id,
                         name="Soot-Scent Trail", feature_id=SOOT_SCENT_TRAIL_ID,
                         labels={"escape": f"Attempt Dexterity (Stealth) against {holder.display_name}'s Smoke Save DC"},
                         prompt=(f"Soot-Scent Trail: {holder.display_name} is following {actor.display_name}'s "
                                 "soot trail. At the end of this turn, attempt a Dexterity (Stealth) check "
                                 "against its Smoke Save DC to end the trace, for no action or resource cost?"))
            if not chosen:
                continue
            dc = int(save_dcs.save_dc(engine, holder))
            bonus = ability_checks.skill_bonus(engine, actor, "Stealth", ability_checks.ability_modifier(actor, "DEX"))
            # Escaping a scent trail is neither a visual Hide nor an auditory
            # concealment check; general DEX/Stealth/all-check rules still apply.
            modes = check_modes(actor, "DEX", "Stealth", engine=engine)
            roll = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id,
                                     reason="CHECK:soot_scent:Stealth",
                                     mode=next(iter(modes)) if len(modes) == 1 else "NORMAL")
            engine._record_roll(roll)
            roll = floored(engine, actor, roll, dc, ability="DEX", skill="Stealth")
            success = roll.total >= dc
            engine._append_event("CHECK_ROLLED", f"passive:{SOOT_SCENT_TRAIL_ID}",
                                 actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"dc": dc, "success": success, "check": "Stealth",
                                          "actor": roll.model_dump(mode="json"), "against": holder.entity_id})
            if success:
                engine._remove_condition_instance(holder, iid, f"passive:{SOOT_SCENT_TRAIL_ID}", expected=condition)


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


def _placement_used_this_round(engine: Any, actor: Any) -> bool:
    """Whether the owner already placed a Smoke Trace in the current round.

    The round identity -- not a turn expiry and not the Response allowance --
    keeps the printed once-per-round limit, so it holds across the owner's and
    other creatures' turns within the round."""
    return any(condition.condition_id == ROUND_USE_CONDITION
               and (condition.data or {}).get("round") == engine.state.round_number
               for condition in actor.conditions.values())


@hook("candidate_allowed", query_key=actor_action)
def trace_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The pure admission query: a second placement is not offered until the next round.

    Reads only the owner's saved round clock and the current round number. It never
    consumes the placement, so menu previews, AI estimates and declined choices all
    leave the once-per-round use unspent."""
    if not str(getattr(action, "source_definition_id", "") or "").endswith(".smoke.place_trace"):
        return None
    return False if _placement_used_this_round(engine, actor) else None


@effect("smoke_trace_round_use")
def trace_round_use(ctx: Any, row: dict[str, Any]) -> None:
    """Commit one accepted placement: the round identity becomes evented, saved, owned state.

    Runs only when a placement actually resolves -- never on a menu preview, an AI
    estimate or a declined choice -- so a cancelled placement spends nothing."""
    engine, actor = ctx.engine, ctx.actor
    if _placement_used_this_round(engine, actor):
        return
    from .condition_ownership import remove_instance

    for instance_id, condition in list(actor.conditions.items()):
        if condition.condition_id == ROUND_USE_CONDITION:
            remove_instance(engine, actor, instance_id, ctx.source)
    engine._apply_condition(actor, ROUND_USE_CONDITION, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"round": engine.state.round_number,
                                  "label": "Smoke Trace: already placed this round"})


@hook("state_event")
def retire_old_round(engine: Any, event: Any) -> None:
    """Retire the placement clock when the next actual round begins.

    A fresh round is a fresh once-per-round -- before the owner's own turn,
    independently of the trace's printed lifetime through that turn."""
    if event.event_type != "ROUND_STARTED":
        return
    from .condition_ownership import remove_instance

    for actor in engine.state.actors.values():
        for instance_id, condition in list(actor.conditions.items()):
            if condition.condition_id == ROUND_USE_CONDITION and (condition.data or {}).get("round") != engine.state.round_number:
                remove_instance(engine, actor, instance_id, "system:smoke_trace.round.expiry")
