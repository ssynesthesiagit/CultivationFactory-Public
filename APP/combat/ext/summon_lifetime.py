"""Expire summons at the native turn boundary using their persisted lifetime data.

Duration expiry uses ``expires_on``; concentration and destruction retain their
existing engine paths. The optional ``ends_with_summoner`` policy requires explicit
rules or owner authority for removal on owner defeat. No current source opts in.
Corpse Servant lasts "Until destroyed or dismissed": losing its summoner neither
destroys nor dismisses it, even if it can no longer receive commands.

The generic policy seam remains available for an authorized future source and
already-persisted records. Missing policy is inert. Unconscious but active owners
and owners revived before the boundary do not trigger it. Dismissed creatures
still retain the engine's turn-slot bookkeeping, but take no action there.
"""
from . import hook
from .effect_durations import stored_token_due
from ..summons import dismiss

#: The one lifetime word combat/rules/summons.json may put in a source, and the reason the creature
#: leaves with its summoner. An absent or different value is inert: the creature keeps whatever
#: lifetime its own printed text already gives it.
ENDS_WITH_SUMMONER = 'ends_with_summoner'


@hook('turn_boundary_start', priority=-100)
def expire_summons(engine, actor, *, checkpoint=None):
    """No deadline in the saved summon record means no new behavior or event."""
    for creature in tuple(engine.state.actors.values()):
        record = creature.summon
        if (record and creature.active and record.get('status') == 'present'
                and record.get('expires_on') and stored_token_due(engine, record['expires_on'], creature.turn_flags,
                    'summon_lifetime', actor=actor if checkpoint else None, checkpoint=checkpoint)):
            dismiss(engine, creature, 'DURATION_ENDED',
                    log=f"{creature.display_name}'s {record.get('duration_text', 'duration')} is up; it disappears.")


@hook('nominal_slot_boundary', priority=-100)
def nominal_summons(engine, actor, checkpoint):
    expire_summons(engine, actor, checkpoint=checkpoint)


def _summoner_out_of_the_fight(engine, record) -> bool:
    """True when the fighter this creature was printed to obey has been defeated: gone from the
    fight with no Hit Points left.  Unconscious at 0 Hit Points is not that -- that fighter has not
    left, so its creatures have not lost their summoner.  A missing or creature owner answers False.
    This reads the fight, never the rules, so a fight saved before any lifetime policy existed (its
    summon records carry an ``owner`` but no ``lifetime``) answers False through the policy check in
    ``dismiss_orphans`` and every old summon stays exactly where it was."""
    owner = engine.state.actors.get(record.get('owner') or '')
    if owner is None or owner.summon is not None:
        return False  # a missing or creature owner is not a defeated summoner
    return not owner.active and owner.primary_combatant and owner.current_hp <= 0


@hook('turn_boundary_start', priority=-100)
def dismiss_orphans(engine, actor):
    """A creature whose own printed lifetime says it ends with its summoner leaves the map when that
    summoner falls.  Every other creature is untouched: a record with no ``lifetime`` (which includes
    every fight saved before this rule) and a source that never asked for it both do nothing here,
    so a living summoner, a trained beast, a timed ritual and an old save are all left as they are."""
    for creature in tuple(engine.state.actors.values()):
        record = creature.summon
        if (record and creature.active and record.get('status') == 'present'
                and record.get('lifetime') == ENDS_WITH_SUMMONER and _summoner_out_of_the_fight(engine, record)):
            owner = engine.state.actors[record['owner']]
            dismiss(engine, creature, 'OWNER_DEFEATED',
                    log=f"{creature.display_name} leaves the map: {owner.display_name}, who called it here, "
                        f"is out of the fight.")
