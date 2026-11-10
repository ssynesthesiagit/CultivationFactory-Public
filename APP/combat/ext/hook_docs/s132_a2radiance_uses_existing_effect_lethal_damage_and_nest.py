"""A2RADIANCE uses existing effect, lethal_damage and nested event contracts:
  suppress_named_condition is an opt-in typed effect with explicit conditions.
  It offers one represented named ordinary condition instance, excluding explicit
  nonordinary/Legendary/Secret/artifact/Realm flags and protected printed source
  categories. It uses needle.ask and benefit_suppression.suppress(owner_turn):
  the caster chooses, the original instance clock runs while paused, and the
  original source/instance/data return at caster next-turn START if still alive.
  Names identify rules states, never guesses from a creature's name or flavour.
  rescue_movement=true on a hold_at_1hp reaction effect opts newly sealed Morning
  Breath rows into a second saved destination choice after damage commits.
  The caster chooses a square it perceives from native granted_movement.candidates
  for the recipient's 20-foot grant; granted_moves.commit resolves the route with
  provokes=False, preserving ordinary movement. All terrain, occupancy, posture,
  Speed, flight and hazard checks remain native. Declining the destination leaves
  the recipient at 1 HP. Unflagged saved reaction rows retain their old menu.
  Radiance’s Blessing uses a source-hash-gated compile_block passive and turn_start.
  needle.ask offers once-scene CP recovery when conscious, able to circulate and
  below the actual Path pool maximum; _gain_resource retains all resource vetoes.
  Accepted gain stores an integer _round_ use flag; decline, blocked recovery and
  full pools preserve the allowance. Initialization without a decision provider
  uses the choice helper's documented use-first fallback. Ability-score selection
  remains character construction. Old catalogs lacking the passive remain inert.
  No new engine seam, saved event shape, core dispatch or runtime replacement."""
