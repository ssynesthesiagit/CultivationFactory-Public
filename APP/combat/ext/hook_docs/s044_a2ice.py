"""General native condition, physical destruction and Temporary HP checkpoints (A2ICE):
  zone_cells_destroyed(engine, zone, cells) -> None.
    Strict checkpoint before native wall sections or larger lattice cells are
    destroyed. Cells are the exact removed Positions; expiry, replacement and
    cap eviction do not call it. Providers may resolve owner aftermath choices
    transactionally. Whole-wall destruction reports all its cells once.
  condition_application_attempt(engine, target, condition_id, source_id, source_actor_id) -> bool | None.
    Strict transactional checkpoint after immunity and before a new native
    condition instance. False prevents this application; True/None permits it.
    May ask the affected player's optional prevention choice and record its
    allowance. No new condition/event is synthesized by the caller when vetoed.
    Ordinary typed, native and nested applications share this one boundary;
    pure immunity queries never spend a once-per-scene prevention.
  temp_hp_offered_bonus(engine, target, amount, source_id, source_actor_id, *, consume) -> nonnegative int | None.
    Strict transactional addition after grant denial and before healing_pending
    and max(existing, offered). Providers qualify the actual recipient and
    granting source, own any activation limit, and add to a positive offer only.
    Rejected equal/lower offers keep the existing grant's identity. Missing
    providers leave ordinary Temporary HP unchanged; invalid replies roll back.
  check_hazard_mode(engine, actor, ability, skill, hazards) -> ADVANTAGE | DISADVANTAGE | None.
    Pure strict check_modes query when a check carries explicit nonempty hazard
    or subject tags. Combines with ordinary independent modes; conflicting
    Advantage/Disadvantage cancel normally. No inferred topic or recipient.
  Ice's shared plugin API: ice_lattice.counted_spaces/lattice_limit quotes
    individual cap-counted spaces for ice_second_pass.scholar_space. The
    ice_fracture source_feature/fracture_numbers/response_available/count_response/
    shatter_response helpers preserve existing response/save/choice delivery.
    ice_second_pass.preserve_space optionally replaces a shatter ending; only
    that cell receives the shortened native owner-turn deadline. All state is
    evented JSON data. New ice_winter_crucible and icefall_lattice effect rows
    opt into their aftermath; unowned or markerless rows retain previous paths.
  footprint_is_authoritative (zone.trigger_profile): when true, the persisted
    affected_cells define the effective horizontal footprint for area membership
    and display. It only ever narrows columns: the native shape and height rules
    still decide the vertical volume, so a reduced footprint never extends a
    zone above or below its own recorded extent. A clipped radial zone proves
    membership at a surviving column rather than anywhere in the old radius.
    Missing/false keeps the ordinary shape-derived footprint.

"""
