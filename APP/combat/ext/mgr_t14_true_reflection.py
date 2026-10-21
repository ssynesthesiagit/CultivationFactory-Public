"""True Reflection (Mirror Cultivator CL18): the Reaction's True Doppelganger lasts Concentration up to 1 minute.

The Doppelganger is called by a Reaction, not an Action, so combat/summons.py ``summon`` has no
``action_catalog`` entry to read the printed duration from (its own action-summon path stamps
``expires_on`` from the calling action's typed duration and the technique use starts Concentration).
This plug-in stamps the printed "1 minute" and begins the summoner's Concentration on the
Doppelganger at its own appearance, for this source's creature only; every other summon keeps the
duration its own source already gives. Ending Concentration dismisses it through
combat/summons.py ``on_concentration_end``: the Concentration is held on
``reaction:typed.<feature>``, whose tail matches the record's own ``source``.
"""
from . import hook

#: The activation that calls the Doppelganger, and the creature group combat/rules/summons.json gives it.
FEATURE = "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"
GROUP = "true_doppelganger"
#: Printed "Duration: 1 minute / Concentration: Required".
DURATION = {"kind": "minutes", "amount": 1}
#: Reaction rows hold Concentration under this id shape ("reaction:typed.<feature>"), matching the compiler's action_id.
CONCENTRATION_SOURCE = f"reaction:typed.{FEATURE}"


@hook("summon_appeared")
def true_reflection_concentration(engine, owner, creature, source_id):
    """No other creature or summoner is touched: a missing or different record stays exactly as it was."""
    record = getattr(creature, "summon", None) or {}
    if (record.get("group") != GROUP or record.get("source") != FEATURE
            or record.get("owner") != owner.entity_id or record.get("status") != "present"):
        return
    from ..typed_executor import duration_expiry

    record["expires_on"] = duration_expiry(engine, DURATION)
    record["duration_text"] = "1 minute"
    engine._start_concentration(owner, CONCENTRATION_SOURCE)
