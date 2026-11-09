"""Move-before-attack activation geometry (CHARGEMOVE1):
  activation_target_geometry(engine, actor, target, action, *, destination=None)
  -> bool | None. Pure, strict query replacing ONLY a target's activation reach
  and line-of-effect geometry. True must prove a native legal route and a legal
  attack from the same reachable square; False denies. Multiple providers
  combine with all. None preserves normal geometry. Knowledge, relations,
  costs and actual attack checks are unchanged. destination is a remembered
  target's known square: the provider checks the grant and attack against that
  square and never reads the hidden creature's current position; so a
  remembered target within the grant is offered, and one beyond it is denied.
  Default-inert without a typed opt-in.
  move_attack implements top-level move_then_attack effects before normal
  attack rows. distance_ft is an integer or "speed" (optional integer
  speed_numerator/speed_denominator). no_oa, no_oa_from_target,
  ignore_nonmagical_difficult and hostile_spaces configure the movement.
  weapon_words uses the delivering ready weapon's current reach;
  weapon_attack also uses its attack bonus while retaining the talent save DC.
  attack_during allows an attack square followed by remaining movement.
  Native granted paths use an independent budget, never the Move action.
  Existing pass_through/difficult_exempt hooks apply these traits only within
  route queries/commits, without replacing engine methods or permanent grants.
  Existing variant producers may promote a reviewed menu.movement row into
  their active effects (One Opening), leaving the standing menu inert.
  Human square choices retain every legal endpoint; automatic choices prefer
  the cheapest attack square and share the same native traversal and attack."""
