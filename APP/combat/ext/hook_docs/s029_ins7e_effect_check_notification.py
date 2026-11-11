"""INS7E effect-check notification:
  effect_check_resolved(ctx, holder, item, check, success) -> None is a strict
  end_effect notification after its evented real Cultivation Check and outcome.
  It carries the actual checked condition/modifier and check metadata with
  purpose derived from the committed end (disrupt) or suppression operation. No check
  or no subscriber changes nothing; choices/errors roll back the action.
  Shared by source-qualified successful-check riders, independent of ability
  identifiers. Resonance Breaker requires Music Check and the opposing effect's
  recorded Sphere; opposed-check specs may additionally name effect_sphere,
  purpose (suppress/disrupt/identify), and effect_owner_id. Explicit purpose is
  required. A successful suppress/disrupt operation may also declare its actual
  disrupted_actor_id; an effect owner alone never establishes disruption, and
  identify never offers a disruption penalty. Missing facts are inert.
  Qi-Tempered movement uses ext.granted_movement's native candidate identities
  and modes, capped to five feet with every creature exempt from Opportunity
  Attacks during that move. No owned successful Independent Concentration bonus
  means no grant and no exemption scope.
  ext.granted_movement.move(..., nonprovoking=False) retains the named-creature
  exemption by default. True exempts every creature through the native
  opportunity_allowed query, including legacy reactors, for this move only.
  It preserves native mode/path identity and restores ordinary movement and
  exemption scope on completion or error; no call means no behavior change."""
