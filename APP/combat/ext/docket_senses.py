"""Senses for a while, and the Dark sphere's Meld choice (docket 2026-09-28; combat/senses.py does the seeing).

  - An ability that gives a sense for its duration (Thousand-Eyed Revelation's Truesight 120 feet and Blindsight 60 feet,
    Sound-Sovereign Incarnation's Blindsight, Dragon-Vein Mantle's Tremorsense; combat/rules/senses.json grants "active"):
    once it is used, a Sense condition holds each sense until the duration ends (at the start of its user's turn) or,
    for a Concentration ability, while that Concentration lasts.
  - Effect ``gain_sense`` for a typed ability that is all sense (Sight Beyond Sight: Tremorsense, or Blindsight when it
    expends Martial Focus; authority/typed_mechanics/reviewed_final.d/docket.json).
  - "Meld: <talent>" (an Action; "Duration: Concentration, up to 1 hour" unless Persistent Meld's 2 CP are paid too):
    one more Meld its recipient benefits from (effect ``meld_set``; several at once since the owner struck
    the one-Meld sentence on 2026-09-29). Fresh Darkvision/Clearsight/Feed casts touch a willing creature or allow
    an unwilling Wisdom save. Nonself recipients decide acceptance through their own controller, even on an AI caster's turn.
    A new copy replaces the same talent from any caster without stacking; manual renewal is always legal.
    Blindfold uses its printed save. Automatic beneficial casts only target allies/self,
    and Blindfold only enemies. Dark Slaughter/Hide in Darkness retain their caster-only route. Pre-fight Melds
    are combat/prefight.py's. Darkvision may pay another 2 CP for its enhanced range. Recipient state holds the
    caster id, numbers and original duration clock; dark_melds uses it for senses and turn-start Feed grants.
  - Meld actions may declare parameters.meld_upgrades: persistent (bool),
    enhanced_darkvision (bool), temporary_hp (offered integer pool). AI redundancy
    filtering admits an upgrade if it improves any declared benefit; missing keys
    retain legacy suffix detection. Human renewals remain available.
  - Step Through Darkness is a Meld: offered only while it is active.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .. import concentration


def _grant(ctx: Any, sense: str, feet: int, *, duration: dict[str, Any], against: list[str] | None = None,
           requires_condition: str | None = None, requires_condition_data: dict[str, Any] | None = None) -> None:
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
                                  **({"against_conditions": list(against)} if against else {}),
                                  **({"requires_condition": requires_condition} if requires_condition else {}),
                                  **({"requires_condition_data": dict(requires_condition_data)} if requires_condition_data else {})})


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
    """A typed sense for the ability's duration; requires_condition binds it to live owner state."""
    from .. import senses

    if eff.get("expend") == "martial_focus":
        if ctx.actor.resources.get(senses.MARTIAL_FOCUS, 0) < 1:
            ctx.rider("No Martial Focus to expend.")
            return
        ctx.engine._spend_resource(ctx.actor, senses.MARTIAL_FOCUS, 1, ctx.source)
    feet = senses._range(eff, int((ctx.numbers or {}).get("cl") or 1))
    _grant(ctx, str(eff.get("sense") or ""), feet, duration=dict((ctx.typed or {}).get("duration") or {}),
           requires_condition=str(eff["requires_condition"]) if eff.get("requires_condition") else None,
           requires_condition_data=eff.get("requires_condition_data"))


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

    if row.get("condition_id") == senses.MELD and data.get("end_clock") and data.get("talent") in (
            "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT", "TAL_DARK_FEED_ON_DARKNESS"):
        return {"handling": "The table applies this Meld to its recipient for its duration, while its creator concentrates unless made Persistent."}
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
    melds += [talent for talent in ("TAL_DARK_BLINDFOLD", "TAL_DARK_FEED_ON_DARKNESS") if talent in owned]
    if not melds or MELD_RECORD not in owned:
        return None
    import copy
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out = []
    for talent in melds:
        record = info["mechanics"].get(talent) or {}
        name = str(record.get("name") or talent)
        for persistent in ([False, True] if PERSISTENT in owned else [False]):
            for enhanced in ([False, True] if talent == "TAL_DARK_DARKVISION" else [False]):
                cost = (2 if persistent else 0) + (2 if enhanced else 0)
                duration = dict(record.get("duration") or {}) if talent in ("TAL_DARK_BLINDFOLD", "TAL_DARK_FEED_ON_DARKNESS") else {"kind": "hours", "amount": 1}
                duration["concentration"] = not persistent
                effects = copy.deepcopy(record["effects"]) if talent == "TAL_DARK_BLINDFOLD" else [{
                    "type": "meld_set", "talent": talent, "name": name, "concentration": not persistent,
                    "enhanced_darkvision": enhanced, "duration": duration}]
                if talent == "TAL_DARK_BLINDFOLD" and persistent:
                    for save in effects:
                        for row in save.get("on_fail") or []:
                            row["duration"] = "one_minute"
                detail = {
                    "TAL_DARK_BLINDFOLD": "Wisdom save negates. On failure, Blinded and all other senses reach half as far; repeat the save at each turn's end. Sight through supernatural Darkness grants immunity.",
                    "TAL_DARK_FEED_ON_DARKNESS": "At the start of each turn inside the caster's Darkness, gain Temporary HP equal to the caster's key ability modifier. They end one round after leaving the caster's Darkness.",
                    "TAL_DARK_CLEARSIGHT": "Immune to negative effects of the caster's Darkness talents. Clearsight does not grant sight through Darkness by itself; a recipient with Darkvision can see through the caster's Pure Darkness.",
                    "TAL_DARK_DARKVISION": f"Grant Darkvision {120 if enhanced else 60} feet, or add {60 if enhanced else 30} feet to existing Darkvision.",
                }.get(talent, "An unwilling creature can resist with a Wisdom save.")
                unit = str(duration.get("kind") or "hours").rstrip("s")
                lifetime = f"Up to {duration.get('amount')} {unit}{'s' if duration.get('amount') != 1 else ''}" + (" without Concentration." if persistent else "; Concentration.")
                suffix = ('.persistent' if persistent else '') + ('.enhanced' if enhanced else '')
                out.append(ActionDefinition(
                    source_definition_id=f"action:typed.{info['short']}.meld.{talent.lower()}{suffix}",
                    display_name=f"Meld: {name}{' (Persistent)' if persistent else ''}{' (2 CP)' if enhanced else ''}",
                    owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED",
                    target_kind="SELF" if talent in ("TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_HIDE_IN_DARKNESS") else "ANY_CREATURE",
                    range_ft=5, concentration=not persistent,
                    costs=((pool, cost),) if cost else (),
                    parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": duration,
                                          "riders": [], "source": talent if talent == "TAL_DARK_BLINDFOLD" else MELD_RECORD},
                                "expected_damage": 0, "meld_talent": talent, "meld_runtime": 2,
                                "description": f"Touch one creature to grant {name}. Cost: {cost} cultivation points. {lifetime} {detail}" +
                                    (" An unwilling creature can resist with a Wisdom save." if talent in ("TAL_DARK_DARKVISION", "TAL_DARK_FEED_ON_DARKNESS", "TAL_DARK_CLEARSIGHT") else "")}))
    return out


@hook("compiled_rider_utility")
def meld_rider_utility(action: Any) -> int | None:
    """One recipient's live sight/ward or failed-save band, never damage or duration-scaled value."""
    return 8 if (action.parameters or {}).get("meld_runtime") == 2 else None


@effect("meld_set", harmful=False)
def meld_set(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import senses

    engine, actor = ctx.engine, getattr(ctx, "target", None) or ctx.actor
    fresh = (getattr(getattr(ctx, "action", None), "parameters", None) or {}).get("meld_runtime") == 2
    if fresh and actor is not ctx.actor:
        from . import needle
        allied = actor.team_id == ctx.actor.team_id
        accepted = needle.ask(engine, ctx.intent,
            needle.checkpoint_id(engine, "DARK_MELD_CONSENT", ctx.actor.entity_id, actor.entity_id),
            actor, "choice:needle.dark_meld_consent", ["accept"],
            labels={"accept": "Accept the Meld without resisting"}, allow_decline=True,
            preferred=["accept"] if allied else [], automatic=allied,
            default="first" if allied else "decline", target_id=actor.entity_id,
            name=f"Accept {eff.get('name')}?",
            prompt=f"{ctx.actor.display_name} offers {actor.display_name} {eff.get('name')}. "
                   f"{ctx.action.parameters.get('description', '')} "
                   "Accept without a save, or resist with a Wisdom save. This choice costs the recipient no action or cultivation points.")
    else:
        accepted = True
    if not accepted:
        roll = engine._roll_save(actor, "WIS", int(ctx.numbers.get("save_dc") or 10), ctx.source)
        if roll is None or roll.total >= int(ctx.numbers.get("save_dc") or 10):
            return
    from ..typed_executor import clock_expiry
    duration = eff.get("duration") or (getattr(ctx, "typed", None) or {}).get("duration") or {}
    for iid, condition in list(actor.conditions.items()):
        # The same talent replaces its prior grant, even from another caster; different Meld talents stay.
        # This is renewal, not stacking (owner: multiple Melds; ordinary same-effect nonstacking).
        if condition.condition_id == senses.MELD and (condition.data or {}).get("talent") == eff.get("talent"):
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "REPLACED"})
    engine._apply_condition(actor, senses.MELD, ctx.source, ctx.actor.entity_id,
                            expires_on="CONCENTRATION_END" if eff.get("concentration") else "UNTIL_REMOVED",
                            data={"caster_id": ctx.actor.entity_id, "numbers": dict(getattr(ctx, "numbers", None) or {}),
                                  "enhanced_darkvision": bool(eff.get("enhanced_darkvision")),
                                  "end_clock": clock_expiry(engine, duration.get("kind"), duration.get("amount")),
                                  "talent": eff.get("talent"), "concentration": bool(eff.get("concentration")), "source": ctx.source,
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
        if parameters.get("meld_runtime") == 2:
            recipient = engine.state.actors.get(next(iter(candidate.target_ids), actor.entity_id))
            if recipient is None:
                return False
            from .needle import ai_controlled
            if ai_controlled(engine, actor):
                harmful = talent == "TAL_DARK_BLINDFOLD"
                if (recipient.team_id != actor.team_id) != harmful:
                    return False
                if recipient is not actor and not senses.perceives(engine, actor, recipient):
                    return False
            if talent == "TAL_DARK_BLINDFOLD":
                return None
            # Redundancy is an AI preference, never a ban on a player's legal renewal.
            if not ai_controlled(engine, actor):
                return None
            from .effect_durations import due
            chosen = [c for c in recipient.conditions.values() if c.condition_id == senses.MELD
                      and (c.data or {}).get("talent") == talent and c.source_actor_id == actor.entity_id
                      and not due(engine, c.data.get("end_clock"))
                      and (not c.data.get("concentration") or concentration.concentrating_on(actor, c.data.get("source")))]
            upgrades = parameters.get("meld_upgrades") or {}
            enhanced = upgrades.get("enhanced_darkvision", str(action.source_definition_id).endswith(".enhanced"))
            persistent = upgrades.get("persistent", ".persistent" in str(action.source_definition_id))
            # An offered pool is useful even when the same cloak remains after
            # its previous Temporary HP were spent. No ability-id dispatch.
            hp_upgrade = int(upgrades.get("temporary_hp") or 0) > recipient.temporary_hp
            if chosen and all((not enhanced or c.data.get("enhanced_darkvision")) and
                              (not persistent or not c.data.get("concentration")) for c in chosen) and not hp_upgrade:
                return False
            if not chosen and recipient is actor and talent in senses.melds_of(engine, actor) and not enhanced and not hp_upgrade:
                return False
            return None
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
