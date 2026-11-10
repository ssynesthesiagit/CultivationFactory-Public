"""Shared Major Spirit Bond counter and saved-condition projection.

Used by spirit_bonds (destruction, Pact recovery) and spirit_intercession
(post-hit payment). No ability hooks are registered here. Existing resources
and retained conditions gate changes; old fights without the resource remain
condition-only. Updates preserve source/expiry and cannot trigger fresh causes.
"""
from typing import Any
from . import note

STRAIN = "resource:named.bond_strain"
STRAIN_MAX = 3
STRAIN_CONDITION = "condition:typed.spirit_bond_strain"


def sync_bond_strain(engine: Any, owner: Any, count: int) -> None:
    """Project spirit_bonds' Major Spirit Bond counter onto saved conditions.

    Used by spirit_bonds for destruction gains and Pact recovery. Old fights
    without the resource keep their condition-only Intercession bookkeeping.
    """
    from .retained_updates import record_instance_update

    for key, condition in owner.conditions.items():
        if condition.condition_id != STRAIN_CONDITION or condition.data.get('strain') == count:
            continue
        spirit = engine.state.actors.get(condition.data.get('bond_id'))
        name = getattr(spirit, 'display_name', 'your spirit')
        condition.data = {**condition.data, 'strain': count,
                          'label': f'Bond Strain {count}: stress on the bond with {name}. '
                                   'At 3 the bond is in crisis; the GM resolves the spirit\'s response.'}
        record_instance_update(engine, owner, 'condition', key, condition)


def strain(actor: Any) -> int:
    return int(actor.resources.get(STRAIN, 0))


def add_strain(engine: Any, owner: Any, amount: int, source: str, why: str) -> None:
    """Move the owner's Bond Strain by ``amount`` (0-3), with a plain log line; a crisis at 3 is the GM's."""
    if STRAIN not in owner.resources or not amount:
        return
    before = strain(owner)
    if amount > 0:
        gained = min(amount, STRAIN_MAX - before)
        if gained > 0:
            engine._gain_resource(owner, STRAIN, gained, source)
    else:
        spent = min(-amount, before)
        if spent > 0:
            engine._spend_resource(owner, STRAIN, spent, source)
    after = strain(owner)
    # Keep the existing saved per-bond condition as a projection of the shared
    # Major Spirit Bond counter, including destruction gains and Pact recovery.
    sync_bond_strain(engine, owner, after)
    crisis = " The bond is in crisis: the GM chooses what the spirit does." if after >= STRAIN_MAX and before < STRAIN_MAX else ""
    note(engine, source, owner, f"{why} Bond Strain (stress on the bond with the spirit; at {STRAIN_MAX} the spirit may refuse or act on "
                                f"its own) {before} -> {after}.{crisis}")
