"""One Concentration save per damaging attack, against its combined attached damage.

A confirmed attack can attach several damage packets (its primary damage and riders
such as a second damage type). Each packet used to call its own Concentration save.
combat/rules/concentration.json: a damaging hit calls for one save. Here an attached
packet only adds its damage to a per-roll total on the target; the save runs once,
from attack_damage_final, after every packet of that attack has resolved.

Standalone damage (no AttackDamage provenance) and separate attacks (different roll_id)
keep their own saves. The total lives on the target's turn_flags so a pause or reload
mid-attack keeps it.

The first packet also records the event sequence at which the save became owed. The
save is rolled later, after this hit's rider windows, so a one-use "Disadvantage on
its next Concentration saving throw" that such a rider creates a moment ago (Sound's
Dissonant Pulse) must not reach back and penalise the save this very damage caused;
it stays on the creature for the next one. A mode that was already on the creature
when the damage landed still applies.
"""

KEY = "concentration_attack:"


def _key(attack_context) -> str:
    return f"{KEY}{attack_context.roll_id}"


def defer(engine, target, amount: int, source_actor_id, source_definition_id) -> bool:
    """Record an attached packet's damage for the attack's single save.

    Returns False (caller keeps the immediate save) when this damage is not an
    attached attack packet. Returns True when the save is deferred to the attack's end.
    """
    attack = engine.damage_context()
    if attack is None or attack.target_id != target.entity_id or target.concentration is None:
        return False
    entry = target.turn_flags.get(_key(attack))
    if entry is None:
        entry = {"amount": 0, "source_actor_id": source_actor_id, "damage_source_id": source_definition_id,
                 "started_sequence": target.concentration.started_sequence,
                 # Sequence of the first packet: the save is owed from here, so a
                 # one-use mode created by this hit's later riders is for the next one.
                 "owed_sequence": int(getattr(engine.state, "event_sequence", 0) or 0)}
    entry["amount"] = int(entry["amount"]) + int(amount)
    target.turn_flags[_key(attack)] = entry
    return True


def resolve(engine, target, attack) -> None:
    """Run the attack's one Concentration save with its combined damage, if still owed."""
    entry = target.turn_flags.pop(_key(attack), None)
    if entry is None or not target.active or int(entry["amount"]) <= 0:
        return
    held = target.concentration
    # A Concentration begun after this attack's damage is not the one that was damaged.
    if held is None or held.started_sequence != entry["started_sequence"]:
        return
    engine._concentration_check(target, int(entry["amount"]), source_actor_id=entry["source_actor_id"],
                                damage_source_id=entry["damage_source_id"],
                                owed_sequence=int(entry["owed_sequence"]) if "owed_sequence" in entry else None)
