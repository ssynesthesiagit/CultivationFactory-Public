"""Scene recovery and protected condition seams (INS7D):
  scene_recovery_limit(engine, actor, feature) -> int | None is a strict pure
  query; the maximum returned positive allowance extends the default one use.
  No provider preserves that allowance. Recovery callers own their counter,
  resource and timing. Golden Core's action and Perfected turn trigger share it.
  scene_recovery_used(engine, actor, feature, use_number) -> None is a strict
  notification after resource restoration and before the action commits.
  Default inert; providers gate ownership and event mandatory aftermath.
  effect_removal_allowed(engine, holder, kind, row, source) -> bool | None is a
  strict condition/modifier interception before any exact-instance removal.
  False vetoes whole removal; providers may event a replacement retaining a
  protected remainder, and the caller rechecks the original instance identity.
  None with no replacement preserves removal, including normal deadlines.
  forged_exhaustion.set_level(..., scene_locked_levels=0) preserves a saved
  integer minimum until terminal_result ends the scene. Ordinary cures can
  remove excess levels; exact removal cannot erase the protected minimum.
  engine._apply_condition(target, condition_id, source_id, source_actor_id, expires_on=..., data=None, unavoidable=False)
  accepts an explicit unavoidable printed rule: True bypasses immunity and
  condition_application_attempt prevention, preserving ordinary event/replay
  and expiry. Default False preserves all normal prevention. Protected costs
  and replacements that retain them use it; unrelated increases do not.
  These seams carry no ability identifiers or per-ability branches in core.
reaction_rows(engine, actor_id, block, rows) -> replacement list or None.
Pure query before normal reaction eligibility. Default inert; subscribers
return fresh rows and never mutate compiled rows. Subscribers are applied in
registration order and each one sees the rows the previous subscriber
returned, so a subscriber that adds a reaction moment and one that expands
the compiled rows compose instead of erasing each other. reaction_modes metadata
retains each resolved choose-one effect tree; reaction_menus exposes them only
for an owned Ask-me row under manual control. consent_source_id is an optional
decision binding; feature_id remains the cost/limit/effect source."""
