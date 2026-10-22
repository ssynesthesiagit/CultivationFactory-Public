"""True Reflection (Mirror Cultivator CL18): the Reaction's True Doppelganger lasts Concentration up to 1 minute.

The Doppelganger is called by a Reaction, not an Action, so combat/summons.py ``summon`` has no
``action_catalog`` entry to read the printed duration from (its own action-summon path stamps
``expires_on`` from the calling action's typed duration and the technique use starts Concentration).
This plug-in stamps the printed "1 minute" and begins the summoner's Concentration on the
Doppelganger at its own appearance, for this source's creature only; every other summon keeps the
duration its own source already gives. Ending Concentration dismisses it through
combat/summons.py ``on_concentration_end``: the Concentration is held on
``reaction:typed.<feature>``, whose tail matches the record's own ``source``.

Two printed clauses are also read from the triggering packet when the Doppelganger appears:

* its Mirror Strike may deal "one damage type dealt by the triggering damage packet" -- recorded on the
  summon and offered beside the printed Force/Psychic through the ``damage_type_choices`` seam;
* the Doppelganger's size follows the triggering creature's (maximum Large) -- the summon's own
  ``size_from_trigger`` effect in the reviewed record, applied by combat/summons.py ``summon``.

Both are inert for every creature that is not this source's Doppelganger.
"""
from . import hook

#: The activation that calls the Doppelganger, and the creature group combat/rules/summons.json gives it.
FEATURE = "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"
GROUP = "true_doppelganger"
#: Printed "Duration: 1 minute / Concentration: Required".
DURATION = {"kind": "minutes", "amount": 1}
#: Reaction rows hold Concentration under this id shape ("reaction:typed.<feature>"), matching the compiler's action_id.
CONCENTRATION_SOURCE = f"reaction:typed.{FEATURE}"


def _ours(creature) -> dict:
    """The summon record when it is this source's creature; empty otherwise (every other actor stays untouched)."""
    record = getattr(creature, "summon", None) or {}
    if record.get("group") != GROUP or record.get("source") != FEATURE:
        return {}
    return record


@hook("summon_appeared")
def true_reflection_concentration(engine, owner, creature, source_id):
    """No other creature or summoner is touched: a missing or different record stays exactly as it was."""
    record = _ours(creature)
    if not record or record.get("owner") != owner.entity_id or record.get("status") != "present":
        return
    from ..pending_damage import current
    from ..typed_executor import duration_expiry

    # The packet that triggered the Reaction: its settled type is the printed additional Mirror Strike choice.
    packet = current(engine)
    damage_type = str(getattr(packet, "damage_type", None)
                      or getattr(engine, "_typed_pending_damage_type", None) or "").strip().upper()
    if damage_type:
        record["trigger_damage_type"] = damage_type
    record["expires_on"] = duration_expiry(engine, DURATION)
    record["duration_text"] = "1 minute"
    engine._start_concentration(owner, CONCENTRATION_SOURCE)


@hook("damage_type_choices")
def true_reflection_packet_damage_type(ctx, kinds):
    """Mirror Strike: "Force. Psychic. One damage type dealt by the triggering damage packet."

    ``kinds`` are the row's printed Force/Psychic; the triggering packet's own settled type is offered beside
    them, so the automatic "lands hardest" pick can use it and the printed types stay legal. Inert for every
    other attacker."""
    record = _ours(getattr(ctx, "actor", None))
    if not record:
        return None
    trigger = str(record.get("trigger_damage_type") or "").strip().upper()
    if not trigger or trigger in {str(kind).upper() for kind in kinds}:
        return None
    return [*kinds, trigger]
