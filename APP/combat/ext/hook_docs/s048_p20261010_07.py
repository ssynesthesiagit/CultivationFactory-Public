"""General effect ending checkpoint (P20261010-07):
  Gate2 and its Gate3/Gate4 subclasses deliver CONDITION_REMOVED,
  MODIFIER_REMOVED, ZONE_REMOVED, CONCENTRATION_ENDED and SUMMON_DISMISSED
  through combat.effect_endings immediately after recording the event. Manual,
  deadline and nested endings call the same event subscribers exactly once,
  in registered priority order (ties retain registration order). The subscriber
  list is snapshotted; nested endings finish before the parent resumes.
  Ending dispatch is strict: subscriber failures become CheckpointError, player
  pauses propagate, and excessive cascades abort rather than skip cleanup.
  Ordinary non-ending events retain Gate4's existing nested-only policy.

  event(engine, event_type, kwargs) receives originating_event, the exact
  recorded event even after another subscriber appends children. Use this
  identity instead of engine.events[-1]. For exact condition/modifier removals,
  ended_effect carries a detached snapshot of the removed instance, including
  its original source, caster and data. It is transient, never a new event
  payload or saved schema. Pure replay applies the committed records without
  running subscribers. Post-removal hooks must be idempotent and event their
  own dependent mutations through the normal engine helpers.

  engine._remove_condition_instance and _remove_modifier_instance remove one
  instance, with optional expected=<original row> guarding snapshot sweeps
  against replacements. expiring=True offers effect_expiring_choice followed
  by effect_expiring before removal. Hooks may remove/replace the exact row or
  change its expiry; the deadline then preserves that result. Explicit manual
  removals have no expiry-extension offer. Source/copy-bound Concentration
  removal uses concentration.end_copy; departing/replaced owners end a fixed
  snapshot of copies and cannot restart Concentration during that teardown.

  Zone removals run area aftermath and reconcile walls and inside effects once.
  Summon departure ends its Concentration and stored zones explicitly marked
  follows_owner or ends_with_owner, then reconciles derived aura recipients.
  Mere zone ownership is provenance, not a lifetime link. Continuous area
  reconciliation defers reentrant passes and fails if its effects do not settle.
  Individual effect endings only prune obsolete area membership; they must not
  recreate a deliberately removed or suppressed continuous effect. Full area
  reconciliation remains with zone/movement changes, and a nested full request
  upgrades a pending removal-only pass.
"""
