"""Senses for a while, and the Dark sphere's Meld choice (docket 2026-09-28; combat/senses.py does the seeing).

  - An ability that gives a sense for its duration (Thousand-Eyed Revelation's Truesight 120 feet and Blindsight 60 feet,
    Sound-Sovereign Incarnation's Blindsight, Dragon-Vein Mantle's Tremorsense; combat/rules/senses.json grants "active"):
    once it is used, a Sense condition holds each sense until the duration ends (at the start of its user's turn) or,
    for a Concentration ability, while that Concentration lasts.
  - Effect ``gain_sense`` for a typed ability that is all sense (Sight Beyond Sight: Tremorsense, or Blindsight when it
    expends Martial Focus; authority/typed_mechanics/reviewed_final.d/docket.json).
  - "Meld: <talent>" (an Action; "Duration: Concentration, up to 1 hour" unless Persistent Meld's 2 CP are paid too):
    one more Meld its user benefits from (effect ``meld_set``; several at once since the owner struck
    the one-Meld sentence on 2026-09-29). Offered to the player only; Melds cast before a fight are combat/prefight.py's.
  - Step Through Darkness is a Meld: offered only while it is active.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .. import concentration


def _grant(ctx: Any, sense: str, feet: int, *, duration: dict[str, Any], against: list[str] | None = None) -> None:
    from .. import senses
    from .effect_durations import until_round

    if feet <= 0:
        return
    engine, actor = ctx.engine, ctx.actor
    for iid, condition in list(actor.conditions.items()):  # using it again renews it
        if condition.condition_id == senses.SENSE and (condition.data or {}).get("source") == ctx.source and (condition.data or {}).get("sense") == sense:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    concentration = bool(duration.get("concentration"))
    until = None if concentration else until_round(engine, duration)
    label = f"{sense.replace('_', ' ').title()} {feet} ft"
    engine._apply_condition(actor, senses.SENSE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"sense": sense, "range_ft": feet, "source": ctx.source, "label": label, "concentration": concentration,
                                  **({"until_round": until} if until is not None else {}),
                                  **({"against_conditions": list(against)} if against else {})})


@hook("technique_used")
def sense_while_active(ctx: Any) -> None:
    """An ability whose text gives a sense for its duration (combat/rules/senses.json grants with when "active")."""
    from .. import senses

    typed = ctx.typed or {}
    record = str(typed.get("option_of") or typed.get("source") or "")
    grant = (senses.rules().get("grants") or {}).get(record)
    if not grant or grant.get("when") != "active" or not ctx.actor.active:
        return
    duration = dict(grant.get("duration") or typed.get("duration") or {})
    cl = int((ctx.numbers or {}).get("cl") or 1)
    for row in grant.get("senses") or []:
        _grant(ctx, str(row["sense"]), senses._range(row, cl), duration=duration, against=row.get("against_conditions"))


@effect("gain_sense")
def gain_sense(ctx: Any, eff: dict[str, Any]) -> None:
    """{"sense", "range_ft" | "range_by_cl", "expend": "martial_focus"?} for the ability's duration."""
    from .. import senses

    if eff.get("expend") == "martial_focus":
        if ctx.actor.resources.get(senses.MARTIAL_FOCUS, 0) < 1:
            ctx.rider("No Martial Focus to expend.")
            return
        ctx.engine._spend_resource(ctx.actor, senses.MARTIAL_FOCUS, 1, ctx.source)
    feet = senses._range(eff, int((ctx.numbers or {}).get("cl") or 1))
    _grant(ctx, str(eff.get("sense") or ""), feet, duration=dict((ctx.typed or {}).get("duration") or {}))


@hook("nominal_slot_boundary")
def nominal_senses_end(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        senses_end(engine, actor)


@hook("turn_start")
def senses_end(engine: Any, actor: Any) -> None:
    """A sense held for a while ends when its time is up (checked at the start of its holder's turn) or with the
    Concentration that held it."""
    from .. import senses

    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id != senses.SENSE:
            continue
        data = condition.data or {}
        over = data.get("until_round") is not None and engine.state.round_number >= int(data["until_round"])
        dropped = data.get("concentration") and not concentration.concentrating_on(actor, data.get("source"))  # current or held
        if over or dropped:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", str(data.get("source") or "senses"), actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "ended"})


# ------------------------------------------------------------------------------------------------ the Meld
MELD_RECORD, PERSISTENT = "TAL_DARK_MELD", "TAL_DARK_PERSISTENT_MELD"


@hook("status_description")
def sense_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Describe only this plug-in's stored senses/Melds; printed talent text is supplied by the shared builder."""
    from .. import senses

    if row.get("condition_id") == senses.MELD and data.get("talent") in (senses.rules().get("melds") or {}).get("talents", []):
        return {"handling": "The table applies this Meld's implemented sight, immunity, Hide or attack effects; other printed permissions are GM rulings."}
    if row.get("condition_id") == senses.SENSE and data.get("sense") and data.get("range_ft"):
        return {"text": f"{str(data['sense']).replace('_', ' ').title()} out to {data['range_ft']} feet.",
                "handling": "The table uses this sense when checking visibility and targeting."}
    return None


@hook("compile_actions")
def meld_actions(info: dict[str, Any]) -> list[Any] | None:
    from .. import senses

    owned = info["owned_ids"]
    melds = [talent for talent in (senses.rules().get("melds") or {}).get("talents") or [] if talent in owned]
    if len(melds) < 2 or MELD_RECORD not in owned:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out = []
    for talent in melds:
        name = str((info["mechanics"].get(talent) or {}).get("name") or talent)
        for persistent in ([False, True] if PERSISTENT in owned else [False]):
            cost = 2 if persistent else 0
            duration = {"kind": "hours", "amount": 1, "concentration": not persistent}
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.meld.{talent.lower()}{'.persistent' if persistent else ''}",
                display_name=f"Meld: {name}{' (Persistent)' if persistent else ''}", owner_id=info["actor_id"],
                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", costs=((pool, cost),) if cost else (),
                parameters={"typed": {"effects": [{"type": "meld_set", "talent": talent, "name": name, "concentration": not persistent,
                                                   "evidence": "Grant the target one Meld talent you know (Action"
                                                               + ("; Persistent Meld: 2 CP, no Concentration" if persistent else "") + ")."}],
                                      "numbers": info["numbers"], "duration": duration, "riders": [], "source": MELD_RECORD},
                            "expected_damage": 0, "player_only": True, "meld_talent": talent}))
    return out


@effect("meld_set")
def meld_set(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import senses

    engine, actor = ctx.engine, ctx.actor
    for iid, condition in list(actor.conditions.items()):
        # The same Meld again replaces it; others stay (owner 2026-09-29: several Melds at once).
        if condition.condition_id == senses.MELD and (condition.data or {}).get("talent") == eff.get("talent"):
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "REPLACED"})
    engine._apply_condition(actor, senses.MELD, ctx.source, actor.entity_id,
                            expires_on="CONCENTRATION_END" if eff.get("concentration") else "UNTIL_REMOVED",
                            data={"talent": eff.get("talent"), "concentration": bool(eff.get("concentration")), "source": ctx.source,
                                  "label": f"Meld: {eff.get('name')}{' (Concentration)' if eff.get('concentration') else ''}"})


@hook("event", nested=True)
def end_legacy_meld_marker(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Older saves used UNTIL_REMOVED for concentration Melds; remove their marker
    when its actual concentration ends. Held copies of the source stay intact.
    New Melds use native CONCENTRATION_END cleanup before this event is emitted.
    """
    if event_type != "CONCENTRATION_ENDED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    source = kwargs.get("source_definition_id")
    if actor is None or concentration.concentrating_on(actor, source):
        return
    from .. import senses

    for iid, condition in list(actor.conditions.items()):
        data = condition.data or {}
        if condition.condition_id == senses.MELD and data.get("concentration") and data.get("source") == source:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": senses.MELD, "instance_id": iid, "reason": "CONCENTRATION_ENDED"})


@hook("candidate_allowed")
def meld_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    parameters = action.parameters or {}
    from .. import senses

    talent = parameters.get("meld_talent")
    if talent:
        # Not a Meld it already benefits from (a Persistent one may still replace a Concentration one).
        chosen = next((row for row in actor.conditions.values() if row.condition_id == senses.MELD and (row.data or {}).get("talent") == talent), None)
        persistent = str(action.source_definition_id).endswith(".persistent")
        if talent in senses.melds_of(engine, actor) and not (persistent and chosen is not None and (chosen.data or {}).get("concentration")):
            return False
        return None
    typed = parameters.get("typed") or {}
    if str(typed.get("option_of") or typed.get("source") or "") == "TAL_DARK_STEP_THROUGH_DARKNESS" and \
            not senses.meld_active(engine, actor, "TAL_DARK_STEP_THROUGH_DARKNESS"):
        return False
    for row in typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "gain_sense" and row.get("expend") == "martial_focus" and \
                actor.resources.get(senses.MARTIAL_FOCUS, 0) < 1:
            return False  # Sight Beyond Sight's Blindsight: "You may expend Martial Focus"
    return None
