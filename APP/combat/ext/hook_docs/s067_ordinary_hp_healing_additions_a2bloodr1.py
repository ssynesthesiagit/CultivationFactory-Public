"""Ordinary HP healing additions (A2BLOODr1):
  healing_offered_bonus(engine, subject, amount, *, consume) -> int | None
  adds nonnegative integers to a positive ordinary HP offer before stored
  subtraction/halving, assignment, interception and capping. Called strictly by
  typed_executor.stored_healing_reductions; errors roll back the transaction.
  consume=False is a pure estimate: providers must not mutate or consume usage.
  consume=True may commit a provider's allowance once per offer. No event is
  synthesized and Temporary HP/explicit HP restoration do not enter this seam.
  Missing providers retain the prior amount. Raw native _heal callers own their
  stored-reduction preparation and must enter this helper before committing HP.
Provenance-aware healing additions (A2GINS7r5):
  healing_offered_bonus_from(engine, subject, amount, *, consume, healer, source, sphere, power_resources, eligible_recipients, action_name, activation_id) -> int | None
  is the same flat addition at the same point, for a rider whose printed trigger
  names its own caster and feature ("when a Qi-powered feature restores Hit
  Points"). It carries the acting creature, the granting source definition id and
  the feature's sphere and resource costs, so explicit Qi-powered features with no
  sphere can qualify. The resolved eligible roster, action display name and activation
  token bind a choice to the actual recipients and action. Callers that do not know their provenance omit
  it and this seam is not called at all; with no provider registered it returns an
  empty list and the offer is unchanged. A provider must qualify owner, feature and
  activation itself, and may spend nothing on consume=False.
Temporary CP grants (A2GINS7): temporary_cp_granted(engine, recipient, owner, amount, source) is an observational seam called by a plug-in that grants a
  printed Temporary CP to another creature (qiweaving_bond's Feed Current). It
  fires once per granted activation, after the printed spend is recorded, and
  carries the recipient, the granting owner, the amount and the granting source
  so a rider can act on the real grant rather than re-read the talent. It is
  default-inert: with no provider registered it returns an empty list and the
  granting feature is unchanged. It grants nothing by itself; a provider pays
  and records its own rider benefit.
Iron Fist second pass (A2IRONFIST): general_combat_riders supplies opt-in
  standing_burden {extra_ft: nonnegative integer, duration: native clock}.
  It stores one source-owned condition; stand_extra_cost returns the largest
  burden, after ordinary standing reductions. Native posture owns eligibility,
  payment and STOOD_UP events. Absent conditions leave standing unchanged.
  directed_forced_movement carries the ordinary forced_movement row fields.
  A ContextVar scopes forced_movement_direction to the owning engine, source
  and recipient, and restores nested scopes on choices, errors and completion.
  The player chooses a straight horizontal heading with a legal first step;
  heading quotes use the choosing caster's observed occupancy, while native
  execution alone checks actual occupants and records unseen contact.
  automatic users prefer directly away from the caster. Native displacement
  applies defenses, reductions, legal steps, early obstruction and reactions.
  No new engine hook, persistent policy, schema or ability branch is added.
  speed_based_step accepts distance_ft="speed"|"half_speed" and ordinary
  rider_step flags. It quotes current effective walking Speed at resolution,
  then uses rider_step's immediate optional path, separate movement budget and
  scoped opportunity exemptions. No unused credit survives the choice.
  iron_sweeping_kick executes only a failed Shove: Prone branch, including the
  printed minimum-one damage and source-owned preexisting Opening burden.
  Flowing Combination Adept seals flowing_adept in the existing iron_riders
  kit. Only its parent free attempt gets +1 DC; only failure permits the
  optional five-foot target-exempt step. Preexisting-Opening Focus recovery
  applies after either save outcome.
  The parent once-per-actual-turn token controls the Insight too. Old sealed
  actions without these new rows retain their previous mechanics.
  Explicit area recipient selectors retain the printed manual roster. Their
  automatic roster is narrowed to current perception and, for harmful rows,
  enemies; automatic_friendly remains the opt-in for beneficial ally choices.
  Owner area-recipient override data takes precedence over martial defaults.
  Falling Leaf's new sealed recipient_policy=perceived_enemy_auto limits
  automatic secondary recipients to perceived enemies before the choose-N
  checkpoint; both controllers require perception and line of effect from the
  primary target. Manual choices keep their legal printed roster. Its secondary
  save_geometry binds the five-foot radius to the original target rather than
  the caster's own reach. Unstamped historical rows retain their prior path."""
