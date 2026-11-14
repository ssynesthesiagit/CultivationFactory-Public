"""immunity_as_resistance(engine, damage_type, incoming_typed, incoming_actor_id,
target) retains its legacy bool result. A source-qualified consumer may instead
return {modifier_ids: [exact ids], feature_ids: [exact ids]}. The native resolver
converts only those currently qualifying Immunity instances to Resistance;
another overlapping Immunity remains active. Empty/absent replies are inert,
malformed mappings fail validation, and the underlying source is never removed.
Maw uses source-bound expiry conditions; Myriad-Venom retains whole-type True.
Lock18 condition contracts:
  attack_critical_qualification(engine, attacker, target, spec, roll, intent)
  -> bool | None. Pure, strict query once after a hit and before damage. True
  qualifies that hit only; natural/expanded criticals join it before the existing
  critical_cancel providers. None/False is inert. Cancellation reaches the same
  hit context and one damage packet; no second critical provider invocation.
  damage_defenses(engine, target, damage_type, typed, source_actor_id)
  -> list[defense row] | None, pure. Same row schema as standing defenses (kind,
  damage_types and optional scope). Empty is inert. Applies once to typed targets;
  nonempty matching rows opt native targets into the common defense reader,
  combining resistance once with native modifiers/runtime resistance and honoring
  penetration. No new saved fields or events are needed for either pure query.
  condition_rules(actor, engine=None) returns fresh shared data/inline rule rows;
  condition_id_aliases maps legacy full IDs (core Dodge) without changing saved
  state. Optional condition_aliases maps legacy typed names. Suppressed conditions contribute no
  rule. roll_modes_require_source_visible filters attack/check modes only, using
  the recorded source and live visibility when engine is supplied (unknown is
  not visible). Native attack/check consumers supply it. Rule data remains intact.
  standard_conditions reads critical_hit_within_ft and damage_resistances only
  for their condition holders. disabled_if_incapacitated_or_speed_zero permanently
  removes that condition through normal CONDITION_REMOVED events at event delivery;
  pure roll readers also suppress invalid benefits in an old loaded snapshot.
  Attack sight masks are passed as instance-ID projections; no state dictionary
  replacement. Save advantages/disadvantages combine once across all causes.
  Native typed-condition applications consult the existing condition_immune query.
  Concentration damage saves cap DC at 30; no new end-of-turn check."""
