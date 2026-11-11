"""Sniper second-pass precision (A2SNIPER):
  Existing attack_mode_removed also accepts DISADVANTAGE:long_range. Actions
  explicitly sealed with strike_penalty_provenance=1 split long-range penalties
  from adjacent-enemy/weapon penalties in typed_executor; only range gets the
  named provenance. The native resolver's existing provenance filter removes
  it before Advantage/Disadvantage cancellation. Unstamped catalogs retain their
  historical combined penalty/events. Removal never extends range, grants sight,
  or adds Advantage. sniper_precision supplies the owning Far Shot or live
  Hundred-Breath Wait policy. No locked engine/reducer/controller file changes.
  sniper_precision uses compile_block/compile_actions for weapon-backed Head
  Shot and Perfect Shot, turn_boundary_start for Still-Scope's actual starting
  posture, and transactional attack_result/rider_step for its benefits. Perfect
  Shot's sealed condition expires on this turn's end; only a real qualifying
  ranged attempt consumes it. Head Shot's threshold uses a resolution-local HP
  snapshot and this shot's settled damage packets, never prior damage. Its
  unsupported drop-to-zero eligibility remains a rider. All policy/ownership
  lives in new compiled rows; old saved actions without them remain inert."""
