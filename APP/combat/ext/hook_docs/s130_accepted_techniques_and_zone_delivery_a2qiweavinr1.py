"""Accepted techniques and zone delivery (A2QIWEAVINr1):
technique_accepted(engine, actor, action) -> None, strict. Called by typed
execution after action/payment acceptance, before technique_start vetoes and
counter reactions. Setting actions bypass it. May record activation limits;
transaction preview rollback and rejected intents retain the ordinary service
semantics. No subscriber changes historical activation behavior.
zone_creation_profile(zone, ctx) -> ZoneState | None, transactional sequential replacement after construction and before durability bonuses/commit; may refine a creation's geometry, duration and durability while retaining identity, owner and source. Default inert; zone_created receives the final profile. Providers own legal geometry and source-qualified consent; no preview mutation or ability-specific core branch.
Check d20 scopes carry explicit check-spec hazards as named values during drawing and opposed-check finalization; omitted hazards remain empty. Rewrite providers may read these causes without inferring them from conditions or hidden scene facts.
zone_created(ctx, zone) -> None, strict. Called after construction but before
ZONE_CREATED records the zone. Providers may add JSON-compatible activation
metadata to trigger_profile; they must not change identity or geometry.
trigger_harm(effects, numbers) -> None or True, pure query. Whether the effects
one zone trigger or named-terrain rule runs deal damage to the creature it works
on. Preview callers ask it too (movement-hazard tests for AI movement risk,
relocation that must avoid immediate harm), so a subscriber must answer from
committed state and must never mutate anything. combat/zones.py `_hurts` asks it before its historical damage/extra_damage
reading, so a plug-in whose trigger wraps its damage in a custom effect row (for
example a Seed pulse that resolves a save and damage of its own) still appears to
the shared movement-hazard query used by AI movement risk and by relocation that
must avoid immediate harm. With no subscriber, or one that answers None, only the
literal damage rows count, exactly as before; the row that actually deals the
damage is not duplicated here.
zone_follows(engine, zone) -> bool or None, strict. Whether an area that
records ``follows_owner`` rides its owner right now (combat/zones.py
``follows_now`` reads it after every move and when the owner moves). A False
answer ends the ride early, so the area stays where it is for the rest of its
duration -- an area that "moves with you only until the start of your next
turn" (Body as Center, combat/ext/body_as_center.py) records the turn it was
centered and answers False once the owner's turn count has moved past it.
Default inert: no subscriber leaves every recorded follower riding as before,
and an area that never records ``follows_owner`` is never asked.
zone_trigger_context(ctx, zone, creature, moment) -> None, strict. Called before
trigger effects run; providers may restore their recorded activation metadata
into transient typed/cache data. They must not ask a new activation choice or
spend activation resources. Absent metadata/subscribers leaves old zones inert."""
