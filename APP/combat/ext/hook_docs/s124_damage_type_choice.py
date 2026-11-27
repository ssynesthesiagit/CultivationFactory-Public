"""damage_type_choice(ctx, kinds, targets) -> one allowed damage type or None.
    General transactional checkpoint in typed_executor.choose_damage_type for a
    printed player choice, shared by attack and save/area damage. Exactly one
    provider may answer, and its result must be in kinds. Context and targets are
    resolution-local, never saved. No answer preserves the historical automatic
    selection and old event bytes. Newly sealed Corpse Explosion uses one choice
    for the whole blast; manual owners are asked, while AI preference considers
    perceived targets only. The hook is inert without an owning provider.
damage_defended(engine, target, damage_type, source_id, source_actor_id, defenses) -> None
is a real-packet notification from typed_reactions.defend, after defenses and
next-instance consumption; never from pure damage_factor queries. defenses is
a fresh dict with resist and resistance_suppressed booleans. Suppression covers
penetration and packets that prohibit reductions, even without prior Resistance.
Subscribers may retain an ephemeral receipt for final_damage, handling nested
packets in order. Do not modify defenses or ask/spend here; choices belong to
final_damage. No subscribers means no behavior change. This does not cover
native packets that bypass typed_reactions.defend; owners must opt into the
shared typed defense path. The receipt is never serialized or replayed state."""
