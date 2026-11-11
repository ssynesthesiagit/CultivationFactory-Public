"""General attack_roll_modes(engine, attacker, target) -> iterable containing
ADVANTAGE and/or DISADVANTAGE, or None. Strict pure query shared by native,
portable and typed attacks and read-only menu presentation. Contributions
are read by combat.attack_modes.contributed(engine, attacker, target),
which returns a strict frozenset of uncancelled strings. They combine with
each resolver's existing modes before cancellation (and native/typed mode
removals). Portable attacks retain their local burning/opening rules.
Providers may not roll, consume, emit events or mutate state;
absent providers/None change no behavior. Consumers remove one-use grants
only from actual ATTACK_ROLLED receipts, including cancelled Advantage.
foundations3 is the first consumer: its newly sealed Heartfire Surge boon
contributes against hostile targets only; saved markerless catalogs are inert.
Athletics also transports motion-row protection through this hook for every
attack profile. combat.typed_reactions.opportunity_trigger(engine, attacker,
target, source=None) returns the explicit accepted-OA cause or None; matching
participants and optional source are required. movement scopes are produced
by committed leave-reach steps, granted/assistance scopes by their producers.
motion reads only movement; attack_completion may read every cause. The query
never spends, consumes or persists state, and missing scopes are inert."""
