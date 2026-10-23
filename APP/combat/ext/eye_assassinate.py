"""Assassinate (eye, 2026-09-28): "When you reduce a creature to 0 Hit Points with an attack roll while hidden, making
that attack roll does not cause you to stop being hidden. After resolving the attack, compare your recorded Dexterity
(Stealth) check against the Passive Perception of each creature that could detect you. A creature whose Passive
Perception equals or exceeds your recorded check finds you." Uses the new "attack_reveal" hook (typed_executor.py) to
pre-empt the normal "an attack roll ends Hidden" rule for exactly this one case.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .eye_common import has, passive_perception


@hook("attack_reveal")
def assassinate_reveal(ctx: Any, target: Any, hit: bool) -> bool | None:
    engine, actor = ctx.engine, ctx.actor
    if not hit or target.active:  # only Assassinate's own case: this attack just reduced target to 0 HP
        return None
    from .. import stealth

    iid = stealth.hidden(actor)
    if iid is None or not has(engine, actor.entity_id, "assassinate"):
        return None
    check_total = int((actor.conditions[iid].data or {}).get("stealth_total") or 0)
    found_by = [foe for foe in stealth.foes(engine, actor) if foe.active and passive_perception(engine, foe, actor) >= check_total]
    if found_by:
        stealth.reveal(engine, actor, ctx.source, "assassinate: found")
        names = ", ".join(foe.display_name for foe in found_by)
        ctx.rider(f"Assassinate: {target.display_name} fell while you were hidden; the kill does not end your hidden "
                  f"state by itself, but {names} noticed (Passive Perception >= your recorded Stealth check {check_total}).")
    else:
        ctx.rider(f"Assassinate: {target.display_name} fell while you were hidden; the kill does not end your hidden "
                  f"state, and no one's Passive Perception matches your recorded Stealth check {check_total}. You "
                  f"still stop being hidden if another rule ends it (a loud sound, losing all concealment).")
    return False  # handled the reveal decision itself; the default "attacked" reveal must not also run
