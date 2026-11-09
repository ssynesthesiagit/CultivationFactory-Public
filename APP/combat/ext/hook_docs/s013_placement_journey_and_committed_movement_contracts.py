"""Placement, journey and committed-movement contracts:
  placement_search_possible(engine, actor, action, root, context) -> False | None
  is a pure, observed-knowledge query after an AI placement sample misses.
  False proves no native square passes the current scoring filter and skips
  exhaustive ranking only; it never removes a legal square, ability or aim.
  None is default-inert. Providers own their ability and impossibility proof.
  committed_teleport_receipt(engine, receipt) -> None is a strict transactional
  notification after native placement, arrival zones and teleport_settled.
  receipt is a flat integer/string movement record with stable receipt_id,
  source/actor identity, original endpoints, distance, turn and willingness.
  Failed, refused and same-square attempts emit no receipt. Providers gate
  ownership and deduplicate by receipt_id; no subscriber means no state edit.

  journey_options(session, actor_id) -> list[option] | None is a pure query for
  owned legal travel actions. auto_select=0 declines automatic use without
  removing the option from explicit selection. None adds no options.
  journey_command(session, actor_id, kind, payload) -> True | None validates
  and applies an owned command inside a revision-checked transaction; None
  leaves it unhandled. Errors abort the cold session before it is saved.
  journey_properties(session, actor_id) -> dict | None is a pure query for
  owned pace, carrying, travel-exhaustion and integer-fraction expiry values.
  Missing keys preserve ordinary travel behavior.
  journey_step(session, actor_id, previous_position, next_position, regions) -> dict | None
  is a pure query for ignore_slowing and supported_kinds terrain lists; it
  never bypasses physical walls. None preserves the ordinary step.
  journey_auto_blocked(session, actor_id) -> True | None is a pure query that
  pauses automatic selection for a pending player decision without spending
  time, movement, resources or a revision. None preserves automatic selection.
  journey_elapsed(session, actor_id, previous_seconds, seconds, moving_ids) -> None
  strictly notifies owned effects at elapsed-time boundaries. Fraction values
  are transient; persist integer numerators/denominators. moving_ids includes
  transported creatures as well as carriers. Absent providers make no edits.
  journey_state_changed(session, actor_id) -> None strictly notifies owned
  effects of combat/incapacitation changes; absent providers make no edits.
  journey_action_completed(session, actor_id, receipt) -> None strictly notifies
  providers after a real mapped Action, its elapsed time, route and motion
  resource receipt. receipt has id, source, economy, movement_cost_ft, position
  and seconds_spent; movement_cost_ft is the charged movement cost (a difficult
  square costs 10 ft for a 5 ft step), not geometric distance. Declaration,
  cancellation and queries never deliver this hook.
  Absent subscribers are inert; an exception aborts the entire atomic save.
  motion.focus_regain_source(rows, resources, economy, source_definition_id)
  is the shared pure Action-only Focus provider used by combat and map completion;
  None grants nothing, otherwise the caller commits one gain with that source.
  map_actions.auto_choice(session, actor_id, allow_declare=True) -> option | None
  is the default LOCAL_AUTO selection policy for mapped basic Actions and
  map_actions.KINDS names the menu kinds it owns. It settles an already
  declared Action (complete while its declaration is still valid, cancel when
  the creature moved or its route is no longer admissible). With
  allow_declare=False it only answers that settlement question, so the caller
  keeps an owned travel action or a player-owned consent prompt first. With
  allow_declare=True and nothing pending it declares Dash or Disengage with no
  route only when completing it would restore a missing Focus through the
  provider above, replacing only plain movement. None keeps ordinary ranked
  travel; manual seats and explicit option ids are unaffected.
  journey_rest(session, actor_id) -> None strictly notifies owned effects of
  a completed Long Rest (eight hours, or Ascetic Body's four hours of meditation
  through JourneySession.complete_long_rest); absent providers make no edits. These notifications
  abort the cold session before saving if a provider raises.
  journey_short_rest(session, actor_id) -> None strictly notifies owned effects of
  a completed one-hour Short Rest (the UNTIL_SHORT_REST boundary); ext.journey_setup
  removes those conditions from the saved encounter snapshot. The expiry name and the rule
  for it live in combat/effect_endings (SHORT_REST_EXPIRY, ends_at_short_rest), shared with
  Gate2Engine.short_rest so a live fight and a saved snapshot end exactly the same rows.
  Native action parameter ai_state_transition=True exempts a legal state-changing
  operation from AI restraint's same-source self-buff recast veto. It does not
  bypass native legality, affordability, knowledge, concentration, zone or
  temporary-HP restraints. Absent/False preserves existing AI behavior. Shield
  Don/Doff uses this because carried/equipped markers share one source while
  each legal operation changes its state; it is not recasting a standing buff.
  The same veto exempts ai_free_preparation: a free preparation precedes a paid
  action rather than duplicating a standing self-buff. Ordinary action economy
  still applies, and candidate_allowed bounds repetition.
  equipped_item_key(default, engine, actor, category, items) -> key | None
  transforms the active equipment identity from owned inventory rows. Providers
  return None to preserve the default. Shield Training selects the wielded Shield
  among multiple owned Shields so AC, disc talents and possession share one key;
  without multiple Shields the seam is inert. It does not equip or transfer items.
  match_initialize(engine) -> True | None strictly initializes explicit setup
  after the full roster exists and before observation, setup tasks or turns.
  True requests first-turn hooks for genesis without event-based turn dispatch;
  None requests no extra delivery. Errors abort creation; absent providers leave
  setup unchanged.
  Detailed journey snapshots and teleport receipt fields are documented below."""
