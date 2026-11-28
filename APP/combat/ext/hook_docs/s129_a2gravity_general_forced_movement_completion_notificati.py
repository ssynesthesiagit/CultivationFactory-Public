"""A2GRAVITY general forced-movement completion notification:
  forced_movement_reduced(ctx, subject, before_ft, after_ft) -> None.
Strict notification after all typed forced_movement_reduction providers have
combined, before any native route/step. before_ft is what interception and
ordinary reactions left; after_ft is the clamped remainder. It is called only
during actual resolution, never a pure candidate/quote. It may ask the subject
for a printed response and record its own cost/effect; it must not rewrite the
supplied movement distance. No subscriber response leaves the move unchanged.
Anchor Stance reads newly sealed stopped_focus rows/shared conditions here.
Its supported Anchor contribution and a zero remainder permit the mover's
optional Reaction through can_use_reaction/spend_reaction. Old sealed rows and
conditions omit the opt-in and cannot open the new response.
Crushing Focus also subscribes to the existing strict repeat_save_scope.
Its normal context-manager exit observes resolution.success after native
repeat_save_failed rewrites and exact-instance removal. Exceptions/pauses do
not commit a bonus, and the caster's shared per-turn allowance covers initial
and repeated saves alike. No repeat subscriber is installed for an old owner
without the newly reviewed Insight row.
The existing movement_paths reduction helper is now shared by typed push/pull
and caller-context chosen forced routes. Both emit the completion notification
after interception, ordinary reactions and additive reductions, exactly once.
Legacy engine.move_path calls without a resolution Context retain their old
behavior and cannot emit source-bound reduction responses.
Mountain Stance answers both typed save metadata and the existing source-aware
native save_mode named metadata; ordinary saves receive no new roll mode.

  first_thirty_feet is sealed on new Falling Hammer/Feather Body rows.
  Feather Body requires Body Lightening; legacy rows retain their prior fall
  calculation. The single distance answer excludes the first thirty feet once."""
