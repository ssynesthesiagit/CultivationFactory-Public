"""Reflexive Stealth (eye, 2026-09-28): "Trigger: You succeed on a Dexterity saving throw against an effect that
targets an area. Immediately attempt to Hide. For this attempt only, you may take the Hide action even if you do not
currently meet its normal cover or obscurement requirements... If you do not satisfy the normal Hide requirements by
the end of your next turn, the hidden state ends at that time." Uses the existing after_save and turn_end hooks; no
shared-file edit needed.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any
from ..ability_checks import ability_modifier

from . import hook
from .eye_common import has, skill

REFLEXIVE_STEALTH = "TAL_THE_HIDDEN_EYE_REFLEXIVE_STEALTH"
SOURCE = "reaction:eye.reflexive_stealth"


@hook("after_save")
def reflexive_stealth(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    engine, actor = ctx.engine, subject
    if failed or ability != "DEX" or not ctx.typed.get("area") or not has(engine, actor.entity_id, "reflexive_stealth"):
        return
    if not actor.active or not actor.reaction_available:
        return
    from .. import stealth

    if stealth.hidden(actor) is not None:
        return
    from ..ability_checks import VISUAL_CONCEALMENT
    from .. import motion

    modes = (motion.hide_mode(engine, actor),)
    bonus = skill(engine, actor, "Stealth", ability_modifier(actor, "DEX"))
    with activation(engine, actor, SOURCE):
        roll = engine.roll_check(modifier=bonus, actor_id=actor.entity_id, reason="CHECK:reflexive_stealth:stealth",
                                 ability="DEX", skill="Stealth", modes=modes, hazards=(VISUAL_CONCEALMENT,))
        engine._record_roll(roll)
        from . import floored  # Complete Mandala Auspice (combat/ext/d20_floor.py)

        roll = floored(engine, actor, roll, stealth.HIDE_DC)
        actor.reaction_available = False
        success = roll.total >= stealth.HIDE_DC
        engine._append_event("CHECK_ROLLED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": stealth.HIDE_DC, "success": success, "check": "Stealth"})
        if not success:
            ctx.engine._append_event("GM_RIDER", SOURCE, actor_id=actor.entity_id,
                                     payload={"rider": "Reflexive Stealth: the Hide attempt failed."})
            return
        # Bypasses stealth.can_hide's normal visibility gate on purpose (the talent's whole point); expires at the end of
        # the holder's own next turn if it still does not meet the normal Hide requirements (reflexive_stealth_expiry).
        engine._apply_condition(actor, stealth.HIDDEN, SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"stealth_total": roll.total, "reflexive_pending": True})
        engine._append_event("GM_RIDER", SOURCE, actor_id=actor.entity_id,
                             payload={"rider": "Reflexive Stealth: hidden by smoke, debris, movement or another feature of "
                                      "the triggering effect; ends at the end of your next turn unless you then meet the "
                                      "normal Hide requirements."})


@hook("turn_end")
def reflexive_stealth_expiry(engine: Any, actor: Any) -> None:
    from .. import stealth

    iid = stealth.hidden(actor)
    if iid is None:
        return
    data = actor.conditions[iid].data or {}
    if not data.get("reflexive_pending"):
        return
    if data.get("eye_hide_end_count") is not None and sum(e.event_type == "TURN_ENDED" and e.actor_id == actor.entity_id
                                                        for e in engine.events) < int(data["eye_hide_end_count"]):
        return
    if any(stealth.sees(engine, foe, actor) for foe in stealth.foes(engine, actor)):
        stealth.reveal(engine, actor, SOURCE, "reflexive stealth expired: does not meet the normal Hide requirements")
        return
    # Now meets the normal requirements on its own (e.g. it moved into real cover): keep it hidden, but this is a
    # one-time check -- refresh the condition (never mutate data in place) with the pending flag cleared.
    engine._remove_condition(actor, stealth.HIDDEN, SOURCE)
    engine._apply_condition(actor, stealth.HIDDEN, SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={**data, "reflexive_pending": False})
