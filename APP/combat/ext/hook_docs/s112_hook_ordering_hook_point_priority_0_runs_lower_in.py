"""- Hook ordering: @hook(point, priority=0) runs lower integer priorities first,
  retaining registration order for ties. Default priority preserves existing
  subscribers. Use priority=-100 for native landed-zone effects so import order
  cannot offer a movement reaction after a zone already stopped the creature.
- Shared reaction-route checkpoint (combat/ext/rider_movement.py):
  routes(engine, actor, distance, through=(), require_through=False, edge_allowed=None, passage_cost='difficult') -> cell-id
  to Route sequence. checkpoint_step(engine, actor, path, source, distance=None,
  provokes=False, ignore_oa_from=()) -> actual grant feet spent. With no through
  IDs, routes retains legacy grid.reachable paths/pricing, drag, footprint,
  occupied/hostile-difficult cells and the fear-path veto, returning plain paths.
  Through-creature searches and checkpoint_step use native granted_movement
  geometry/resolution. Only checkpoint-dependent
  callers opt in: Empty Cup and Flowing Evasion waive all Opportunity Attacks;
  White Wing exempts only the triggering creature; Reed Slip exempts its chosen
  creature. Ordinary movement allowance is untouched.
  Legacy step(engine, actor, path, source) retains its direct, free,
  non-provoking path traversal for callers that authorize their own geometry
  (including Black Current's through-creature walk), without active-intent
  admission or native repricing.
  Optional through IDs each grant one difficult-terrain crossing, independently.
  Optional passage_cost='free' removes only that creature's surcharge (Empty
  Cup's opposite-side alternative), never terrain/posture/drag costs.
  Route permission is mover/occupant scoped, default-inert outside the helper,
  and restored across nested movement, ControllerPause and errors. Existing
  pass_through(engine, mover, occupant) supplies permission; first
  pass_through_entered(engine, mover, occupant, intent) consumes it without
  consuming again on interior steps; leaving bars re-entry. Queries are pure.
  Optional pure edge_allowed(start, end) prunes the search, never just its final
  shortest path (Flowing Evasion excludes sealed Formation gates).
  Native granted_movement.routes(..., crossing=CrossingConstraint) tracks
  before/inside/after states in the existing grid/flight searches, so a cheaper
  detour never hides required transit; required=False also allows no transit.
  The constraint supplies neither passage permission nor a cost discount.
  Legal endpoints, walls,
  footprints, terrain costs, fear and live step interrupts remain native.
  No persistent permission, condition, new hook or per-ability engine branch.
  Crown consumes the existing movement_step checkpoint at the first qualifying
  willing step; forced displacement and teleports never enter that hook.
- Chosen plug-in paths: engine.move_path(actor, path, source, kind='willing',
  feet=None, intent=None, provokes=True, ignore_oa_from=(), source_actor_id=None)
  runs an adjacent Position sequence inside the caller's accepted transaction.
  Adjacency and forced collision use full altitude-aware volumes. A Route retains
  its selected walk/fly mode; willing paths use that mode's remaining allowance.
  Forced paths share the current activation's per-target interception distance cap.
  'willing' spends ordinary movement (omit feet); 'granted' requires a feet pool
  and leaves ordinary movement unchanged. Both return actual terrain/drag cost,
  honor full-path fear/sight and live Speed/footprints/collisions, and share native
  attempt/landed/OA/zone checkpoints. Existing pass_through permissions authorize
  intermediate creature spaces, never occupied endpoints; interrupted passage
  recovers to a legal space without inflating willing distance. No permission
  is fabricated by this API. Brute Overrun/Ram/Breaker can replace direct movement
  with this call after recording the selected creature's once-only entitlement.
  Flowing Evasion and Patrol can use kind='granted' with their printed OA policy.
  'forced' requires source_actor_id and optionally caps physical distance by feet.
  It first runs normal forced-movement reactions, then, when the caller passes its
  own resolution Context as ctx=..., the moved creature's forced_movement_reduction
  hooks on it -- the same order, scope and restoration typed_executor._push uses
  (ctx.forced_movement_distance_ft holds what the reactions left). combat.movement_paths.
  resolve(..., ctx=<Context>) is that entry point with that argument; engine.move_path
  does not take a Context, and without one no reduction hook runs and the distance is
  unchanged. It never spends ordinary movement, and returns physical distance moved.
  Forced displacement ignores Speed/fear/
  difficult terrain, does not provoke OAs or use voluntary passage permission,
  and still checks live full footprints and legal endpoints at every step.
  forced_movement_attempt(engine, mover, previous, nxt, intent) runs before a step.
  forced_movement_step(engine, mover, previous, nxt, intent) runs after a step.
  Both use the same strict None-or-{stop:True,source_id,label} contract as
  movement_step, before/after the step. movement_steps.context adds forced=True
  and source_id. Typed push/pull shares this executor; area effects resolve before
  landed forced callbacks. No subscribers preserves existing push/pull receipts.
  benefit_suppression.consume_suppressed_conditions(engine, holder, condition_id)
  returns an integer count. One-use effect owners call it after their trigger to
  discard matching backed-up conditions, without restoring them. Poison uses it
  for the next ability check even during penalty suppression. No matching stored
  condition means zero and no state/event change; other suppression is untouched.
  Per-step reactive answers: forced_movement_attempt(engine, mover, previous, nxt, intent) -> None | {"stop": True, "source_id": str, "label": str}, run before each step of a forced move (before leave-reach reactions, payment and entry hazards). A plugin answers for the mover in this step only, may move other creatures off their own turn (Warleader Reactive Position swaps two Commanded allies and stops that push), and owns its consent, costs and records. Default-inert: with no answer the push runs exactly as before, and a declined answer leaves position and step cost unchanged. combat.movement_steps.context(engine, mover).get("forced") is how a subscriber tells a forced step from a voluntary one; a willing path never reaches this hook.
  Caller owns activation/consent and records ability costs normally. Pauses/errors
  unwind the transaction; all actual paths emit MOVEMENT_COMMITTED. Queries and
  unused seams cause no state changes. No plug-in class replacement is needed.
  Strict movement failures use shared CheckpointError and escape enclosing event
  or typed-reaction guards; even a path called by an observational rider rolls
  back its owning transaction. Player pauses retain their original control flow.
- Zone paths: ext/area_steps consumes movement_step(engine, mover, previous, nxt, intent).
  zones.on_step resolves entry, leave, line crossing and named-terrain distance at
  the landed square; damage (including Temporary HP), new immobilization/Prone,
  defeat or displacement ends this path. Native granted paths use the same hook;
  typed pushes call the shared zone query with forced=True. No typed zones is inert.
  The final geometry notification skips duplicate triggers, retaining ordinary
  end-of-move reactions and stealth bookkeeping. Distance counts physical feet
  across actions in one turn, not terrain payment; per-zone once limits persist.
  Last line side and distance/turn counters are integers in the existing recorded
  zone runtime control. All choices share native rollback and replay receipts.
- Granted paths: engine.grant_movement(actor, path, source, feet=..., intent=None,
  provokes=True, ignore_oa_from=()) runs a given adjacent path through native step
- Altitude: Position.z is nonnegative five-foot steps; missing/zero is ground
  and zero is omitted from saved JSON. combat.space supplies 3D volume/distance
  geometry; area cells are drawing projections, spatial_areas owns membership.
  Pure flight(engine, actor) -> capability dict: fly_speed_ft (integer feet),
  fly_speed_bonus_ft (nonnegative integer feet added to an existing Fly Speed
  before percentage restrictions; adds across rows, cannot create flight),
  flight_hover, flight_suspended, flight_disabled, cannot_gain_altitude,
  fly_speed_percent (integer 1-100, the share of the Fly Speed a creature keeps
  while the weight applies; the lowest share any row asks for wins, so two
  halvings still leave half) and fly_speed_zero ("its Fly Speed becomes 0",
  which keeps Hover, suspension and the ability to gain altitude: a creature
  that can Hover stays up, and combat/falling drops one that cannot).
  flight_disabled stays the stronger "it cannot fly or hover at all" reading.
  Native route enumeration also accepts _movement_candidates(movement_grant_ft=)
  for separately granted voluntary movement. This explicit budget replaces both
  walk and flight allowance during the read-only route query; native geometry,
  terrain, fear, hazard, opportunity and traversal legality remain in force.
  Providers
  must own the actor's feature; absent providers preserve ordinary movement.
  The same keys in recorded condition data grant temporary capabilities with
  native expiry. Fly/walk share distance already spent; movement uses native OAs,
  collisions, fear and per-step checkpoints. Non-flying AI receives no jumps.
  Explicit players can select high jumps using Strength and a ten-foot run-up.
  movement_interrupted_sequence is an integer turn flag: changing it with a
  recorded receipt stops the current native move without spending the next step.
  It does not erase future movement allowance (Launching Uppercut's hostile line).
  ext/movement_safety likewise does not veto a later route for a receipt recorded
  after this move's INTENT_ACCEPTED; older receipts do not bypass route safety.
  For unchanged zero-step collisions, movement_safety also omits destinations
  sharing the failed first step recorded in the current turn's receipt. Its
  pure candidate_allowed hook is inert without an owned failure flag; a changed
  mechanical state or next turn permits reconsideration. Gate5's general
  turn_progress.narrow seam additionally checks exact no-op PREPARE bindings
  against unchanged runtime-control COMMIT snapshots, retaining End Turn.
  Gate5 passes its mechanical session's verified records; the guard inspects
  at most 128 trailing records without reading or revalidating the journal.
  An attempt without a preceding snapshot in that window remains eligible.
- Chosen forced destinations (combat/ext/forced_destination.py, used by gravity.py's
  Orbit-Breaking Guard and Weight-Borrowing Throw): routes(engine, mover, feet,
  want=, step_allowed=, goals=) -> {destination: route} enumerates, at the mover's OWN altitude, every
  square within the printed displacement distance whose whole footprint is legal
  under grid.volume_step_legal, breadth-first in the stable row-then-column order.
  ask(...) offers those squares with needle.ask and carries the answer out through
  movement_paths.resolve(kind='forced'), so the target's reactions, reductions and
  per-step checkpoints apply and one MOVEMENT_COMMITTED records the walked route.
  Range is the printed distance in squares: forced displacement spends no walking
  movement, so terrain cost, difficult terrain and the mover's Speed are not read.
  A printed "in any horizontal direction" never changes altitude, so z is preserved
  on both the offer and the move. Callers keep their own checkpoint, choice id,
  prompt and non-square options (also=(id, label, handler)). No legal square = no
  question and no movement.
  Optional step_allowed(previous, next) -> bool constrains every route step before
  visiting it (Water Pull's toward-caster paths); None leaves existing users unchanged.
  feet=None is for printed text that states a DESTINATION and no distance ("Move it to
  a legal space adjacent to you"): goals= is then the whole destination set, only those
  squares are offered, and the search stops as soon as all are found or otherwise runs
  until the reachable space is exhausted, so a far-side arrival needing a longer detour
  is still offered and an unreachable one never appears. adjacent_spaces(engine, who,
  occupant=None) builds that goal set from the engine's own adjacency measure (one
  square, between the two creatures' own volumes) and its own volume_legal test. When an
  occupant is supplied, goal anchors use that occupant's altitude, matching the
  altitude-preserving routes; the 3D distance test still decides whether the space is
  adjacent. This keeps legal arrivals available when chooser and mover start at different
  heights. It
  enumerates candidate anchors around BOTH creatures' real footprints rather than the
  eight offsets of who.position alone, because footprints are anchored top-left and
  extend right and down while the engine measures separation between occupied cell
  sets; a multi-cell creature therefore has legal adjacent arrivals that no offset of
  a single anchor can name. That enumeration is a provable superset and the engine's
  own distance/volume_legal filters remain the only authority, so the offered set is
  widened only by genuinely legal arrivals. With occupant=None the eight in-bounds
  neighbours of who.position are returned, unchanged. A printed Range is a targeting
  limit, never a travel budget for such a move.
- Overlapping zone arrivals: zones.on_moved(engine, mover, start, end, ...) -> None
  snapshots each declared zone's entry/leave membership before running effects.
  If an earlier area displaces the mover, later landing triggers remain eligible
  only while their zone still exists and their membership still applies. Stale
  crossing/moving-through work is skipped; nested movement owns new arrivals.
  Stored areas must retain their active object; map terrain and hook-generated
  areas are re-resolved by zone_id, so fresh projections remain eligible while
  removed or deactivated areas cannot fire a later landing trigger.
  With no typed zones or triggers=False this adds no effects or saved fields.
- Per-turn usage reset retains the legacy once_per_turn:_round_ namespace for
  round checkpoints. Other explicitly per-turn keys reset on every turn start;
  actors without matching keys receive no reset event.
- Landing: strict fall_landed(engine, actor, Fall, intent) -> None runs after
  actual landing, damage and Prone resolution. Fall carries actor_id, distance_ft
  and cause. Providers may offer immediate granted movement using ordinary route
  legality and consent. Pauses/errors unwind the enclosing transaction; no
  subscriber changes no events/state. Partial descents do not call this hook.
- Falling: strict falling(engine, tuple_of_falling_actors, intent) -> None runs
  before a batch descends. It can ask/pay/apply recorded protections; exceptions
  or player pauses unwind the active transaction. The distance each listed
  creature is about to fall is published as engine._fall_plans
  ({actor_id: feet}, transient, restored on unwind; combat.falling.plan_distance
  is the public reader), so a printed trigger that names a minimum drop can ask
  about it before anything moves.
  Strict falling_damage_distance(engine, actor, distance_ft, fall, intent) -> None
  or an int number of feet in [0, distance_ft] runs per falling creature before
  the damage dice are rolled, and the returned distance is what the fall's damage
  is calculated from ("Reduce the fall distance used to calculate fall damage"):
  ordinary defenses then reduce the shorter fall like any other damage. The
  distance actually fallen, and the reported one, are unchanged.
  Composition: every provider is asked about the same distance_ft, from the same
  frozen fall, and their answers combine by the shortest. Each answer is bounded
  by the distance actually fallen, never by an answer already taken, so the
  order abilities register in cannot decide whether a fall resolves; a second
  printed ability using this seam composes with the first instead of raising.
  Strict falling_damage(engine, target, defended_amount, fall, intent) -> None or
  {amount: nonnegative int <= defended_amount, land_prone: bool} runs after ordinary
  defenses/floors, before Temporary HP. Reductions combine by minimum; False
  land_prone prevents landing Prone. Only the scoped falling packet is affected.
  Strict falling_unresolved(engine, actor, intent) -> None runs when a fall cannot
  land at all (no landing space, or a destination a creature now fills), so
  protection paid for that attempt is released instead of outliving it.
  The frozen fall context carries actor_id, distance_ft and cause.
  Generic recorded protection data: fall_speed_ft (positive multiples of five,
  once per round), fall_damage_immune, fall_lands_upright. Featherfall uses these.
  A cushion (Air's Feather-Fall Breath, combat/ext/altitude_abilities.py block
  "altitude_abilities" kind "fall_cushion") instead records reduce_ft and
  lands_upright on the falling creature, spent by that fall: falling_damage_distance
  rolls the distance the reduction leaves (so defenses reduce it), falling_damage
  spends the cushion and land_prone False stands the creature up, and
  falling_unresolved spends a cushion whose fall never landed. Every number of
  either kind (range, reduction or descent rate, how many creatures, whether it
  costs resource, which CL changes it) is read from the feature's own
  combat/rules/feature_blocks.d row, so a second printed ability of either kind is
  a data row; each kind's printed numbers are also that plug-in's code default,
  which is what a fight saved before they moved onto the row still carries.
  No provider/protection gives native capped 1d6/10 ft damage; landing is Prone
  only when final damage before Temporary HP is positive.
  A subscriber that must answer a fall differently from any other packet of the
  same damage type watches the falling source's DAMAGE_ROLLED event, where the
  packet is known to be real before any defense runs (Equipment's Padded Layers
  claims a fall's doubled reduction there). No subscriber means no extra event
  or state.
  combat.falling.displace(engine, actor, steps, source, intent=None,
  settle_after=True) records an explicit vertical forced move with collision
  checks and no movement charge/OA. Ordinary upward movement requires Fly Speed
  or a valid high jump. These helpers store no ability ids in the engine.
- Explicit reaction consumers use typed_reactions.can_use_reaction(engine,
  actor, other_or_None, compiled_row) to share economy/condition/subject/speech
  prohibitions, then open_reaction(engine, row, actor, target_ids, checkpoint)
  after their own consent/payment. Featherfall is the first altitude consumer;
  both helpers retain the normal reaction-use notification and transaction.
- Granted paths: engine.grant_movement(actor, path, source, feet=..., intent=None,
  provokes=True, ignore_oa_from=(), mode=None) runs a given adjacent path through native step
  checkpoints, leave-reach OAs, collision/fear rechecks and entry hazards. It returns
  actual grant feet spent; ordinary movement is untouched. Call only inside an
  accepted transaction. Queries use observed occupancy; hidden contact stops safely.
  The explicit source labels the normal movement receipt. provokes=False exempts
  every reactor; ignore_oa_from exempts named creatures only. Neither exemption
  bypasses other movement restrictions. C16 ext.granted_moves is now an adapter,
  replacing its direct position assignment. Patrol must pass provokes=True and its
  remaining budget, charge the returned cost, then recheck reach/eligibility before
  its attack. Interpose retains its explicit non-provoking default. No caller means
  no new movement/event. Existing native/granted callers preserve their receipts.
  Preserve a granted_movement.Route returned by ext.granted_moves.destinations,
  or pass mode='walk'/'fly' explicitly: height alone cannot identify ground-level
  flight. Validation, cost and resolution use the same selected mode.
  Flight's movement_allowance_adjustment_ft turn flag records the difference
  between actual walking allowance grants and base Speed, at turn start/Dash.
  Later walking Speed changes cannot manufacture or erase flying expenditure.
  A scoped LEAVE_REACH trigger names the actual mover in native and typed consent,
  while keeping the owning action/answer binding. Nested grants restore the outer
  trigger even on pauses/errors; this transient context adds no saved state.
- Voluntary physical paths: combat.voluntary_movement.path_allowed(engine, actor, path)
  is a pure shared query. Every canonical step must not approach a fear source
  visible from that step's starting space, using normal sight/senses and complete
  footprints. Projected viewers are copies; no actor position or observations
  change. Native candidates use it, and native resolution rechecks before and
  after each leave-reach window. Newly acquired fear/visibility safely stops a
  move before the forbidden step, without charging it, with PASSIVE_TRIGGERED.log
  and the normal interrupted MOVEMENT_COMMITTED receipt. No fear preserves bytes.
  Forced displacement/teleports are separate. The old ext.frightened_movement
  module is only a shared-helper import shim, with no candidate filter registered.
  Grant builders should call path_allowed on full paths, not just destinations.
  A grant exempting all hostiles preserves unrelated oa_free_ft protection;
  partial exemptions do not suppress other reactors or waive ordinary rules.
- Committed movement progress (combat/movement_steps.py):
  strict movement_progress_committed(engine, mover, receipt) -> None runs after
  an actual step's position/payment commitment, before movement_landed, entry
  effects and later route reactions. receipt is a read-only primitive mapping:
  actor_id, intent_id (optional), source_id (native willing scope, otherwise None),
  distance_ft (actual geometric step distance, not terrain cost or planned route),
  voluntary, granted, turn_actor_id and own_turn. Forced/dragged landings carry
  voluntary=False even inside a willing mover's enclosing scope. Providers own
  any persisted counters; previews, rejected attempts and teleports do not call
  this seam. Exceptions/player pauses roll back the enclosing transaction and
  its progress. No subscribers means no event, state or cost change.
- Entered-step asset reconciliation:
  strict movement_landed(engine, mover, previous, destination, intent, forced)
  runs immediately after position/payment commit,
  before pass-through notices, typed area entry, map hazards, legacy zones and
  movement_step/forced_movement_step responses. Willing/granted paths and
  forced/dragged landings share this notification. Providers reconcile their own
  carried/attached spatial assets, record updates normally, and return None.
  This is not a reaction window or movement grant. With no providers it is inert;
  exceptions/player pauses roll back the enclosing transaction. Teleports do not
  enter steps and retain their existing committed-event lifecycle.
- Per-step movement: strict movement_step(engine, mover, previous, next, intent)
  runs after paying/entering each native voluntary step, before entry hazards.
  None is inert; {stop: True, source_id, label} ends that move after the step.
  Strict movement_attempt(engine, mover, previous, next, intent) has the same
  reply contract and runs before leave-reach reactions/payment/entry, for rules
  preventing a boundary crossing. Its stop leaves position and step cost unchanged.
  after_move(engine, mover, moved_ft) runs once after a willing move has been recorded
  (combat/motion.py after_move), for any creature, summoned or not, and only when it
  actually moved. Default-inert: no subscriber means no state, no event and no cost change.
  It is the seam for a printed benefit that depends on where its creature now stands --
  a plug-in reconciles its own area-membership effects there, or tells its creature what
  it gained (Death's Court of the Ninth Grave says, once a turn, that a servant standing
  in the Domain crosses Difficult Terrain freely). It does not run for forced displacement
  or teleports.
  Replies appear in MOVEMENT_COMMITTED.interruptions; exceptions/player-choice
  pauses roll back the whole transaction. combat.movement_steps.context(engine, actor)
  exposes, for the creature making this move and only during a step, a read-only mapping
  restored across nesting (all keys default None/empty outside a step; none is stored in
  saved state):
    * travelled_ft -- whole feet of this route covered so far (geometric route length).
    * remaining_ft -- whole feet of this route still to come (geometric route length left).
      Route length ignores terrain cost, dragging and flight, so it is NOT a movement budget.
    * destination -- the route's own chosen endpoint (Position), the square the complete
      canonical path was validated against, so a whole-route rule can answer on the very
      first step; None when the move carries no endpoint.
    * allowance_ft -- the movement allowance in whole feet that ACTUALLY governs this move:
      the mover's remaining ordinary movement in mode, or, when granted is true, the grant's
      own remaining budget (the value the resolver charges, passed to the checkpoint as
      granted_ft). Price a rule against this field, never remaining_ft.
    * mode -- the movement mode in play: 'walk', 'fly' or 'jump'.
    * granted -- True when allowance_ft is a grant's budget rather than the mover's ordinary
      allowance, so a rule can use the grant-aware route builder (granted_movement.routes /
      candidates) instead of the native candidate list, without borrowing movement_remaining_ft.
      Pass the route's mode ("walk"/"fly") to granted_movement.routes so its search matches the mode
      that governs the move: a walking grant must not count an endpoint reachable only by flying.
  A granted candidate from granted_movement.candidates also carries metadata
  ['movement_allowance_ft'] (its grant budget, with ['movement_mode'] when spatial), so a
  candidate_allowed rule can price a granted route against its own grant.
  Consumers must record their resource, condition and Reaction changes normally.
  Native granted movement shares this checkpoint through granted_movement.candidates
  and _resolve_movement(granted_ft=..., ignore_oa_from=...), preserving ordinary
  movement allowance. Forced moves/teleports are separate and do not use this hook.
- Vessel movement: strict vessel_moved(ctx, vessel_zone, previous_position) runs
  after one vessel has completed nonzero walking movement, including Raise and
  group routes. ctx is the owning typed activation; vessel_zone is the specific
  moved vessel at its destination. Return None; no subscribers is inert.
  Consumers recheck that this vessel still has its owner's active control thread.
  Player-choice pauses/errors roll back the enclosing activation.
- Completed-step settlement: strict movement_step_settled(engine, mover, previous, next, intent)
  runs after all visited movement_step subscribers,
  including when one stops the path, before entry hazards. It settles effects
  already owed by the paid step (delayed conditions or distance receipts), without
  creating another movement-triggered reaction or movement grant. Normal defenses
  against the owed effect may pause for a player choice. Return None or the movement_step stop
  reply; every finalizer runs and its stop receipt is retained. No subscribers
  is inert. Distance context and transaction rollback match movement_step.
- Native attack specs report attack_roll_occurred and attack_natural_result for
  that attempt only. A cancelled pre-roll route does not fire roll/outcome riders
  or consume held next-roll benefits. Typed per-attempt mode modifiers are removed
  by their creation IDs; modifiers held before or granted during cancellation
  remain. _add_modifier returns its new ID without changing its recorded event.
- Projectile geometry: pure sight_path(engine, attacker, target) returns None
  or {source_id, label, path:[{x:int,y:int,z?:int},...], ignore_sight?:bool}; two to eight
  in-bounds cells start at the bound effect origin and end at the target. Optional
  z is a nonnegative altitude in grid steps. Routes measure all three dimensions;
  ordinary routes require clear segments at their actual height. Optional
  surface_contacts entries {path_index, cell:{x,y}} name an adjacent opaque cell
  whose face bends the projectile beside that intermediate path point. Its exact
  contact is the midpoint between the waypoint and surface cell centres, at the
  waypoint altitude. The two adjoining segments end/start at that face. Shared
  terrain_occlusion.segment_clear checks actual 3D sight and solid spans, including
  overlapping spans and endpoints; no wall cell is removed or opened. Contact
  must be below the solid wall top and change direction geometrically. All stored
  coordinates remain integers; fractional face endpoints are transient only.
  shot_geometry.contact_path(row) derives the shared exact endpoints for segment
  validation, last-leg cover and route ranking/range/log distance. Travel uses
  the grid's 3D Chebyshev metric and rounds up to an integer foot once after
  summing all exact legs; attack_distance also supplies normal/long-range modes.
  Cover rays/edge crossings accept transient face endpoints without coercing
  them into waypoint centres. Routes without contacts retain centre geometry.
  Without contacts, all opaque terrain retains its normal blocking behavior.
  An explicit ignore_sight route delegates barrier exceptions to its owning rule;
  it does not disclose an unknown/hidden target or change general observations.
  shot_geometry.action(engine,attacker) supplies the scoped activation for providers.
  Native creature candidates measure the entire route for range and bind the chosen
  cells/cover in metadata. Resolution reuses that route and rechecks its geometry.
  Scope restores on nesting/error/choice pause; no actor position is substituted.
  Pure cover_reduction(engine,attacker,target,cover) returns None or nonnegative
  integer cover levels removed (0/half/three-quarters/total); grants add, floored
  at no cover, after ordinary/deep/plugin, declaration/redirection and directional
  cover are combined by final attack defense. None preserves bytes.
  Core and directional shield cover use the last route leg. Accepted routes
  are checked again after declaration/before-attack reactions, before each roll;
  changed endpoints or blocked segments miss with a recorded notice, never a
  straight-shot fallback. Different-source typed effects/attacks clear inherited
  route scope before their callbacks and restore the outer scope afterward.
  Candidate cover receipts precede reactions; ATTACK_ROLLED records final cover. Ordinary visibility queries outside an
  activation retain direct sight. Only source-backed consumers may ignore sight.
- ANY_CREATURE typed actions preserve an explicitly selected self recipient in
  Context.targets/target, including nested saves. SELF buffs keep implicit-actor
  semantics. requires_hearing checks every selected recipient, including self.
- Shared damage-event pipeline: pending_damage.scope captures
  packet intent as explicit source_flags, unioned with the producer's sealed
  typed.damage_source_flags. Names include deliberately_weakened, harmless,
  staged_hazard, cannot_be_consumed, permanent_artifact and
  no_zero_hp_substitution; absent flags make no behavioral change. No consumer
  infers intent from an attack label, its damage, or its owner's team.
  damage_packet_facts uses damage_receipt_facts(engine, target, source_id, source_actor_id)
  to preserve the flags on DAMAGE_COMMITTED for post-resolution consumers.
  Defenses (including Immunity downgrade) precede reaction reductions; final_damage,
  damage_floor and damage_deferral then settle before typed_reactions.on_damage_final.
  That checkpoint chooses one available typed drop-to-zero response and pays
  through the existing consent/resource/Reaction path. It never grants a second
  Reaction or revives a down creature. damage_pipeline.replacement_allowed is
  the shared final-packet gate for instant death and explicit substitution bans.
  Legacy would_drop providers retain their earlier checkpoint and all-provider
  minimum; lethal_damage retains its native gate. Native damage commitment is
  the sole production caller of the typed final checkpoint; standalone on_damage
  retains its numeric-query API. No rows means no choice or cost.
  A temporary damage_immunity_as_resistance modifier preserves Immunity but
  treats its type as Resistance while active. Unlike ordinary Resistance, this
  downgrade cannot be suppressed/ignored; its normal source-turn expiry ends it.
  typed_reactions.downgradable_immunities(engine, target, source_cl) is a pure
  query for eligible types; immunity_cannot_be_downgraded and
  immunity_downgrade_min_cl on defense rows/typed sources are absolute gates.
  Foundation consumers use the existing support_value_bonus/support_value_resolved
  scalar transport, cost_available and native receipt settlement; they do not
  create a second damage packet or reroll reductions.
- Defended lethal damage: lethal_damage(engine, target, remaining_damage, type, source_id, source_actor_id, intent)
  runs after all final_damage reductions and
  floors, before temporary HP absorption. Only a living target still facing zero
  HP is offered. Return None or an integer HP floor within 0..maximum_hp; invalid
  replies fail the transaction. None leaves damage unchanged. Subscribers run in registration order, with
  lethality rechecked after each reply, so a successful rescue prevents another
  payment. A floor never heals or revives. callbacks(point) exposes the same
  stable ordered subscriber tuple for native checkpoints with between-reply
  checks; callers must preserve strict errors and native choice rollback.
- Source-aware native saves: save_mode(engine, target, ability, dc, source_id, roll_context)
  AUTO60 Mageguard contributes Disadvantage only to actual CON Concentration saves while an active owned
  guardian/mageguard row Challenges that bearer within the owner's actual melee reach. Pure query; historical
  rows lacking this new compiled kind and unowned actors contribute nothing.
  returns None, ADVANTAGE, DISADVANTAGE, or a list/tuple of independent
  ADVANTAGE/DISADVANTAGE contributions. The engine retains every contribution
  until it combines the full typed/native mode set; opposing modes cancel once.
  Roll-reason attribution (2026-10-16): a reply may be an attributed dict
  {"mode": ..., "effect": name, "why": plain reason, optional "owner"} so the
  displayed roll reasons name the ability; a bare mode keeps the shared
  generic "Save-specific effect" label. Subscribers that own multiple sources
  must return each contribution so every same-kind source stays stated.
  Subscribers that own multiple sources must return each contribution rather
  than pre-canceling them. No contribution preserves existing mode behavior.
  roll_context carries source_actor_id, named
  conditions and save_modes before cancellation (typed, native and checkpoint
  contributions, copied as a sorted list).
  Native Concentration checks collect concentration.save_modes(engine, actor)
  into that list without canceling: the collector consumes one-use rows and
  applies concentration_mode_removed, then _roll_save cancels once after all
  ordinary/checkpoint/hook contributions. Empty sets add no mode; this general
  seam serves every Concentration source, including opposing independent rows.
  Repeat saves
  carry the original condition's source actor and name, not the repeat caster.
  save_final(ctx, subject, ability, named, failed) runs after stored outcome
  rewrites, before save consequences. Use it for final-outcome riders; after_save
  remains the earlier rewrite checkpoint. save_final is strict and transactional;
  absent consumers leave the result and event stream unchanged.
  At save_final, ctx.save_result is this exact RollRecord (or None for an
  automatic success); ctx.save_effect is the current block_save packet when
  available; ctx.save_dc is its threshold after save modifiers. These are
  transient, so nested rolls cannot impersonate this save.
  C16 consumers: Root-Snare Step stops in movement_step after the current five-foot
  step; Deep Root Holds the Gate asks in movement_attempt before leaving the claim's
  adjacent square. Patrol Zone entry/exit/through tests use each previous/next pair
  in movement_step, including both crossings when the final destination is outside.
  Provider ownership/zone checks, consent, costs, saves and limits remain in riders.
  Native execution rechecks disabling/displacing attempt responses before offering
  leave-reach OAs, and rechecks again after those OAs before charging the step.
- Movement collision: native accepted paths stop at the last legal square when
  occupancy or terrain blocks either the next footprint or a diagonal side
  footprint, including after leave-reach reactions. The blocked step costs no
  movement. TARGETS_OBSERVED records concealed contact even if the blocker became
  located after path acceptance; integer contact cells prevent repeated attempts.
  Shared occupancy remains exempt. PASSIVE_TRIGGERED records a plain stop notice,
  and MOVEMENT_COMMITTED retains actual path, cost and interruption. Candidate
  validation and invalid path/budget errors retain their existing contracts.
  C16 consumers: Root-Snare Step stops in movement_step after the current five-foot
  step; Deep Root Holds the Gate asks in movement_attempt before leaving the claim's
  adjacent square. Patrol Zone entry/exit/through tests use each previous/next pair
  in movement_step, including both crossings when the final destination is outside.
  Provider ownership/zone checks, consent, costs, saves and limits remain in riders.
  Native execution rechecks disabling/displacing attempt responses before offering
  leave-reach OAs, and rechecks again after those OAs before charging the step."""
