"""Nested free weapon attacks:
  combat.targeting.reason(engine, actor, target, action) -> denial text or None
  and in_range(engine, actor, target, action) -> bool are the shared pure menu
  and execution queries: footprint reach for located creatures, remembered
  square range for unseen creatures, and the owner's line-of-effect policy.
  combat.target_knowledge.attack_aim(engine, actor, target, action) is a scoped
  context manager for melee and improvised follow-up attacks inside another
  accepted action. It freezes that attack's own known square for the shared
  location_missed checkpoint; it never follows concealed movement. No return
  value or persisted state; nested scopes and consent/errors restore the prior
  transient receipt. Absent a scope, existing candidate targeting is unchanged."""
