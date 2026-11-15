"""General rider movement and repeat saves (P20261005-11):
  general_rider_step(ctx, row) reuses rider_step's choice and bounded native
  granted movement. Its candidate_allowed listener is scoped to the owning
  engine, actor and source. visible_destination applies native sight and sense
  queries without changing altitude or observed occupancy. Ordinary movement and opportunity
  attack flags retain their existing behavior after the step finishes.
  Repeat saves use existing condition/ongoing repeat_save data, its original
  caster DC and the native holder-turn checkpoint's exact-instance removal.
  Recipient rate limits use zone triggers' existing per_round field and native
  per-recipient counters shared by enter/start events. No matching typed row
  adds a listener or a counter to an old saved fight."""
