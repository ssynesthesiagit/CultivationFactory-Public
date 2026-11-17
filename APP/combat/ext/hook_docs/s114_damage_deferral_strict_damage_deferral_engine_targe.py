"""- Damage deferral: strict damage_deferral(engine, target, packet, intent) returns
  None or an integer amount to defer, from 0 through packet.amount. It runs after
  all final_damage reductions and HP floors combine, before Temporary HP/HP loss.
  Frozen combat.damage_deferral.DamageToCommit carries the remaining amount,
  damage type, source/target identities and confirmed AttackDamage (or None).
  Providers run sequentially and see only the still-unheld damage. Absent owners
  return None; absent providers are inert. Providers own consent, capacity,
  recorded pool/reservation changes, expiry and an explicit exclusion for their
  own payout packets. Do not register a deferral provider under final_damage too.
  Held Harm can switch its existing final_damage provider to this point, return
  the held amount, and retain its pool/choice logic; it must no longer return a
  reduced-amount dictionary. A full pool or zero remaining damage spends nothing.
  Errors and choice pauses propagate to the containing native transaction.
- zones.attack_modes(engine, attacker, target) returns independent obscuration
  Advantage/Disadvantage contributions. Native selective removal reads these
  before final cancellation; mutual concealment cannot erase their provenance.
  With no removal policy, the original combined helper/events remain unchanged.
- Attack mode removal: strict pure attack_mode_removed(engine, attacker, target, ranged)
  returns None or an iterable of supported tokens: ADVANTAGE (all contributions),
  DISADVANTAGE:invisible (target condition), DISADVANTAGE:blinded (attacker
  condition), DISADVANTAGE:obscured (typed zone visibility contribution),
  DISADVANTAGE:prone (only the attacker's outgoing Prone contribution).
  ranged is spec.range_ft is not None for a native roll; direct mode queries
  supply None. Remove contributions before cancellation; never add an opposite
  mode. Stored own/incoming/versus modifiers participate, and checkpoint replies
  cannot reintroduce removed Advantage. Unrelated conditions/modifiers remain.
  Unknown tokens/invalid reply shapes fail the transaction and roll back.
  ATTACK_ROLLED.attack_mode_removed records the applied removal policy when
  nonempty (not a claim every named cause was present). None adds no metadata.
  combat.attack_modes.strike scopes temporary provenance by actor/target/source,
  restored on nesting/error/pause; no saved modifier wire shape changes.
  Providers own eligibility and authority exceptions. An unconditional ADVANTAGE
  token also removes higher-authority sources; conditional rules must not use it
  without satisfying their printed exceptions. No production condition masking
  or early strike-filter workaround is needed by these consumers.
- Fresh CONSCIOUS entry records fresh_zero_hp and initial_damage_excess on
  LIFE_STATE_CHANGED. The shared life-state consumer starts a new failure count
  and applies its ordinary massive-damage threshold (including owned exceptions).
  Positive healing clears the prior count; CONSCIOUS-to-DYING keeps that episode's
  failures. Ordinary life-state events retain their previous payload shape.
- Conscious at zero HP: zero_hp(engine, target, source_id, intent) -> "CONSCIOUS",
  "DYING", "STABLE" or None. Exactly one non-None provider may choose a state;
  invalid/conflicting replies abort the transaction. If none answers, the ordinary
  zero_hp_default(engine, target, source_id, intent) -> "DYING", "STABLE" or None
  fallback runs. The life_state plug-in owns that fallback, so conscious survival
  never applies Unconscious as an incidental side effect.
  CONSCIOUS preserves existing economy/movement and Concentration, without refunds;
  normal turn starts restore economy. It makes no death saving throws, but damage
  at zero still records failures and massive damage may kill. A surviving provider
  must expire its window via public life_state.fall_unconscious, or its own final
  defeat. Healing above zero clears the lifecycle state. Explicit final defeat
  bypasses survival. LIFE_STATE_CHANGED replays the same state; missing old fields
  still mean ordinary active life. Ability costs, consent, durations and exception
  rules belong to the owning plug-in; this lifecycle never silently grants them.
- Native critical range: attack_critical_range(engine, attacker, target, spec) -> int or None.
  Strict pure query, integer 2..20, lowest answer wins; default 20. spec includes
  attack_roll_mode after Advantage/Disadvantage cancellation. The legacy
  critical_range(ctx, target) -> int or None is also queried inside a scoped typed
  strike, before the d20 rewrite checkpoint. The selected threshold and readable
  attack_name are exported by d20_context; current/replacement outcome checks use
  critical_attacks.hits, the same natural-1/expanded-auto-hit policy as resolution.
  Neither query rolls dice or mutates state. Expanded
  criticals automatically hit, as requested by census C15; natural 1 still misses.
  critical_cancel(engine, attacker, target, spec, roll, intent) -> bool or None
  runs only on a confirmed critical hit before any damage dice, through ordinary
  choice transport. First True cancels and stops further providers. False/None
  declines; invalid replies abort. Cancellation preserves the hit but normalizes
  damage and all following critical riders. AttackDamage.critical_cancelled
  preserves that decision through nested damage responses without history scans.
  ATTACK_CRITICAL_RESOLVED records
  changed range/final status by roll id; no extra event for default unchanged hits.
  C15 critical_hits.expanded is now a read-only compatibility adapter; no second
  damage packet. Sword Saint and legacy deferred C15 rows remain deferred pending
  their integrated-weapon eligibility and consumer acceptance matrix.
  SquareGrid.reachable(..., edge_allowed=None) and shortest_path(...,
  edge_allowed=None) accept a pure (previous: Position, next: Position) -> bool
  predicate during search. None preserves legacy costs and tie ordering.
  combat.voluntary_movement.edge_predicate(engine, actor) supplies this for fear,
  or None without fear. Search retains equal-cost and longer allowed alternatives;
  callers must still recheck current restrictions at commit, as native moves do.
- Healing interception: healing_pending(engine, target, amount, healer, source, kind) -> int or None.
  Strict transactional query/reaction checkpoint before a positive HP/Temporary HP
  grant; kind is "hp" or "temp_hp", healer is ActorState or None when unknown,
  source is the granting ability id. Nonnegative integer reductions add up, clamped
  at zero; None declines. Each provider sees the offered amount after stored HP
  reductions, before max-HP/existing-Temporary-HP clamping. Invalid replies or
  player pauses roll back. Zero offers do not trigger. No provider preserves bytes.
  Gate2Engine._heal commits one HP grant after caller-owned stored reductions;
  notify_healed preserves the caller's existing post-heal notification behavior.
  _grant_temp_hp owns the single Temporary HP interception, including typed grants.
  typed_executor.stored_healing_reductions applies existing HP-only penalties.
  C15 _reduced_healing(..., healer=None, source="") combines those with interception
  for old callers committing HP themselves; never pass its result to _heal, which
  would intercept twice. Typed healing, Body Refiner recovery, Return the Living,
  and life_state.heal_to carry exact healer/source through the shared checkpoint.
  life_state keeps its existing condition-removal order before the healing receipt.
  heal_to returns actual HP restored; zero-HP recovery restores turn permissions
  and clears death-save bookkeeping only after positive healing. Denial preserves
  the recovery state and says that no HP was regained.
  run_checkpoint wraps strict provider failures in CheckpointError, which escapes
  enclosing observational/event/reaction dispatchers. Invalid checkpoint replies
  must raise CheckpointError too. Player-pause exceptions retain their identity.
- Completed attacks: strict attack_completed(engine, notice, intent) -> None runs
  after native or portable damage/notifications and all compound riders, or a
  typed attack's full hit/miss riders. It receives the immutable AttackNotice (source,
  attacker and actual redirected target identities, index, hit, melee and kind).
  It cannot change the settled outcome, but may resolve a separately legal attack.
  Subscribers own consent, costs, reach/weapon checks, triggers and use limits.
  Guardian's Reprisal can consume a previously recorded Interpose/Take the Blow
  entitlement here; Sword Sovereign's marked-attacker miss response can also use it.
  Nested attacks do not reopen this checkpoint; a terminal result ends delivery,
  and final-rider callbacks cannot use it to reopen a finished fight. Pauses/errors
  unwind the entire accepted transaction. attack_completion.deferred(engine)
  queues immutable notices until a compound effect completes; nested scopes share
  its queue, pauses/errors discard it, and terminal results suppress delivery.
  attack_completion.can_continue guards native sequences, separate typed attack
  blocks and portable attacks if the attacker is defeated or cannot act; already
  triggered non-attack effects still finish. Normal next-hit reach checks
  still apply. No subscribers means no new state/event. ext.subscribers returns
  a snapshot of callbacks for native dispatchers needing per-provider rechecks;
  dispatchers must propagate errors and validate their hook's return contract.
- Damage response context: strict damage_context_pending_reaction_rank(engine, reactor, row, packet, intent)
  -> None or {allowed: bool, reduction_bonus: nonnegative int}.
  foundations3's owned Heart-Ash provider uses this native query for a single
  paid Cautery reduction with an unspent prior Ash generation receipt.
  prior_event_resources.prior_generated_units is its public pure ledger helper:
  (engine, actor_id, resource_id, producer_id, *, before_sequence, transaction_id)
  -> guaranteed remaining integer credit. It subtracts native spends/expiry and
  grants no credit to initial, unknown, other-source or same-transaction gains;
  native consent, affordability and base payment remain with the caller.
  compile_passives
  seals its owned PB marker; absent ownership/eligible payment it returns None.
  Runs once per owned generic damage-response row, after ordinary defenses and before any
  damage-reaction ranking/consent/numeric query. False eligibility wins; bonuses
  add to flat damage_modifier reductions. Providers must gate on their owned row.
  No provider changes nothing. Exceptions/player pauses unwind the transaction.
  combat.pending_damage.current(engine) exposes frozen amount, damage_type,
  pressure_kind, source/target IDs, hostile/source_wounded flags, source_flags,
  triggering event_sequence/transaction_id, and pre-packet resource balances.
  Nested packets restore context in finally; no packet/cache objects are saved.
  combat.pending_damage.packet_scratch(engine) is the same nesting for per-packet
  bookkeeping: a caller-owned dict, empty for each packet, restored to the enclosing
  packet's on the way out, and never saved (life_state keeps one hit's answered death
  there, so nested damage can neither inherit nor erase it).
  Native _commit_damage accepts explicit pressure_kind/source_flags for actual
  damage packets; it never invents an abstract drain/pressure quantity. A future
  numeric-pressure owner may reuse pending_damage.scope/prepare around its own
  accepted numeric response transaction, without treating that pressure as HP.
  Explicit source_flags include supernatural_attack, willing_cost, unconsumable,
  maximum_hp_loss and anti_farming. Flags describe the delivered source; a name,
  damage type or resource cost does not establish one of those facts.
  save_context.damage_response_state(engine, proposal, source_id) returns a
  caller-namespaced transient dictionary for one resolved recipient/save. Split
  portions share it; other targets, saves and nested deliveries do not. Maw and
  Equipment use it to retain a single accepted reduction budget. It creates no
  saved state, events, payment or choice without an owning consumer.
- Explicit unavoidable HP costs may emit UNAVOIDABLE_DAMAGE_COMMITTED with
  target_ids and integer hp_before, hp_damage and remaining_hp. life_state
  consumes this receipt for ordinary zero-HP/death consequences; damage-triggered
  benefits, Stamina Guard, defenses and Temporary HP do not receive a normal
  DAMAGE_COMMITTED receipt. The producer must own the explicit printed bypass.
- Strict effect_batch_resolved(ctx, first_event_index) -> None runs after a
  successful run_effects batch, including resolved save outcomes, repeated
  effects and persistent zone pulses. first_event_index is the pre-batch length
  of engine.events. Nested batches notify separately, so consumers must consume
  their exact source/recipient instance once and ignore enclosing notifications.
  It observes committed effects and cannot undo hit/save consequences. Pauses
  and errors unwind without settlement. No subscriber adds no state or events.
  This complements paid activation_settlement; it never treats a zone pulse as
  a fresh paid activation. Packet-sensitive resource consumers use the former
  for one triggering instance and the latter for actual activation payments.
- Generic damaged-reaction rows may explicitly set damage_quote_after_consent:
  true. Their existing numeric reduction query then runs after accepted consent,
  the reaction activation guard and successful resource payment. This supports
  rolled reductions with player-owned allocations without asking for allocations
  or drawing reduction dice on a declined reaction. Absent metadata preserves
  historical quote order and event/roll bytes. Consent/payment still use their
  ordinary native checkpoints; pauses unwind the complete intent.
- Retained resource capacity: _set_resource_maximum(actor, pool, maximum, source,
  retain_excess=False) clamps by default. True retains held integer points and a
  resource_round_retained_excess:<pool> bound; spending shrinks that bound and
  gains have zero room above maximum. Native journey_setup may restore
  resource_retained_excess: {pool: held_integer}; genesis requires an existing
  pool, an exact match to its initial value, and a value above its maximum.
  Missing declarations preserve ordinary validation/clamping. This carries
  explicitly retained resources across native cold encounter continuations.
- Cultivation caps and suppression use one owner: the cultivation_limit effect (cl_cap
  or element) and cultivation_access.effective_cl(engine, actor, printed_cl). The
  Maw's complete Body Refining suppression is the complete_body_suppression effect.
  While that condition lasts, the suppressed Body's own features and states are
  unavailable: the Maw answers no reaction, stores no new Essence and offers none
  of its actions, and its state ends when the suppression is applied.
- Native state effect metadata: state(ctx, row) accepts optional effect_kind
  (ward, barrier, transformation, aura, stance or damage_reduction). It persists
  rule.effect_kind on the created condition for ordinary source-qualified ending
  and suppression consumers. An unknown kind is rejected; absent metadata
  introduces no classification or behavior. A duration or display name alone
  never classifies an effect. The Maw's minute transformation declares its own
  kind and keeps it when restored from a native journey.
- Temporary HP lifetime capture: every native temp_hp row with an explicit
  duration/expiry is captured into temp_hp_grants' exact accepted-grant clock
  in every fight (its printed duration is a rule of the row; there is no
  opt-in hook). Actual accepted TEMP_HP_GRANTED receipts identify the pool; rejected
  offers never replace its identity. The clock uses ordinary native condition
  expiry and clears only its own still-held grant when it ends. Public
  lifetime_for(actor, grant_sequence) returns that marker or None;
  rebind_lifetime(engine, actor, marker, after_sequence=...) preserves the
  original deadline after a suppressed pool is successfully restored, without
  binding an older/rejected or unrelated offer.
- Ordered line rows may opt into scoped_origin: true. The existing
  piercing_area effect then uses action_geometry.point(engine, actor) for its
  shape, nearest-first ordering and live obstruction checks. Absent metadata
  keeps the physical actor origin. This consumes a previously validated
  effect_origins record and grants no new origin or perception permission.
  damage packets; it never invents an abstract drain/pressure quantity.
- Strict scalar_pressure_pending(engine, packet, intent) -> None or a primitive
  receipt with actor_id, source_id, reduction (nonnegative integer), resource_id,
  resource_spent (nonnegative integer), reaction_spent (boolean). One receipt per
  actor; providers own eligibility, consent and actual payment. Public frozen
  combat.scalar_pressure.ScalarPressure carries source/recipient/value/cause,
  intent/event/instance identity, public source flags, hostility/wounded flags and
  pre-value resource balances. Private/self-cost/overdraw/hidden-injury/backlash
  flags bypass this public response seam.
  scalar_pressure.settle returns the actual reduced integer consumed by typed
  resource loss and numeric healing-penalty application. Zero, absent source/cause,
  boolean healing denial and percentages never become pressure points. No provider
  means no event/cost/value change; strict pauses/errors roll back the parent
  transaction. Nested packets are independent; only primitive receipts persist.
  Damage finalization and pending_damage remain separate.
- Strict post_hit_damage(engine, attacker, target, settled_hit, intent) -> None
  runs once after a confirmed hit's primary damage, before legacy notifications,
  including typed and damage-less hits. Frozen settled_hit holds AttackDamage,
  damage_type and resource_before(actor_id, resource_id), captured before the
  attack begins. Consumers own eligibility, player choice, payment, extra damage
  and post-damage thresholds. No consumer adds events/costs. Exceptions and pauses
  roll back the parent attack. Old after_hit notifications remain unchanged.
- Observed targeting: combat/target_knowledge.py knowledge(engine, viewer, target,
  action) is a pure query returning DIRECT/current position, LAST_OBSERVED/a saved
  square, or None. Remembered creature attacks bind LegalCandidate.destination and
  target_knowledge metadata; normal intent destination/staleness checks still apply.
  No actor is moved or substituted to resolve the aim. An empty remembered square
  consumes the ordinary cost/action, emits ATTACK_LOCATION_MISSED, and applies no
  absent-recipient effects or defender reactions. Typed execution keeps explicit
  self effects and attack-use flags (opens/uses/marks_used and Pair outcome identity).
  Its transient Context.missed_target_ids carries only the bound identities; targets
  and target contain no absent creature. Native and typed attack checkpoints also
  recheck the accepted aim after reactions. The owner's 2026-10-06 targeting
  rule supersedes requires_seen_target for attack rolls: a known square is
  attackable with line of effect, existing Disadvantage and the fight's optional
  positive concealment percentage. Non-attack creature
  effects require sight and effect. Range and area recipient resolution remain
  unchanged; area origins require line of effect.
  Creation and committed transactions record positions per side in the existing
  final event's observations_after payload (TARGETS_OBSERVED for contact or when a
  transaction has no event). Normal event numbers and candidate bindings stay stable;
  reads never create observations. Old state defaults to no remembered locations.
  target_observation_refresh(engine) -> None or bool: a pure opt-in to persist
  currently perceived positions even when their coordinates are unchanged.
  None/default retains coordinate deduplication; False vetoes True. Only committed
  observation checkpoints call it, never context/menu reads. ai_search_policy
  enables freshness only for stamped fights, using existing integer position
  payloads and event sequences without revealing hidden paths or adding state.
  Contact during a blocked step may locate an unseen creature. Execution records
  the actual overlapping occupied cells as integer-only unseen_contact_cells in
  the mover's turn flags. Candidate occupancy excludes those cells until turn reset;
  it does not infer the rest of a concealed footprint. Older anchor-only receipts
  remain readable and acquire contacted cells on the next collision. Observed movement
  endpoints record their observing sides; controller history omits hidden movement,
  paths and embedded reducer state. The authoritative journal is preserved.
- Limited remote origins and destination safety (SOLSYS-SPACE1):
  effect_origins records may carry attack_limit: positive int. The activation
  shares a resolution-local strike budget across nested blocks of the same
  source. action_geometry.commit_usage seals the limited origin snapshot at
  an actual attack roll or entered touch effect before its grant is consumed;
  activate(..., action=ActionDefinition) also supports ephemeral reaction
  definitions absent from the primary catalog, restoring them on scope exit.
  Folded Reach's effect_resolution_scope offers the same point choice for a
  reaction/granted attack without extending its physical trigger reach.
  Attached non-attack effects retain the snapshot; attack(..., new_strike=True)
  resets a nested attack to physical geometry after the limited origin is used.
  Independent nested attacks cannot reuse its spent condition. Per-strike
  outcome data lives on Context.strike_record, not an inheritable hit cache.
  No limit leaves ordinary anchor revalidation intact.
  action_geometry.finish_attack spends one after attached hit/miss
  effects and before completion reactions; exhausted origins use physical
  geometry for later strikes. Other-source nested attacks own separate scopes.
  No limit leaves existing remote origins unchanged. Folded Reach supplies
  visible point origins, normal range/cover, and consumes its condition after
  the qualifying use; Folded Weapon Line seals its next-strike hit/miss effects.
  reveal_attack_direction is a generic typed effect: store only the signed
  compass direction of this attack for its target, with a readable historical
  knowledge condition. It never reveals an unseen creature's position.
  Save-branch Contexts now retain save_result and save_dc from the exact settled
  parent save (including modifiers), not the last unrelated journal roll.
  subject_repositioning reads unsafe_on_failure_margin: positive int on a
  destination_must_be_safe row: only a failed save meeting that margin admits
  immediate damage hazards. unsafe_destination_requires_gm additionally asks
  for the printed GM's permitted hazard squares through needle.ask's existing
  gm_adjudication transport (default: none). This is a terrain permission, not
  confirmation of a chosen move: the owner then chooses among every safe and
  approved landing. compile_action opts these rows into the GM preview.
  No field retains safe-only destination selection.
  Unowned Folded Reach grants no origin; remote points are not extra AI senses.
- Remote activation origins: effect_origins(engine, actor, action) -> None or list
  of {id, label, position:{x,y,z?}}. Pure providers validate current ownership and
  anchor eligibility using physical caster geometry. IDs must be unique and cells
  integer/in bounds, with optional nonnegative z in grid steps. No records =
  byte-identical ordinary candidates and events.
  Each origin creates a separate candidate; metadata and candidate identity bind
  its ID/cell/label. Range, effect LOS/cover and typed line/cone geometry use the
  chosen point. Physical position, movement, auras and reaction reach stay put.
  Execution records the choice, revalidates the anchor and restores scoped geometry
  on pause/error. Anchor validation runs after reactions even when no checkpoint
  returns a result. Nested typed effects and attacks from another actor/source
  get their own geometry for the entire execution, including reach, declaration,
  cover and callbacks, then restore the outer origin. No origin preserves physical
  geometry and emits no additional events.
  action_geometry.py is the shared engine contract; remote_origins.py supplies
  Marked Origin and Flow Line Strike. Generic riders can add providers without
  changing engine geometry. Missing/moved/destroyed anchors invalidate the choice.
  Formation Thread Relay uses the same provider: new owned Pulses seal
  formation_relay_techniques=1 and journal techniques=1 on the ally's grant.
  That grant permits a non-Secret sphere technique as well as a Cultivation
  Attack, once before the owner's next turn. Physical caster perception is
  checked for creatures and aimed squares. Historical grants stay attack-only;
  without an owned grant this provider adds nothing. Formation Maze similarly
  seals formation_maze_map_anchors=1 in new array numbers to offer perceived
  map doors/gates, preserving historical arrays' anchor choices.
  Echo Step validates its bounded in-action origin through this same contract;
  its provider is inert during menu generation and does not move the caster.
- Activation interception: technique_declared(engine, user, action, candidate, intent)
  returns None or a dict with source_id and readable label, plus cancel (bool),
  spend_activation (bool; default false), range_delta_ft/area_delta_ft (nonpositive
  integers), forced_cap_ft/movement_cap_ft/damage_roll_reduction (nonnegative integers), and/or
  retarget_id (a legal single-creature recipient). Runs strictly inside the native
  transaction before Action/Bonus Action or complete generic-reaction payment.
  Reactions supply their real source, effects, weapon delivery, range and costs;
  the caller retains payment ownership, including explicit spend-on-cancellation.
  Reaction availability and affordability are rechecked after intervening choices.
  Generic reactions cannot redirect precomputed protection effects; such a reply
  fails strictly instead of partially redirecting. Reaction choices can pause an
  API-controlled turn for a different manual player. Declaration errors propagate
  through generic row adapters to native rollback, rather than becoming GM riders.
  Replies are recorded with the accepted candidate ID. Range/area changes floor at
  touch/5 feet; forced distance and the first damage roll are limited only for this
  activation. movement_cap_ft is a per-recipient budget shared by native typed
  pushes/pulls, movement grants, reaction steps and teleports. Only actual distance
  or grants consume it; multiple rows cannot reset it. A teleport destination
  outside the remaining budget fails visibly without silently choosing another
  square. Custom plug-in movement and moved objects remain a stated GM boundary;
  consumers must use movement_distance/movement_committed to opt in. Retargeting
  never mutates the original catalog or accepted intent.
  Multiple subscribers compose in registration order. Cancellation defaults to no
  activation payment and skips completion callbacks; spend_activation opts into
  losing those costs. Independent direct attacks use the same checkpoint before
  rolling; their callers own any Reaction payment already made. No replies leaves
  ordinary event/state bytes unchanged. Scope restores on pause/error/nesting.
  Speech-Knot Point and Heaven-Sealing Ice Script consume this seam. Delayed or
  split activations require separate persisted scheduling; this reply does not
  invent such a schedule.
  named_ability(action) resolves explicit typed source/immortal_from/forged_from
  references against authority records; unknown sources and ordinary weapons do
  not qualify. Cost and weapon delivery never determine this provenance. Generic
  Immortal Art reactions retain their originating record when compiled; older
  rows without a recorded origin remain unknown rather than inferred by name.
- Creature kinds: ext/creature_kinds.py reuses C12's explicit persisted labels.
  matches(actor, kinds), is_unclean(actor), and labels(actor) never infer a kind
  from a name, condition or immunity. Unknown labels do not match. Unclean expands
  only to the printed Undead/Demon/Fiend/Corrupted Spirit/Possession Entity labels.
  if_creature_kind narrows nested effects. C12's unrelated exclusion rows remain
  on that rider lane; this port supplies the shared classification and bonuses.
  damage_roll_bonus(ctx, effect, kinds) and attack_damage_bonus(ctx, target, effect)
  return integer additions to a real damage roll (None = unchanged). Ordinary
  fixed damage and shared multi-target rolls receive no kind bonus. Attack limits
  are consumed only after actual HP or temporary-HP damage, with a recorded log.
  Typed save rows may declare disadvantage_if_kind; the normal save-mode merger
  combines it with other Advantage/Disadvantage. Missing fields preserve behavior.
- Public roster availability: combat/roster_selection.py filters new-fight catalogs,
  practice setups, token selection and team presets. Historical match loading uses
  its bound roster; it never consults this selection filter. Retired presets are
  hidden on read without rewriting their stored file. New requests naming a retired
  fighter fail before genesis. Qi Armor numbers come from the typed owner record via
  combat/typed_numbers.py; stored portable/Factory bundles retain their own numbers.
- Flat reaction reduction budgets: combat/ext/attack_reduction.remember(engine,
  target, pending, reduced, amounts) retains already rolled surplus only after
  consent/payment. amounts contains (integer, allowed uppercase types); empty
  types permits all. carry(engine, target, pending) consumes the same confirmed
  AttackDamage roll's remaining portions before new damage responses. Both are
  inert without a positive supplied budget and explicit attack provenance.
  Self/ally generic reactions, parked hit guards, damage_reduction and damage_soak
  use this shared seam; final attack_damage_final removes its primitive state.
  Non-attack damage, nested packets without attack provenance and other rolls
  never borrow the budget. Permanent flat defenses remain per-packet defenses.
  An optional feature string tags a portion for effect-wide accounting. used()
  lets the owner avoid regranting its budget on later packets. Native paid numeric
  DAMAGE_APPLICATION reaction receipts use the same helper via event/final_damage.
  park(target, attacker_id, integer_reduction, feature_id, engine=engine) stores
  paid pre-damage self/ally hit guards until rolled damage binds the confirmed
  attack. Runtime callers pass engine to retain the accepted guard's transient
  relocation owner; the optional argument preserves pure fixture callers.
  Delayed hit_reduced/hit_absorbed consumers use follow_up_scope(engine, target,
  attacker_id, exact_feature_id) around that guard's aftermath. Aggregate reducer
  lists may contain several independent owners, so each consumer selects its
  exact originating feature. Missing receipts are unowned. Surplus portions
  retain their exact original owner through reaction_reduction_carried callbacks,
  including later packets. No ownership receipt is stored in actor flags.
  An optional
  delivery='interceptable_weapon' in remember limits a budget to represented ranged
  physical weapon packets; a separate after-impact effect cannot borrow it.
- Per-creature use limits: a printed "Use Limit: Once per <rest> per creature" (or "per target", in either word
  order) is one use *per creature*, not one use for the whole ability. combat/ext/target_limits.py is the single
  model: it widens the ability's use counter to PER_TARGET_USES at compile time so the count never runs out, keeps
  the real limit as a list of the creatures used on in a condition:typed.target_uses on the user, offers the action
  again for a different creature (candidate_allowed) and refuses the creature it was already used on. The refusal
  the player reads is a plain sentence naming the creature, the ability and the rest it recharges on, read from the
  printed "Use Limit" line (printed_limit/recharge_label/recharge_for; a fight is shorter than a rest, so the
  record lasts the fight, as printed). note_use(..., subject) records a use for a plug-in whose limit is not an
  action cost. A limit naming no creature stays one use for the whole ability; the ledger only records uses made
  through an Action, so a Reaction or passive per-creature limit is recorded in the data but not yet gated -- a
  99-wide counter nothing records would be unlimited, which is why the widening is not applied to those rows.
- Initiative choices: pure fight_setup_tasks(engine) returns None or a list of
  {actor_id, source_id} tasks owned by that actor. Unowned tasks are ignored;
  duplicates are errors. New fights seal these tasks after initiative, before
  ROUND_STARTED/TURN_STARTED. No tasks preserves the old events and state bytes.
  Factory setup-task providers can read participant_control_modes from the saved
  roster setup; only manual modes queue Ask-me work, while missing legacy modes
  default to manual.
  The only candidate while tasks remain is "Finish fight setup"; it costs no
  action/reaction and invokes strict fight_setup(engine, actor, source_id, intent).
  Exactly one owning consumer must return True per task (including a permitted
  decline); others return None. Missing handlers fail without losing the save.
  Consumers use choice_checkpoints.dynamic_choice for legal placements/options,
  with readable labels, stable distinct checkpoints, and explicit AI preferences.
  Manual owners are asked even on an AI first turn. Choices/effects share one
  native transaction: a pause/error restores all placements, rolls and events.
  Generic Ask-me reactions triggered by Initiative use this same setup queue before
  turn one; the owning consumer resolves the ordinary Initiative checkpoint transactionally.
  Only after all tasks finish does FIGHT_SETUP_COMPLETED clear the saved tasks
  and begin round/turn one. No ordinary action riders run for this system step.
  Persisted empty/legacy tasks never backfill during loading. Constructor task
  discovery is pure; interactive effects must never run in match_start/init.
  Beast Aspects uses these same public hooks for Chimera's three distinct
  Initiative selections, before any creature's first turn.
  relations.genuinely_opposing(engine, actor, other) -> bool is the public
  scene-evidence query for triggers that exclude staged hostility. It requires
  current ENEMY allegiance and explicit GENUINE evidence; absent evidence is
  UNKNOWN and grants nothing. The owner/GM-only change_relations service accepts
  SCENE_OPPOSITION with two actor IDs and opposition=GENUINE/STAGED/UNKNOWN.
  This validated, symmetric per-fight fact is journaled/replayed independently
  of side changes. Empty evidence leaves legacy serialization unchanged.
- Shortfall payment: pure payment_shortfall(engine, actor, technique_source_id,
  effective_cost_totals, missing_totals) returns None or frozen PaymentAlternative
  from combat.alternative_payments. Read-only totals include cost floors; a plan
  must cover exactly the missing resources with positive HP/other-resource costs.
  Its source must be owned via actor action/reaction/passive/augment IDs or compiled
  feature rows. Consumers gate their rate, limits and eligibility; unowned plans
  cannot unlock actions. Affordable actions never query or change payment. Native
  menu and execution share this quote; execution rechecks it, asks the acting player
  through the existing choice transport (AI chooses the first viable plan), and
  commits actual resource spending plus ALTERNATIVE_PAYMENT_COMMITTED. HP costs
  preserve the declared minimum (at least1) and are not damage or resource gains.
  Strict payment_shortfall_paid(engine, actor, technique_source_id, plan, intent)
  runs once inside the same transaction for owning usage bookkeeping. All effects,
  economy, events and rolls roll back on pause/error/decline. Declining cancels the
  attempted technique with a readable retry diagnostic. No provider means no silent
  payment. Plans are transient; only primitive receipts enter the journal/reducer.
  The shared refund helper caps later discounts by the receipt's actual resource
  spending, so replacing CP with HP cannot manufacture CP through a refund.
- Voluntary substitution: payment_substitution(engine, actor, technique_source_id, effective_cost_totals, missing_totals)
  has the same pure, owned PaymentAlternative contract as payment_shortfall, but may
  replace additional points of the listed cost even when fully affordable. Coverage
  must be positive, no larger than the actual cost, and cover every missing resource.
  This opt-in hook does not change when payment_shortfall is queried. A consumer
  must require the owner's explicit setting/eligibility; no reply leaves ordinary
  payment untouched. The shared native choice, atomic receipt, HP minimum, re-quote,
  refund cap and payment_shortfall_paid callback apply to both kinds of plan.
  Decline cancels the attempt without spending; a setting can be turned off to pay
  normally. Crimson Sacrifice uses this seam to replace the previous spend/refund
  workaround while retaining voluntary substitution when CP is already available.
- Creature types: ActorTemplate/ActorState.creature_types holds an immutable tuple
  of explicit printed labels. Factory identity, portable CombatantStats and summon
  stat-block creature_type/creature_types fields supply it when creating a new
  bundle. combat.creature_types.types_for(actor) returns the tuple; has_type(actor,
  label) tests a case-insensitive exact label. Unknown is (). No race, name,
  condition or immunity implies a type or an Unclean classification. Empty tuples
  are omitted from serialization; loading an old bundle never backfills current
  labels. Persisted labels survive snapshots/replays, and no hook or gameplay rule
  runs merely because a label exists. New explicit labels intentionally change
  new bundle/state commitments; old unlabeled bundles retain their exact shape.
- Void Needle's void_pressure effect consumes one shared pressure per turn across
  its existing preselected options; a miss consumes none. Its Cost Lock condition
  expires at the start of its source's next turn and uses technique_cost_floor
  for both native payments and public plug-in quotes/refunds. Cost-Denying Needle
  is a manual reminder until resource-gain provenance distinguishes ordinary
  temporary recovery from permanent features; it must not use no_cp_regain.
  No owning effect/condition changes ordinary technique payment or resource gain;
  no engine method is wrapped.
- Native transaction rollback: ControllerPause and its subclasses restore the
  transaction's state, event history, roll history and deterministic counter,
  then re-raise the exact original pause. Ordinary Exception rollback is
  unchanged. Other BaseException signals are not intercepted. Preview clones
  use their own native transaction snapshots; no runtime wrapper is required.
- Native movement availability: effective Speed0 offers no ordinary movement,
  even if an effect grants a positive remaining allowance. The same speed query
  already used during execution covers condition rules, modifiers and life state.
  This does not change forced movement or restore/spend the allowance; once the
  restriction ends, ordinary movement becomes available again. Positive-Speed
  candidate geometry, costs and event bytes are unchanged.
- Native movement revalidation: after leave-reach reactions, Gate2 rechecks
  active/life/speed, displacement, newly Prone conditions, full-footprint path
  legality, current terrain/drag cost and remaining budget before charging a
  step. An invalidated path stops at the last committed cell and emits the
  existing MOVEMENT_COMMITTED interrupted record; it does not charge the old
  step. Hazard/zone incapacitation also stops subsequent steps. Unchanged
  movement retains its exact path, costs, event order and serialization.
- Movement record contract (general, no ability id): a MOVEMENT_COMMITTED payload
  says in its own flags whether the mover walked by its own choice, and readers
  key only on those flags. ``forced``/``teleport`` true mean "moved against its
  will" (a push, drag, placement or jump) and a named terrain reads them as
  involuntary: the creature enters the ground it lands in but its travel does not
  count towards a "moving more than N feet through" distance (combat/zones.py
  _movement_distance_through_zone). Anything else is a voluntary walk and counts,
  however it was delivered. ``path`` is the whole route the mover actually
  stood on, as integer ``{x, y}`` squares -- never just the two ends -- so
  per-square and cumulative rules read the real walk; a producer that relocates a
  creature it did not itself move (a mount carried by its rider, a rider carried
  by its mount, a mount's controlled charge) records the mover's route translated
  onto the carried creature's own squares, and inherits the mover's ``forced``,
  so a mounted pair cannot disagree about the same travel (mounts.py
  ``_carried_route``). ``carried_by`` names who carried the creature and is
  provenance for the carrier's own suppression of re-processing; it does not mean
  involuntary. Consumers must use these flags rather than re-deriving intent from
  ids or abilities, and producers must not invent a fourth meaning for them.
- Native radius geometry: SquareGrid.cells_in_radius(center, radius_cells) and
  cells_in_radius_of_cells(centers, radius_cells) return the original row-major
  Chebyshev union clipped to map bounds, including empty/negative radii. The
  shared radius_geometry cache keys bounds, center set and radius only; frozen
  Positions are reused across engines. Terrain/actors never affect this query.
  Limits are 4096 entries, 524288 retained cells and 64 centers per cached key;
  cold queries enumerate the clipped square union in row-major order, without
  scanning uncovered cells. Larger center sets use the same geometry without
  retaining their keys. A separate 16384-entry coordinate cache shares frozen
  Positions across overlapping cold keys. Custom grid overrides still dispatch
  normally. No provider registration, event, random draw or saved state changes.
- Terminal summary verification: an already loaded session is verified directly.
  The ordinary summary reuses strict verification's full journal replay for its
  replay status, state hash and terminal result; it does not replay twice or trust
  cached PASS flags. Reaction audit rows use the verified genesis/committed journal
  documents, including replay enrichment, for every ability: a just-committed
  session's raw last-action events must not change summary bytes on reload.
  Stored-summary corruption checks remain strict. The sealed
  historical summary keeps its original dedicated validation path.
- API-controlled actions preserve the provider's checked payload/token, rationale
  and state hash in match-local pending metadata while player reactions are asked.
  provider_step/auto_step and ai_execute accept reaction answers; the table uses
  its existing Use/Decline transport. Sequential answers survive restart, and
  resuming a pending choice needs no provider call or available provider. A stale
  state or wrong checkpoint cannot consume an answer. Commit clears the pending
  record and writes one provider audit receipt. No pending player choice leaves
  ordinary automatic resolution unchanged; no new mechanical event is introduced.
- Weapon delivery: a plug-in attaching typed.weapon sets typed.weapon_source_id to
  the base compiled weapon action ID; compiler-delivered techniques use
  typed.delivered_by. Opportunity attacks follow typed.opportunity_of through the
  action catalog, including a base technique's delivery metadata. weapon_identity
  normalizes a weapon's attack modes to the base ID and guards against catalog cycles:
  physical_weapon_id(source, parameters) is that one shared normalization (#off-hand copies
  and extended-reach variants are the same object), and it is default-inert -- an action that
  is not a mode of another is returned unchanged.
  Deferred bonuses optionally bind to that ID
  through Context.damage_cache['_on_hit_weapon_id']; absent binding preserves legacy
  eligibility. combat/ext/weapon_hits.py supplies the shared classification query.
  Its public available_weapons(engine, actor, words=()) returns base IDs mapped
  to weapon actions after Gate2's dropped/disarmed and borrowed held_by gates,
  independent of attack economy/range. Selection, weapon-required effects and
  weapon-bound bonuses share this query; unbound bonuses are unchanged.
- Deferred once-per-turn damage uses a persistent _round_typed_on_hit flag keyed
  by source/effect and valued by actual round/slot/actor/turn counter; refreshing
  the modifier cannot grant another use in the same turn. deferred_hit_state's
  event hook migrates legacy typed_on_hit:<modifier_id> spending on the first
  event after reload, before hit resolution/refresh/turn advancement. Only live
  legacy deferred modifiers opt in; the resulting string survives commit/reload.
  The counter is the current actor's turn identity, which can move while one
  resolution is still running (a reaction granting an isolated turn, or an
  initiative slot advance between two damage components of one hit), so
  typed_executor._moment_scope additionally spends such a rider once per target
  per moment: the outermost run_effects opens a transient _typed_moment set and
  the rider records (actor, key, target) when it fires. Records are keyed by the
  owner that spent them, so one fighter's rider never withholds another's; the set
  itself is per engine and shared, so a nested resolution (a reaction inside an
  action) joins the moment already in flight rather than opening a second one.
  Outside a moment nothing changes; the record is never stored in a saved fight.
- extra_targets (combat/ext/extra_targets.py) offers additional creatures for a clause like "another
  creature within 10 feet of the target": it takes {"count", "who", "sight", "range_ft",
  "within_ft_of_first", "range_from_user", "area_only", "prefer", "effects"}. Each chosen creature
  receives the nested effects and so saves for itself. Two general options measure the extra creature
  against the already-aimed creature rather than the user: "within_ft_of_first": n requires a chosen
  creature to stand within n feet of it and never to be it, and "range_from_user": false drops the
  user-distance test for that row (the aimed-creature distance is then the only bound). A row that sets
  neither behaves exactly as before. Both are inert for characters that do not own the row.
  Optional choice_name and choice_prompt provide display-only ability identity and consequence;
  choice_prompt accepts {actor}, {action}, and {first} display names. Absent metadata preserves
  existing prompts and selection/payment. shi_pp_apply_numbing reuses the owned Numbing Point
  leaves and shared shi_pressure_points.deliver_point helper; choice_reactors advertises only
  owners of new sealed Point rows carrying that effect, including during an enemy AI turn.
  Optional requires_perception checks the user's perception and grid line of sight (including
  solid cover) to each extra recipient; it does not require the recipient to see the user.
  Absent this option, the existing sight contract and target pool are unchanged.
  Optional prefer="hostile_or_decline" selects an eligible enemy automatically or declines
  when none exists; manual users can still select any eligible creature. Existing defaults
  remain unchanged for rows without this preference.
- limit_concentration_duration is an opt-in effect (also applied by technique_used
  for new bundles with a sealed unlimited concentration contract), using the existing event and
  turn hooks: record the duration slot deadline for the current concentration
  copy, end that copy when due, and discard the deadline on early loss. Missing
  effect rows and no sealed opt-in leave legacy concentration behavior unchanged.
- Persistence reuses its freshly generated legal candidates only inside one execute_intent acceptance, guarded by
  the complete state hash and consumed once. A preview clone still generates its own candidates and syncs its walls.
  Do not retain candidate batches across state/terrain mutations; public intent binding and stale checks still apply.
- Grid shortest_path/reachable keep all cheapest predecessors and reconstruct nearest the start-to-goal line
  (ties: continue the segment, then coordinates). Plugins using paths inherit this deterministic tie-break;
  minimum costs, legal endpoints, footprint/corner checks and difficult terrain remain authoritative.
- Deterministic: a saved fight is replayed from its events. Change state only through the engine's own evented methods
  (_apply_condition, _remove_condition, _gain_resource, _spend_resource, _commit_damage, _append_event, run_effects) or turn
  flags (restored on reload; a key containing "_round_" survives the turn reset). Never mutate a condition's data in place.
- Key everything off the character's own compiled rows (a "block" in combat/rules/feature_blocks.d/*.json, compiled through
  the compile_block hook) or its actions, so other characters and fights saved before are unaffected.
- A failing hook must not end a fight: exceptions are caught and logged as a GM line. The one exception is a
  ControllerPause (below): the fight stopping to ask the player for a reaction is not a failure, so ``run`` and the generic
  reaction rows in typed_reactions.py let it through untouched.
- Defense data may combine requires_condition with attack_kinds to grant temporary resistance only to the listed
  attack kinds (weapon, unarmed, other). Empty attack_kinds retains the existing unrestricted defense behaviour."""
