"""Live movement Speed contracts (movement_speeds, flight, roof_movement, journey):
  all_movement_speeds_bonus(engine, actor) -> nonnegative integer feet | None.
  Strict pure query. Only an owned active all-Speeds benefit responds; absence
  adds zero. Walking retains its original speed/motion readers; independent
  existing modes add the returned bonus once before percentage restrictions.
  movement_speeds(engine, actor) -> capability dict | None supplies independent
  swim_speed_ft/burrow_speed_ft grants. Missing grants never create a mode.
  Capability rows may carry <mode>_speed_bonus_included_ft (integer feet already
  in the grant). Resolution replaces that recorded contribution with today's
  bonus before choosing the fastest grant, including native template Speeds.
  Public movement_speeds.land_speed_grant declares <mode>_speed_uses_walk_bonus=1
  and the actual included contribution for walking-derived grants. The public
  speed_contributions.effective_speed(include_all_movement_bonus=False) pure
  projection removes these already-contributed walking bonuses before final
  restrictions. Queries replace only their actual walking contribution, so a
  halved bonus remains halved without changing other snapshot components.
  Live providers still recompute their whole grant as before. All recorded
  leaves are integers. No provider
  may infer provenance from equal numeric speeds or call a sibling's internals.
  Source-sheet speed.flying_ft/climbing_ft/swimming_ft/burrowing_ft are native
  independent facts retained by compiler/templates/replay. Zero is absent.
  Mapped swim/burrow routes require authored travel_regions of kind water or
  burrowable at the destination's altitude. Geometry, occupancy and solid walls
  remain authoritative. These modes add no teleport range or wall bypass.
  Journey move payload accepts optional mode (default walk), offers every legal
  mode in its ordinary menu, and scales its sourced walking pace by the ratio
  of native live mode Speed to source walking Speed. It introduces no fixed
  feet/hour conversion. CombatService continues to own encounter transfers."""
