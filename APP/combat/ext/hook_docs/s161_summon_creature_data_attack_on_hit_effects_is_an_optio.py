"""Summon creature data: attack.on_hit_effects is an optional list of explicit
typed effects appended after the attack's damage and form rider. These run
with the creature's ordinary hit Context. specials may supply effects (a list)
instead of the legacy effect (one row), plus numbers mapping compiled numeric
keys to the existing summon formulas (pb, cl, key, atk, dc, ability modifiers).
Both forms are deep-copied into sealed actions. Absent fields preserve legacy
bodies. No ability name inference occurs. Chain Clone uses these fields for
Hooking Links, owner-DC Set the Tether, and ordinary Grapple/Shove options.
bound_object_bonuses(ctx, spec) -> {ac?: int, hp?: int} | None is a strict,
pure additive query before a bound object's constructor and creation event.
Only nonnegative integer bonuses are accepted; no answer preserves the printed
base statistics. The object records the final AC, current HP and maximum HP
through its normal creation event. Prison Warden is an owned-feature consumer."""
