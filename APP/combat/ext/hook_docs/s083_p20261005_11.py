"""General rider flight and skill projections (P20261005-11):
  general_flight(ctx, row) applies an explicitly typed fixed Fly Speed/Hover
  condition to its own user for the printed duration. Native flight owns paths,
  movement payment, altitude and falling; walking Speed is unchanged. Only the
  same source is refreshed, leaving other flight grants independent. No owning
  row changes existing actors or saved actions.
  compile_skill_bonuses(info) -> None or {skills: changed named skill rows,
  notes: strings, handled_features: owned feature IDs}. A pure strict compiler
  hook before all skill reads; inputs include skills, owned_ids, mechanics,
  mods, pb and owner_sheet (including repeated acquisitions). Providers preserve unrelated skill adjustments, never mutate
  the input, and claim a feature only when they completely implement it.
  general_skill_expertise replaces the known proficiency component with twice
  PB; legacy totals lacking rank remain unchanged with an unresolved-rank
  diagnostic and are not claimed handled. The projected skill rows are sealed
  in new bundles. No matching
  typed row means no projection; old saved skill totals remain unchanged.
  New factory bundles also preserve explicit skill ranks in skill_proficiency
  (skill name -> integer 0/1/2). combat.ability_checks.proficiency_rank is shared
  by the compiler and Expertise projection; roll_skill_proficiency reads scoped
  check metadata or a named native check reason. Fate uses this provenance for
  its stacking exclusion. Missing ranks remain unknown, never inferred from totals."""
