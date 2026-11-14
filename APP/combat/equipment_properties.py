"""Equipment-property arithmetic shared by Imbuement and damage defenses.

An enhancement replaces, rather than adds to, the compiled magical bonus.
Suppression removes magical numeric bonuses, not independent properties or
mundane ability/training bonuses. All queries are pure. Weapon ancestry is the
same public weapon_delivery contract used by attacks and hand occupancy.
"""


def packet_weapon(engine, actor_id, typed):
    """Resolve a catalogue packet or explicit delivery to one physical weapon.

    Native/derived packets must supply delivery metadata; an unknown packet
    never borrows the actor's best weapon or guesses from an item/display name.
    """
    from .weapon_delivery import weapon_identity
    for source, action in engine.action_catalog.items():
        if action.owner_id == actor_id and (action.parameters or {}).get("typed") is typed:
            return weapon_identity(engine, source, typed, action.parameters)
    delivery = typed.get("delivered_by") or typed.get("weapon_source_id") or typed.get("opportunity_of")
    if delivery:
        action = engine.action_catalog.get(delivery)
        return weapon_identity(engine, delivery, ((action.parameters or {}).get("typed") or {}) if action else {},
                               action.parameters if action else {})
    return None


def enhancement_delta(compiled, rules, channel):
    """One channel's change from the bonus already folded into its base total."""
    relevant = [r for r in rules if channel in r.get("magic_channels", ())]
    if not relevant:
        return 0
    if any(r.get("suppress_magic") for r in relevant):
        return -int(compiled)
    return max([int(compiled), *(int(r.get("magic_bonus") or 0) for r in relevant)]) - int(compiled)
