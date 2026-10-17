"""
Failed-save recipient choice effects (A2SWORD):
  remember_failed_save_recipient {key} in on_fail collects actual recipients
  in the activation-local Context cache. choose_failed_save_recipient {key,
  name, effects} after the save asks its owner for exactly one living failed
  recipient, then resolves effects with only that subject. No failures means
  no prompt. AI options require current perceived location. Receipts do not
  persist or leak between activations; Needle owns pause/retry and transaction
  rollback. Existing saved rows without either effect are inert.
  Sword's Fatal Strike uses the existing pure hit_snapshot and strict hit_final
  hooks: pre-damage Bloodied/own Intent receipt, optional payment, one persisted
  use condition and sealed save branches. No Action/Reaction is spent.
  Its compile_actions provider seals a private damage-delivery action; the
  candidate_allowed hook denies standalone use. on_hit_context carries the
  confirmed critical/attack receipt to this child's catalog identity, so
  source-scoped defenses read the talent's Sword sphere even on weapon hits.

Subject repositioning (SOL176): subject_reposition(ctx, effect) -> True or None
  runs strictly before typed movement/teleport resolution. True means an owning
  provider handled the complete row; None retains the historical interpreter.
  subject_repositioning requires choose_subject_destination=true on each movement
  or teleport row, explicit non-self scope and a genesis integer policy;
  unstamped saves, self grants and actors without a matching row are inert.
  teleport_steps.destinations/destination_allowed accept optional viewer: the
  subject owns origin, footprint and occupancy; viewer owns sight. Absent viewer
  retains self-teleport queries. typed_executor.teleport_subject(ctx, subject,
  destination) shares landing gates, ledgers and zone arrivals without changing
  controller payment. Gate contexts use the moved creature's own compiled
  numbers for its escape checks. Physical rows explicitly choose_subject_destination=true
  use a legal continuous ground route and movement_paths' forced resolution;
  ordinary grants retain their semantics. Duplicate represented hops share one
  choice and landing within the resolution Context.
  zones.hazard_test(..., immediate_only=True) quotes entry/cross damage for
  safe-destination rules, excluding start-only damage. Default False retains
  all existing AI entry/start risk queries; no stored zone or policy changes.
  Scoundrel's existing event hook (nested=True) ends Bob and Weave on lost adjacency or an
  unavailable anchor. cover_anchor_expiry_policy=1 is recorded at match_start;
  absent policy retains old cover lifecycles and saves. No anchor is inert.

Nested free weapon attacks:
  combat.targeting.reason(engine, actor, target, action) -> denial text or None
  and in_range(engine, actor, target, action) -> bool are the shared pure menu
  and execution queries: footprint reach for located creatures, remembered
  square range for unseen creatures, and the owner's line-of-effect policy.
  combat.target_knowledge.attack_aim(engine, actor, target, action) is a scoped
  context manager for melee and improvised follow-up attacks inside another
  accepted action. It freezes that attack's own known square for the shared
  location_missed checkpoint; it never follows concealed movement. No return
  value or persisted state; nested scopes and consent/errors restore the prior
  transient receipt. Absent a scope, existing candidate targeting is unchanged.

General rider flight and skill projections (P20261005-11):
  general_flight(ctx, row) applies an explicitly typed fixed Fly Speed/Hover
  condition to its own user for the printed duration. Native flight owns paths,
  movement payment, altitude and falling; walking Speed is unchanged. Only the
  same source is refreshed, leaving other flight grants independent. No owning
  row changes existing actors or saved actions.
  compile_skill_bonuses(info) -> None or {skills: changed named skill rows,
  notes: strings, handled_features: owned feature IDs}. A pure strict compiler
  hook before all skill reads; inputs include skills, owned_ids, mechanics,
  mods and pb. Providers preserve unrelated skill adjustments, never mutate
  the input, and claim a feature only when they completely implement it.
  general_skill_expertise replaces the known proficiency component with twice
  PB; legacy totals lacking rank remain unchanged with an unresolved-rank
  diagnostic and are not claimed handled. The projected skill rows are sealed
  in new bundles. No matching
  typed row means no projection; old saved skill totals remain unchanged.

General rider movement and repeat saves (P20261005-11):
  general_rider_step(ctx, row) reuses rider_step's choice and bounded native
  granted movement. Its candidate_allowed listener is scoped to the owning
  engine, actor and source. visible_destination applies native sight and sense
  queries without changing altitude or observed occupancy. Ordinary movement and opportunity
  attack flags retain their existing behavior after the step finishes.
  Repeat saves use existing condition/ongoing repeat_save data, its original
  caster DC and the native holder-turn checkpoint's exact-instance removal.
  Recipient rate limits use zone triggers' existing per_round field and native
  per-recipient counters shared by enter/start events. No matching typed row
  adds a listener or a counter to an old saved fight.

Reviewed passive trait adapter (P20261005-13):
  compile_passives(passives, info) -> new passive-row list; strict pure transform
  immediately after compile_blocks. info supplies source/hash-gated owned_ids
  and numbers. An owned feature_blocks spec may add passive_traits alongside
  any ordinary block, including defense; block="passive_traits" is a traits-only
  marker and does not suppress the source's other effects. The adapter emits
  block="passive_trait" rows with the same feature_id and copied typed config.
  Configs have exact fields (one row per kind per source):
    {kind: forced_movement_reduction, distance_ft: nonnegative integer}
    {kind: standing_cost, cost_ft: nonnegative integer}
    {kind: effective_size, steps: positive integer, roles: [act|resist],
     purposes: [forced|shove|grapple|prone|comparison|brutal_shove|overrun]}
    {kind: grapple_escape_mode, mode: ADVANTAGE|DISADVANTAGE,
     checks: boolean, saves: boolean}, with at least one roll kind enabled.
  Unknown/missing fields, malformed types, repeated kinds and unsupported
  values raise at compile time. These are unconditional traits; unexpressed
  requirements, replacements, costs or additional effects must remain separate.
  passive_traits.py registers forced_distance only (never the second typed
  forced_movement_reduction checkpoint), so its cut applies once per existing
  on_forced_movement call. stand_cost is a pure quote; posture owns all standing
  gates and payment. size_steps requires both role and purpose to match and
  changes neither footprint nor reach. Escape check/save hooks require a
  supplied live Grappled hold on the roller and the actual source actor's
  compiled trait; another grappler, a helped ally's hold, and mere restraint
  do not qualify. Independent Advantage/Disadvantage replies combine normally.
  Runtime reads existing typed_passive_rows only, so retained bundles preserve
  their traits on reload without reading current source data. No new saved
  state, event, action or lock field is introduced; absent traits are inert.

Area knowledge policy (owner 2026-10-08): area_knowledge_policy's match_start
  provider records area_knowledge_policy=1 in MATCH_CREATED for new fights.
  It also binds area_origin_permissions, a sparse source-ID -> integer 0 map
  of printed unseen-origin exceptions; absent sources require sight. Targeting
  consumes this saved map plus saved typed overrides, never current prose.
  Missing stamps retain predecessor behavior; saved_fight_compat preserves an
  existing stamp in SAVED_FIGHT_CONTINUED without changing unstamped payloads.
  Stamped continuations copy the saved permission map. A stamped fight missing
  its binding is rejected rather than silently using changed source authority.
  combat.area_knowledge.origin_allowed(engine, actor, action, destination) -> bool
  gates CELL square perception for rules requiring sight, independently of range
  and line of effect. Explicit typed/printed unseen-origin permissions remain.
  preview_engine(engine, actor) -> read-only engine projection uses the public
  target_knowledge.actors_for view for area_safety and collateral metadata.
  Execution always uses the original engine and hits actual area occupants.
  This is a general owner rule, not an ability hook or runtime method patch.

Terrain occlusion: SquareGrid.bind_occluder_policy(policy) rebuilds immutable
  region geometry before restored queries: cell-v1 retains predecessor cells;
  cross-v1 honors occluder="cell"|"centerline" with altitude-aware crosses.
  The terrain_occlusion match_start hook(engine)->None records cross-v1 in
  MATCH_CREATED only for maps using crosses; it is inert otherwise. Gate 3/4
  restore/upgrade bind the saved policy before sight, targeting or perception.
  Unstamped saves always bind cell-v1. No movement, cover or dynamic zone rules
  change. Map presentation exposes the bound geometry, never current defaults.
  Cross intersections have a bounded grid-local geometry cache, cleared on
  policy rebind; full-cell terrain and dynamic obscurement remain fresh checks.
Targeting policy (owner 2026-10-06): combat.targeting.reason is the pure
  creature-recipient legality seam used by recipients.allowed, for menus,
  controllers and attack declaration. It delegates sight to the same senses
  policy as fog; combat.targeting.line_of_effect checks solid grid geometry
  independently of darkness. CELL generation uses it for the point of origin.
  attack_line_of_effect(engine, actor, target, source) checks area origins rather
  than individual area recipients; existing area selection clips propagation.
  Native and portable attack packets call combat.targeting.attack_missed after
  declaration/checkpoint movement and before its attack roll. It records a
  percentile roll only when the fight's configured percentage is positive;
  absent/zero percentages and clear targets remain inert. Existing unseen
  Advantage/Disadvantage and empty remembered-square misses are unchanged.
  targeting.policy(engine) supplies the same saved settings to attack resolution,
  remembered_square_label(engine, actor, target) and status_text zone cards.
  attack_modes.presentation_modes(engine, actor, target) is a read-only menu
  query for uncancelled condition/modifier and sight contributions after the
  same strict owned removals as resolution. It creates/consumes no modifiers,
  events or dice; targeting uses it to explain cancellation or removal rather
  than promising Disadvantage unconditionally. Later action-specific penalties
  and reaction choices are not predicted by this actor/target query.
  The targeting_policy match_start provider also binds ai_knowledge_policy=1
  in MATCH_CREATED. knowledge_policy.roster(engine, viewer) returns known
  geometry for AI restraint/mount choices; unstamped saves retain prior choices.
  Knowledge-policy journal projection is a pure read; raw journals are unchanged.
  Continuations preserve this integer policy. No observation schema is changed.
  The targeting_policy match_start provider binds the two integer percentages
  in the existing MATCH_CREATED payload, without adding an event/state field.
  Constructor events are replaced on load. saved_fight_compat derives zero or
  20/50 for unstamped predecessors from the locked engine fingerprint (the
  saved_targeting_policies.json release registry) and binds that policy in the existing
  continuation event; old history is never rewritten or globally patched.
  read_queries.pure scopes nested recipient/targeting/perception queries to one synchronous
  call on one engine. can_see uses actor-object keys (projected footprints stay
  distinct), and zones.typed_zones shares its derived rows only within that call.
  Queries/providers must not mutate inputs. The scope resets on return or error;
  no answers survive into execution, a reaction, a new action/origin or a refresh.
  Outside a pure-query scope typed_zones remains uncached. No stored fight fields
  or candidate IDs change. Containers returned by the zone query are fresh lists.
  recipients.allowed shares sight across its targeting, knowledge and reach
  checks; senses.perception shares zones across one viewer's cells/creatures.
  read_queries.candidate_pass(engine) is a read-only context manager used by
  action_legality.observe and saved_fight_compat's intent-binding validation.
  It shares queries only within one shot_geometry action/origin frame, keyed
  by that frame's retained object identity, state_version and event_sequence.
  New actions/origins, recorded changes and outer-call exit invalidate reuse.
  Loadout/terrain queries outside a shot frame remain call-local or uncached.
  It must not wrap execution, reactions or any other state-changing operation.
  A transient spec.concealment_missed flag distinguishes an actual miss from
  canceled/empty aims. Normal miss riders and completion responses still run;
  d20/natural-result responses never run without an actual attack d20.
  This global owner targeting rule is not an ability-specific sight exception.
Candidate construction (lock round 22): a movement query computes immutable
  ranged-attack descriptors once per observed hostile entity ID and passes them
  to tactical_cover(..., attacks=...). The dictionary is local to that query:
  another actor, changed equipment/conditions/catalogue, rollback, reload or
  next query always recomputes it. Unknown/remembered actors retain their
  observed action list; the cache never substitutes live hidden actor data.
  It caches no legality, cover-hook reply, candidate or fight state. Existing
  per-position cover providers and candidate ordering remain authoritative.
  tactical_cover also shares geometry-only sight rays between attacks against
  the same prospective target; cover_bonus(ray_paths=None) remains uncached by
  default. Provider replies still run separately for every attack/ray, and
  providers must treat ray context as read-only. Neither cache outlives its call.

Movement route seams (lock round SOL137):
  opportunity_allowed(engine, reactor, mover) -> False or None is strictly
  observational: no choices, spending, conditions, concentration or event writes.
  It observes existing protection for menus, route quotes and execution.
  opportunity_response(engine, reactor, mover) -> False or None runs only
  during an accepted attack, after eligibility and before OA consent. Native
  steps and ability-granted OAs share the typed reaction selector; legacy native
  reactors use the step seam directly. ask=False never invokes this response.
  It may ask the mover to release protection or choose a witness, and commit
  the resulting costs, saves and effects;
  False cancels this attack. No providers means no change. Guiding Star uses
  this response seam; its released protection remains an observational veto.
  Unrecorded Movement also chooses/saves only in this response or the accepted
  movement event; its observational veto reads existing witness protection.
  native_route_selection(engine, actor) -> None or pure selector callable.
  selector(start_cell, cost_optimal_predecessors, native_costs, legacy_parents)
  -> mapping. legacy_parents is None on the ground; spatial searches provide
  the old single-parent traversal so equal safety scores retain the old path.
  destination_cell -> ordered adjacent cell tuples. Ground cells are (x,y),
  spatial cells (x,y,z). Maps and predecessor sets are immutable views.
  Every returned edge must belong to the native DAG;
  omitted destinations retain the original route. At most one provider applies.
  Called once per movement search before candidate binding. Inputs are read-only;
  no provider is exactly the old route chooser, ordering, cost and identity.
  The unlocked movement_routes provider applies only to Factory fighters. It
  minimizes OA crossings then hazardous squares among equal-cost native paths.
  Memoization lives for one actor query, never across state changes or execution.
  Gate2Engine.opportunity_eligible(mover, previous, next, ignore_oa_from=(),
  free_ft=None, reactors=None, cache=None) -> sorted reactor IDs is the shared
  pure routing/execution query. previous is a projected mover position; optional
  reactors is the observed set for previews, live set for execution. cache is
  caller-owned and valid for one unchanged actor/menu query only. Ask-me reports
  eligibility without asking or spending; execution keeps its reaction pauses.
  It reuses typed_reactions eligibility, waivers, perception and reaction plans.
  ActionIntent.movement_path/movement_mode are optional, omitted from old dumps.
  A supplied full adjacent route is rebuilt and priced with granted_movement's
  validator and flight.step_cost. Its path and mode enter candidate identity;
  legacy destination-only identity stays unchanged. Native step execution still
  rechecks costs/occupancy/altitude, forced stops and checkpoints after reactions.
  Recovery validates recorded MOVE candidate bindings and consumes the original
  path through the existing one-use prepared-candidate seam, without rerouting.
  movement_routes.context_for_payload is the general preview/commit service seam;
  TabletopService.preview_move_path/commit_move_path expose it to UI callers.
  Metadata expected_opportunity_attack_count/expected_opportunity_attacks lists
  observed potential reactors by actor_id/display_name, not guaranteed attacks.
  No route is a promise that hazards/reactions will allow reaching its endpoint.

Movement cost query (lock round 22):
  movement_step_surcharge(engine, actor, mode) -> None or nonnegative integer
  feet added per adjacent grid step, before the existing dragging multiplier.
  Pure strict query; independent providers add. Walking terrain and crawling
  costs add rather than multiply. Return None for nonowners/inapplicable modes.
  Walking/flight/granted menus and native step execution use the same query;
  execution rechecks after reactions. No reply leaves costs/paths/events intact.
  In a mixed high-jump route, flight.step_cost passes "walk" for the level
  approach and "jump" for the rising steps. Jump quotes use that same step-cost
  function for ascent, including terrain, surcharges and dragging. The route's
  movement_mode stays "jump"; no per-segment field is stored in saved fights.
  No Speed, state or allowance is changed by the query. Actual spending remains
  recorded in MOVEMENT_COMMITTED. Grid reachable(extra_step_cost_ft=0) is the
  optional default-inert path-search input; it retains canonical tie ordering.

Walking cost seam: condition_rules rows may supply walking_extra_cost (integer
extra feet per foot, default 0; duplicate rows use the maximum). posture.walking_extra
is a pure shared query walking_extra(engine, actor), used by ground path search
and flight.step_cost execution. walking_cost(engine, actor, normal_extra) ->
None | nonnegative integer is a pure hook to reduce the condition's extra cost
(minimum answer wins; None preserves it). It is only queried for a positive
condition cost; providers must be inert without their own ability/state.
Gate2Grid reachable/shortest_path/movement_step_multiplier accept the optional
extra_step_multiplier=0, added to terrain before drag pricing. Speed and standing
cost are unchanged. No condition carrying the key preserves legacy paths/costs.
The separate no_jumping condition flag (default false) prevents jump offers;
extra walking cost alone does not restrict other movement modes.
posture.standing_cost is the pure stand_allowed/stand_cost query for a mid-turn
Stand Up offer; posture.stand_up remains the sole recorded state transition.
Both use standing_cost's eligibility, veto, cost-provider and budget checks;
explicit ability costs bypass cost providers, and ignore_speed permits zero
Speed, but neither bypasses vetoes or the movement budget.
Standing candidate metadata contract: gate2_engine.legal_candidates produces
standing_cost_ft as a nonnegative integer number of movement feet (including 0)
only for an eligible system:combat.stand_up candidate. It denotes movement-only
payment, consuming neither Action nor Bonus Action; tabletop_service uses it
for the cost label. LocalDeterministicController treats its PRESENCE as an
unconditional posture score of 10000, preferring standing over ordinary choices.
Other providers must not attach this key to unrelated actions. Absence leaves
normal presentation/scoring unchanged; no new saved-state field is introduced.

Forged use-limit metadata: newly compiled action.parameters.typed.use_limit is
the semicolon-joined nonempty printed technique.limits strings, when supplied.
typed.source remains the owning technique ID even when the action ID is hashed.
This read-only metadata does not infer a reset from an ID or change the existing
per-fight use counter, cost or payment. Missing limits omit the field. Saved
bundles keep their original metadata; presentation must treat absence as unknown.

Native lifecycle checkpoint (lock round 19): state_event(engine, event) receives
one recorded CombatEvent after native state processing on Gate2, Gate3 and
Gate4. Return None. It is strict, including nested events, so failures roll back
an active transaction; recursive delivery is bounded at eight calls. Providers
must require their owned condition/data and record all changes through existing
events. With no applicable provider it adds no event, choice or state. This is
separate from Gate4's event hook; a lifecycle consumer registers only here, never
at both points. Standard condition forfeiture uses this checkpoint.
Lock18 condition contracts:
  attack_critical_qualification(engine, attacker, target, spec, roll, intent)
  -> bool | None. Pure, strict query once after a hit and before damage. True
  qualifies that hit only; natural/expanded criticals join it before the existing
  critical_cancel providers. None/False is inert. Cancellation reaches the same
  hit context and one damage packet; no second critical provider invocation.
  damage_defenses(engine, target, damage_type, typed, source_actor_id)
  -> list[defense row] | None, pure. Same row schema as standing defenses (kind,
  damage_types and optional scope). Empty is inert. Applies once to typed targets;
  nonempty matching rows opt native targets into the common defense reader,
  combining resistance once with native modifiers/runtime resistance and honoring
  penetration. No new saved fields or events are needed for either pure query.
  condition_rules(actor, engine=None) returns fresh shared data/inline rule rows;
  condition_id_aliases maps legacy full IDs (core Dodge) without changing saved
  state. Optional condition_aliases maps legacy typed names. Suppressed conditions contribute no
  rule. roll_modes_require_source_visible filters attack/check modes only, using
  the recorded source and live visibility when engine is supplied (unknown is
  not visible). Native attack/check consumers supply it. Rule data remains intact.
  standard_conditions reads critical_hit_within_ft and damage_resistances only
  for their condition holders. disabled_if_incapacitated_or_speed_zero permanently
  removes that condition through normal CONDITION_REMOVED events at event delivery;
  pure roll readers also suppress invalid benefits in an old loaded snapshot.
  Attack sight masks are passed as instance-ID projections; no state dictionary
  replacement. Save advantages/disadvantages combine once across all causes.
  Native typed-condition applications consult the existing condition_immune query.
  Concentration damage saves cap DC at 30; no new end-of-turn check.

Action-reason ordering (lock round 19): activation payment uses stage 0, target
checks stage 1, and final shape-payment filters stage 2. cannot_pay accepts the
caller stage, so a surviving target's real resource shortage takes precedence
over another target's earlier rejection. Candidate eligibility is unchanged.
Action availability:
  engine.action_availabilities(actor_id, source_ids) -> {source_id: answer} is
  the batch form of the single-source query below. Table and connected-sheet
  button explanations reuse diagnostics from CombatService's existing checked
  candidate pass on the live service engine during ordinary menu/decision
  construction. Without matching diagnostics, an independent query shares one
  fresh candidate pass on an isolated engine copy across the requested sources.
  Each source retains its own rejection stages, details and pure explanatory
  hook replies; an empty source list does no work. Diagnostic frames may survive
  a call in the transient engine/service derived cache, never in persisted fight
  state. Reuse requires the same actor and requested sources in the frame, plus
  a matching canonical signature of fight state, action catalogue and typed
  control modes; changes to any of these invalidate reuse. Returned cached
  answers are copied, and reuse does not invoke explanatory providers again.
  Neither form executes an intent, changes state, asks a player or reveals a
  hidden target. Exhausted-use answers retain the compiled per-fight reset text.
  engine.action_availability(actor_id, source_id) -> {available: bool,
  reason: str | None, code?: str, details?: dict}. Read-only, exact source ID in
  the current decision context. It uses matching live-pass diagnostics when
  available; otherwise it observes the actual candidate checks on an isolated
  engine copy, so fallback temporary geometry/cache work cannot mutate the
  caller's state, events, rolls or caches. It executes no intent and asks no
  choices. A real surviving candidate is required for available=True. Rejections
  come from the checks themselves; among alternative targets/origins, the first
  rejection at the furthest reached candidate-filter stage is shown. Candidate
  ordering, identities, payment predicates and AI policy are unchanged.
  candidate_unavailability(engine, actor, candidate, action) -> str | None;
  target_unavailability(engine, actor, target, action) -> str | None;
  recipient_unavailability(engine, actor, target, action) -> str | None.
  These hooks run adjacent to a False result of candidate_allowed,
  target_eligibility, recipient_allowed respectively, either on the live service
  engine during its observed candidate pass or on the isolated engine during an
  independent query's fallback pass. Providers must be pure in both contexts
  and must not depend on being called for every read: replies may be reused.
  Each owner explains its own active denial in plain text, with no hidden creature
  identity/location, state mutation, cost, prompt or cache. None is default-inert
  and leaves a neutral restriction explanation. First non-None reply is shown.

Resumable hit defenses (lock round 19): on_attack_hit's optional
correct_ac_miss(total, armor_class) callback returns an integer revised total.
The native caller owns one correction attempt, consent, payment and bonus damage.
After a successful explicit AC correction, only unvisited defenses continue;
prior AC and payments remain applied. No callback means the old defense flow.
hit_response may return {armor_class: int, hit: bool, miss_reason: "armor_class"
| "forced" | "natural_replaced", natural_result?: int 1..20}. Only an armor_class
miss with unchanged natural is correctable. Legacy (AC, hit) replies are terminal.
Forced/replaced-natural replies never become an AC deficit; original roll records
and the provider's replacement receipt remain intact. Declare a miss that compared
no AC as combat/attack_outcomes.unconditional_miss(), which is exactly that: it
carries no armor_class, so the fight keeps the AC the roll was made against and
publishes no outcome receipt (below) for a miss no number caused. Replies are transient.
ext.invoke(point, registered_callback, *args) is shared by run and the resumable
pipeline: it preserves observational error handling and propagates choice pauses.
The pipeline invokes one registered provider at a time with the current total.
Attack correction:
  attack_miss_correction(engine, attacker, target, spec, roll, intent, total, ac)
  -> None or {source_id: str, label: str, bonus: positive int, bonus_damage?:
  nonnegative int}. Strict transactional providers own consent and recorded
  payment. Called only for a rolled miss, never a natural 1, forced miss or
  canceled attack. Providers see the existing roll and current AC; bonuses do
  not roll again. The first bonus producing a hit stops dispatch. An initial
  corrected miss continues through ordinary hit defenses and damage; a miss
  caused by an already-run hit defense can be corrected without repeating that
  defense. At most one correction dispatch per attack. Bonus damage is part of
  that hit's ordinary damage packet/type, only if it remains a hit. PASSIVE_TRIGGERED
  records each accepted correction and the original roll ID. No providers/replies
  means no change, event, resource spend or saved-state field. Spec is transient.

Movement presentation query:
  speed_explanation(engine, actor) -> list[{label: str, delta_ft: int,
  source_id?: str}]. Pure, optional provenance for that provider's speed hook;
  labels name the player-facing cause. Return []/None for nonowners. These rows
  never alter Speed, candidates or saved state. Terrain step costs use the grid's
  newly entered footprint cells, only for adjacent destinations; summaries do
  not claim an exact path cost.
  engine.movement_explanation(actor_id, destination: Position | None = None)
  -> {actor_id, effective_speed_ft, movement_remaining_ft, reasons, explained_refusal}.
  Reasons have code/message/blocks_destination and optional source IDs, distances,
  speed deltas or difficult-terrain cells/cost. With no destination, Frightened is
  a summary (blocks_destination=None). Only observed fear sources are exposed,
  matching native movement. An empty list does not establish legality. This
  opt-in read-only query never runs during candidate generation or execution;
  saved state, RNG and events are unchanged.
  Terrain step_cost_ft is optional: only an adjacent destination supplies an
  exact step cost via SquareGrid.movement_step_multiplier (entered footprint
  cells, base costs, zone costs and drag). Other queries summarize terrain,
  without quoting a cost for an unspecified path.

Plug-in hook points for sphere and talent mechanics (owner 2026-09-28: "we need to automate every aspect before another
playtest", several workers at once). A module in combat/ext/ registers what it adds with the decorators below; every module
in the package is imported once, the first time a hook is asked for, in name order.

Beastmastery pack feature block (AUTO106 2026-10-05): combat/ext/beastmastery_pack.py reads the feature_blocks.d block
  "beastmastery_pack" (kinds "procession", "encirclement", "sovereign_pack_mind") it compiles through the ordinary
  compile_block hook. Ownership alone grants no active Action benefit. No new hook point:
  Sovereign Pack Mind's paid Bonus Action creates a native one-minute condition with data.choice_owner=1,
  exposing its manual owner's decisions to the service's AI-step probe only while active; d20_bonus then asks the owner
  through needle.ask before adding Proficiency Bonus to a present same-side Tamer/Rider Beast Ally's roll within
  120 feet. Only acceptance spends the integer _round_sovereign_pack_mind receipt; AI owners decide automatically.
  Without both the owned row and activation condition it is inert, including old saved bundles. The natural die
  and roll mode are unchanged. Procession's undefined fear resistance and Encirclement's scoped Disengage,
  speed-on-hit and chosen movement remain GM reminders; no global immunity or Disengage suppression is registered.

Hook contract: wall_defenses(ctx, zone, stats) -> defense dict or None.
  docket_walls.defense_stats calls it once per wall attack before rolling/damage.
  ctx identifies the actual attacking action/actor; zone identifies the owner;
  stats is the current defense dict. Return a copied dict for owned, qualified
  benefits; never mutate the input or saved zone. transform dispatches subscribers
  in registration order, passing each the previous non-None result as stats.
  None retains that result; later explicit replacements of the same field win.
  Independent benefits must preserve unrelated fields from their input dict.
  No subscribers/None leaves existing defenses and saved zones intact.

Spoken-technique reaction seam (combat/speech.py, typed_reactions.on_technique_start):
  speech.record_needs_voice(record, option="") answers from combat/rules/speech.json whether an
  ability named by (record id, option label) needs its user's own voice -- a shout, kanji-style
  battle cry, chant, song, spoken command or Verbal component; it is the test the owner's own list
  records, and needs_voice(action) is the same test for a whole action. A reaction whose printed
  trigger is "a creature ... speaks a command word, uses a Voice talent, casts a spell with a
  verbal component, or begins a supernatural chant" is offered only when the ability that just
  started was spoken: either its targets must hear it (the parsed requires_hearing) or it needs its
  user's own voice. Both tests read the compiled row, so no ability id appears in the engine; the
  list stays inert for a character with no such ability and for an ability that is not spoken. No
  new state, event or saved field.

Approach-restricted path seam (combat/voluntary_movement.py, combat/rules/typed_conditions.json,
combat/ext/approach_restriction.py):
  any condition whose engine rule carries no_approach keeps its holder from taking a willing step
  toward the creature that applied it -- Frightened, and a printed "cannot willingly move closer to
  you" (Name-Striking Tone's Kept at Distance, Spear's World-Transfixing Point, Thread's Sever the
  Battle Line, Daemonic Cultivation's Consume Fear). The set is read from the shared rules table, so
  a new ability needs the rule and nothing in code. The sight exception belongs to the rule, not to
  the query: a rule that also carries no_approach_requires_source_visible (Frightened's printed "It
  can't willingly take a step closer while that source is visible") bites only while that creature is
  visible; a rule without it binds from anywhere. fear_sources returns every such source,
  unconditional_sources the subset that needs no sight. Forced movement never uses this query;
  a voluntary teleport does, through the engine's own teleport_check seam
  (approach_restriction), and only for the unconditional rules -- Frightened's printed rule is about
  steps, so its teleports stay legal. A creature with no such condition keeps every step and every
  teleport it had before.

Printed Save DC seam (combat/save_dcs.py, combat/ability_checks.key_modifier):
  save_dc(engine, actor, basis) answers what a printed "<its Save DC | its Cultivation Save DC |
  its named sphere Save DC>" is worth, reading the defender's own sealed numbers
  (ext.needle.numbers_of): save_dc is the Save DC its sheet records, else 8 + Proficiency Bonus +
  Key Ability modifier; cultivation and sphere are 8 + Proficiency Bonus + Key Ability modifier
  (the sphere's own casts use the same Key Ability, and differ from save_dc only where a sheet sets
  its own). key_modifier is that Key Ability modifier alone, the spellcasting ability this system
  casts from. Both are pure queries: they read state, write nothing and roll nothing, so a reloaded
  fight answers the same number. Used by typed_executor.resolve_opposed_check's kind="dc" branch
  and by ext.contests.select_check, which ranks the alternatives a defender may choose between
  (holds_against_difficulty, the helper that scores one of them).
  No ability id appears in either module.

Opposed-check effect contract (ext.contests / typed_executor):
  contest_against: actor_check / target_check describe kind=check with ability
  and optional skill, kind=cultivation (PB + key modifier), kind=key_ability (the
  creature's own Key Ability, for a printed "its spellcasting ability check"),
  kind=dc (a printed Save DC; combat/save_dcs.py), or kind=save with ability
  (defender only). A spec's options array is chosen by its roller using
  ordinary player/AI checkpoints before drawing either die. Alternatives are ranked by
  how often they actually work, counted over D20_PAIRS = 400 equally likely pairs of
  two d20s (a printed difficulty draws no die, so its share is that chance counted
  twenty times over), and higher is better for the roller who picks it. Each alternative
  is scored for its own roller -- the attacker's land rate, the defender's hold rate,
  which are complements of each other -- by one of three pure helpers:
  holds_against_die(attacker_bonus, defender_bonus) (a rolled contest is won only by
  the higher total, so a tie holds), reaches_difficulty(attacker_bonus, difficulty) and
  its complement holds_against_difficulty (a fixed difficulty is met by getting to the
  number, exactly included). printed_modifier(engine, actor, row, numbers=) gives the
  bonus one alternative's d20 carries, or None when it prints a difficulty instead.
  Keeping the die in the arithmetic is the point: against a +7 Sound Check a difficulty
  of 15 is reached by 13 rolls in 20 while a defending +7 check is beaten by 19 in 40, so
  the check is the better defense although 15 is the larger number. select_check's
  `opposing` argument is the other side's check -- the one it already chose for the
  defender, or the whole spec it chooses from for the attacker, which is scored against
  the best defense the opponent could print (a rolled attack improves exactly with its own
  bonus whatever the defense turns out to be); without it, a plain +0 attack is assumed.
  A prompt whose alternatives are all printed difficulties says the total must reach the
  difficulty; one that is all dice keeps the tie rule; a menu offering both states both
  rules, because only a rolled check can tie.
  The prompt names the reaction, the creature it answers and the ability that
  triggered it. on_success/on_fail run on the selected target; success_by entries
  have margin, effects, an optional label, an optional reading (the plain sentence the
  optional prompt appends, so the player is told what accepting does), and optional=True
  for a printed "you may", which is then asked of the roller (choice:needle.contest_optional,
  the AI answers for itself) instead of paid out silently; that prompt names the
  triggering ability, the creature, and the reading when the row carries one.

  A check spec may carry "hazards": what that check
  relies on (["visual_concealment"] for a Stealth check that relies on being
  unseen), passed to check_modes so a scoped check_against condition reaches
  only a check that names it; absent the key nothing is scoped.
  A hostile-target action row sets harmful=True / applies_to=target so the
  existing compiler does not treat a utility check as an ally/self benefit.
  resolve_opposed_check(ctx, target, actor_check, target_check, *,
  save_fail_effects=None, save_success_effects=None) returns an
  ephemeral OpposedCheckResult (actor RollRecord, target RollRecord or None, dc,
  margin, tied, success); resistance is the defender's total or the printed DC, so
  margin reads the same either way, but success does not: two rolled checks need the
  actor strictly ahead, while a printed DC is a fixed difficulty met on equality (the
  same total >= dc comparison typed_executor.block_wall_breach makes). tied is True
  only between two dice; meeting a printed DC exactly is a success, not a tie. Rolls are
  serialized in CHECK_ROLLED and displayed in history (roll_kind "opposed_check" for two
  dice, "dc_check" with the dc for a printed number). Ties between two dice
  preserve the defended situation; natural 1/20 do not bypass check totals.
  Optional save effects describe what a failed/successful defending save does
  (the contest's on_success/on_fail respectively). typed_save_modifiers(ctx,
  subject, ability, fail_effects, success_effects) returns shaped bonus/modes,
  named conditions, plugin metadata and pressure bonus; settle_typed_save(ctx,
  subject, ability, roll, failed, named, plugin_named, pressure_bonus) returns
  final failure after shared notifications/overrides. Both also serve block_save;
  absent owned modifiers/hooks they contribute no bonus, mode or extra effect.
  Unflagged rows and saved fights are unchanged. No result object is persisted.
  contest_check_mode(ctx, subject, opponent, spec) -> ADVANTAGE | DISADVANTAGE
  or None, before each check (not a save); combines independent modes normally.
  opposed_check_resolved(ctx, target, result, actor_check, target_check) -> None,
  after evented resolution, before branch effects. Ownership/qualification must
  be checked by subscribers. No subscribers means no additional behavior.
  check_dc(ctx, target, spec) -> int | None. The Difficulty Class an opposed check
  is measured against, when its target_check says {"kind": "dc", "of": "<name>"}
  (typed_executor.dc_of). The first positive integer answers; no answer, no "of",
  or a name no plug-in answers reads the target's own Cultivation Save DC
  (combat/ext/end_effect.cultivation_dc), which is what every cultivation talent
  prints. A provider is how a printed DC owned by somebody other than the target is
  read ("the binder's Cultivation Save DC"; spirit_seals.seal_binder_dc).
  Absent = unchanged; a "dc" check never rolls a die for the defender, and matching
  the DC succeeds.

Rules for a module here:
- Cai Clan owner-authored Subpath (cai_clan.py) uses existing hooks only.
  cai_investiture(ctx, effect) selects a fixed willing allied group with the
  owner's choice transport, then stores concentration-linked layers; court=true
  applies its once-per-combat limit and enhanced group. cai_censure(ctx, effect)
  is a Judgment Saber on-hit mark. cai_flare_protection(ctx, effect) grants
  Temporary HP only to this caster's invested allies in the resolved area.
  cai_end_investiture(ctx, effect) ends only this owner's Layer/Court copies
  through concentration.end_copy; candidate_allowed exposes its free control
  only while such an activation exists. Other Concentration remains intact.
  Source ownership is sealed in optional action.parameters.cai_clan; absent
  metadata / absent owned conditions is inert. Layer condition data are integer
  bonuses and plain display strings; Censure stores its dice count at placement.
  The damage-context event claims a single Censure after a confirmed attack
  deals positive HP/Temporary-HP damage, before its zero-HP outcome settles.
  The Radiant component shares the hit's HP-excess accounting without creating
  another death-save failure; it has no attack provenance and cannot claim another.
  Reduction uses a separate round-bound condition, surviving turn changes and
  re-investment, and chooses the maximum rather than stacking Administrators.
  Typed recipients use damage_reduction; native/legacy recipients use
  final_damage after defenses. The latter returns {amount: defended minus
  reduction}, clamped to zero, only for a positive packet and an owned layer.
- Independent triggered weapon attacks retain weapon_source_id in the public
  typed_reactions.triggered_context. Grip, family and deferred-bonus queries
  resolve the actual owned weapon; contexts without an attached weapon stay inert.
  weapon_hits.triggered_melee_weapon(engine, actor, unarmed=False) returns the
  strongest available, readied melee attack (preferring natural attacks for an
  explicit Unarmed Strike), or None. Shared by that context and Moon-Falling
  Counter; legacy catalogs preserve their unmanaged-grip policy.
- Reviewed normal/long attack ranges: factory_compiler copies a positive
  range.feet/long_feet pair to typed range_ft/long_range_ft independently of
  weapon delivery. Public action range stays the maximum; the executor applies
  long-range disadvantage. No declared pair leaves existing metadata unchanged.
- A plug-in-owned passive activation may use reviewed activation.trigger=null
  and source=reviewed_plugin_activation to avoid a second generic paid trigger.
  The printed trigger remains in rules_text/effect evidence and is enforced by
  the owning plug-in. Existing row_allowed can reject legacy generic copies;
  it must return None for unrelated owned rows and characters.
- Movement reconciliation: zones.on_moved(engine, mover, start, end, *, forced=False, entry_at=None)
  -> None. Pass the committed segment's endpoints and forced classification, including
  when another callback has already moved the creature again (mounted Overrun, or any
  deferred placement). Crossing and terrain-distance matching use that segment. Opt in
  with entry_at=end to check its recorded entry despite a later displacement; None keeps
  the existing live-position entry check. Following areas and continuous inside effects
  always use the live position. It never relocates the creature or adds movement events.
  With no applicable areas it adds no zone effects; omitted entry_at changes no behavior.
- Typed modifier target scope ``attack_or_sphere_technique`` (factory_compiler) is a reusable data selector with ``scope_filter.attack_flags``, ``weapon_families`` and ``sphere_ids`` arrays. An attack qualifies by configured flag/family; an active technique qualifies by configured sphere. Empty categories match nothing. Reviewed modifier data can therefore describe eligibility without per-ability names in the compiler.
- Perception queries: combat/senses.py perceives(engine, viewer, target,
  locate_concealed=False) is the shared creature/footprint decision;
  perceives_cell(engine, viewer, position) queries empty terrain, and
  perception(engine, viewer) projects cells and creature ids for tabletop fog.
  These public queries consume existing sense/zone hooks without adding abilities
  or changing saved state. Callers must not reconstruct blindness or area policy.
- Area risk previews reuse typed_executor.effect_subjects and save_subjects per
  effect, including nested save recipients and legacy printed exclusions. They
  resolve a bound Context.target as one recipient; a multi-recipient root
  Context leaves target=None and supplies its complete targets list. Per-save
  subcontexts then bind that save's creature without changing the root roster.
  Both queries are pure: no rolls, decisions, payments or persistent state. Explicit
  self harm has separate self_harm/self_expected_damage metadata and controller
  cost; only endangered area recipients appear in friendly-fire warnings.
  area_effect_risk(ctx, effect) -> None | 'harmful' | 'harmless' is a pure leaf
  classification query. Providers answer only for their own effect type; no
  row means no behavior. Conflicting/invalid answers are rejected. A harmful
  non-damage effect contributes a recipient and zero estimated damage, retaining
  the controller's ally-count penalty. Unknown saving-throw leaves conservatively
  retain warnings; known beneficial leaves are excluded. Recipient scopes always
  use the executor query, including enemy-only saves. No persistent state changes.
- Simultaneous recipients: typed_executor.simultaneous(ctx, subjects) wraps one
  save or damage row applied to two or more recipients in the engine's
  victory_deferred() hold. An early defeat in the batch (including the user in
  its own unrestricted area) cannot end combat before the remaining recipients
  save and take their results; the ordinary victory check then runs once, so a
  batch that defeats every side ends as DRAW_SIMULTANEOUS. Holds nest; a pause
  or error discards the pending check with its transaction. One recipient keeps
  the immediate check. Plug-ins applying one effect to several creatures may use
  the same helper. Transient engine attributes only; no saved fields.
- Granted attacks: an opted-in typed action sets granted_attack=True and marks
  its one root attack effect granted_attack_root=True. Nested attack-granting
  effects and Cleave cannot grant another attack from that action. Missing
  markers preserve existing actions. This general executor contract is available
  to any plug-in that supplies a printed Granted Attack.
Relations and side changes (lock round 17):
- combat.relations.relation(engine, a, b) -> ALLY | ENEMY | NEUTRAL is the shared
  pure live query; a/b are actor states or visible actors. DecisionContext is
  also accepted in place of engine. No cached allegiance. Default: same team
  allies, different teams enemies; team:neutral is neutral to every other actor,
  including another neutral. Self is an ally. Optional MatchState.relations
  contains symmetric sorted team pairs and actor pairs; actor pairs win.
  Missing tables serialize exactly as before. New tables enter through sealed
  roster_setup.relations or recorded commands, never an unrecorded mutation.
- CombatService.change_relations(match_id, change=..., expected_state_version=N)
  is the owner/GM entry point. ACTOR_SIDE(subject actor, other team) changes only
  that actor. TEAM_RELATION/ACTOR_RELATION(subject, other, relation) change a pair.
  These commands use normal journal prepare/commit/recovery and explicit
  ACTOR_SIDE_CHANGED/RELATION_CHANGED events. They spend no economy or rolls,
  invalidate stale decisions, and reject pending choices, setup or ended fights.
  Actor pair overrides and already applied recipients survive side changes;
  companions keep their side unless explicitly changed. Attacks do not change
  relations. New enemy/ally checks must query the current relation. Combat ends
  when no active opposing primaries remain; neutral bystanders cannot prevent it.
- Create-fight: create_factory_match accepts neutral_actor_ids (catalog IDs or
  actor:factory.<project>); each fighter belongs to exactly one group. Confirmed
  setup accepts two combat teams plus optional team:neutral, displayed as Neutral.
- Pure strict bystander_policy(engine, actor) -> None | bool selects retreat and
  Dodge AI. First non-None reply wins. Default neutral actors without enemies
  use it; explicit mortal creature types also use it when they have no enemies.
  No inference from a creature's name. A new enemy restores ordinary combat AI.
  Manual turns keep their normal menus and reaction ownership. Bystander AI
  retreats through safe legal movement, Dodges, then ends its turn. AI never
  explicitly targets a neutral; harmful-area nonenemy_area_count penalizes
  bystanders like allies. This optional metadata is absent in legacy fights.
  compile_actions may set action.parameters.ai_area_family to a stable string
  identifying alternate area shapes of one ability. Decision contexts copy it
  into candidate metadata; the AI prefers a hostile-hitting placement without
  unavoidable allied recipients (including its caster) within that family.
  Without the field, placements group by source ID. Explicit activation self
  costs and harmless/optionally spared allies do not veto a placement. No engine
  recipients, saved candidates, or player choices change.
  Rider migration must also use this seam for area recipients: enemies exclude
  neutrals, each creature includes them. Friendly-fire activation is separate.

Rules for a module here:
- Strict turn_boundary_start(engine, actor) -> None runs after establishing the
  current round/slot and incrementing turns_started, before per-turn resets,
  flight/economy initialization, expiry events, TURN_STARTED, hooks, reactions,
  choices or zone triggers. Lower priorities run first. Subscribers record all
  changes using normal events; errors/pauses roll back the enclosing transaction.
  Legacy Defeated, Dying and Stable slots retain these boundaries and normal turn-start
  gameplay (including death saves/recovery), then end automatically if still
  unable to act. combat.turn_decisions.passes_without_decision is the shared
  read-only engine/service query: setup and pending resolutions are excluded;
  recovered or Conscious-at-zero creatures keep their decisions. A forced End
  Turn left in an old save or after an own-turn defeat is committed by Local
  Auto without changing stored control preferences. No new saved field.
  If a turn_boundary_start subscriber sets terminal_result, the engine stops
  turn startup after this checkpoint, before resets, expiry, TURN_STARTED or
  native-zone effects. No subscriber changing state means no new event.
* turn_decision_required(engine, actor) -> bool: pure query in the shared
  turn_decisions.passes_without_decision helper, after normal turn-start gameplay.
  True retains the normal player/AI control decision for an active Dying or Stable
  actor; False/None is default-inert and preserves legacy automatic passing.
  Inactive actors, setup tasks and pending resolutions keep their existing paths.
  ext.life_state opts in only for the saved dying_2024 rule; no new saved field.
- turn_boundary_start consumers: ext.summon_lifetime (-100)
  consumes only active present summons with a persisted expires_on deadline,
  using the shared effect_durations.due clock and summons.dismiss. Old records
  without deadlines remain inert. Dismissal does not roll dice or ask a choice.
  ext.warleader_commands carries a legacy-format Soul-Standard window's spent
  free Command Response (a base-build turn flag) into that window's own
  response_used field, because the boundary runs before the engine's turn-flag
  reset while the window outlives it. Inert for a window that carries its own
  field and for any creature without that window.
  The approved h64 lifetime data is recorded when a timed summon appears; there
  is no later sweep in summons.on_turn_start. When composing fix/h64-summons,
  retain this single sweep and remove its former _expire_timed_summons call/body.
  Deliberate ordering difference: due summons leave before every start-turn
  effect; per-turn reset receipts now see the established turn counter.
  The same module's dismiss_orphans subscriber (-100) ends an active present
  summon whose owner row names a primary combatant that is out of the fight with
  no Hit Points left, reusing summons.dismiss with reason OWNER_DEFEATED and a
  plain log naming the creature and its summoner. Its policy gate reads the
  record's persisted 'lifetime' == 'ends_with_summoner', which
  combat/rules/summons.json may set only with explicit rules or owner authority
  that the creature ends when its summoner is defeated. No current source opts
  in: Corpse Servant's "Until destroyed or dismissed" does not authorize removal
  on owner defeat. Inability to command or dismiss a creature is not dismissal.
  Everything else is inert and unchanged: a source with no 'lifetime', a record
  with no 'lifetime' (which is every fight saved before this rule, since those
  records carry 'owner' but no policy). Riding capability, inability to command,
  and the absence of a fixed duration do not opt a creature into this policy.
  Duration and Concentration endings retain their existing paths.
  Unconscious at 0 Hit Points is not a defeated
  summoner (ext.life_state.py keeps that fighter on the map), a record with no
  owner row is inert, and dismissal rolls no dice and asks no choice. The
  creature's own turn slot still comes round in the engine's bookkeeping; it just
  takes no action there.
- Continued shaped zones retain their original stored affected_cells and journal.
  spatial_areas.display_cells(engine, zone) is a pure presentation query using the
  same current physical geometry as zone_contains. Table shading therefore
  reflects effective membership after continuation. Explicit paint and walls
  preserve their recorded cells. No save migration, state change or event is
  produced by presentation; revised physical clipping remains an intended change.
- Physical area propagation uses grid.effect_ray_cells(start, end), an exact
  integer 3D voxel traversal including both endpoints. All positive-length
  interior crossings count; a corner/edge touch alone does not enter a cell.
  BLOCKED terrain clips each area's center-sampled location, including lines
  passing obliquely beside pillars. Finite heights use the ray's actual altitude.
  Shared in_area/area_cells/spatial_areas feed previews, shading, targets and
  zones. Shape membership and cube bounds are independent; attack sight rays
  retain their previous rasterization. No state/event/schema field is added.
- Weapon delivery/identity is shared by attack_provenance and ext.weapon_hits
  through combat.weapon_delivery.delivery_kind/weapon_identity. The actual
  packet decides weapon, unarmed or cultivation delivery; Opportunity ancestry
  and delivering-weapon IDs normalize variants once. Tactical ranged eligibility
  uses typed range metadata, while distance uses the catalogue's maximum range.
  A disabled base weapon excludes all its variants. No saved field is added.
  weapon_variant_parent(parameters) -> parent source id or None is a pure
  compatibility query for saved attack wrappers without variant_of metadata.
  Return early unless the wrapper belongs to the plug-in; never change the
  parameters or catalog. Direct variant_of/reach metadata takes precedence.
  Default None retains the action's own physical identity. Echo uses it for old
  Echo-origin attacks; other delivery/position wrappers may share this seam.
- publish_reaction_used(engine, actor, row) notifies an already accepted/paid
  native Reaction. The native attack scope owns cleanup; the row carries its
  feature_id/name/effects. Replies may set the answered frame's penalty, read
  through reaction_penalty(engine, actor_id, feature_id). Frames restore on
  pause/error and depth is bounded at 16. Existing typed-window publication and
  nesting policy remain unchanged; no call means no behavior or event change.
  The existing transient trigger_scope accepts optional action_name and
  roll_kind='reaction' for readable accepted-Reaction prompts. Its actor,
  source and target describe this Reaction; the scope restores on exit/pause.
- Native reaction roll-mode composition retains original Advantage/Disadvantage
  sources after masking and removal, then combines eligible checkpoints and
  native_reaction_roll_mode replies once. Any opposing sources mean NORMAL,
  including accepted native attacks without a Countermeasure reply. Outside
  an accepted native scope the existing mode is returned. No ordinary-attack
  composition change is introduced; collection is ephemeral and read-only.
- effect_cover.ability_cover is the shared per-ray provider dispatch for native
  attack defense and explicit cover_from queries. Actual attacks send purpose
  'attack', their ranged flag and source actor ID. Directional and effect cover
  combine once by maximum per ray, then least clear-ray cover; existing scalar
  attack cover remains a floor and final cover reduction runs once. Providers
  remain responsible for their ranged/melee eligibility. Absent providers leave
  existing attack behavior unchanged.
- Spatial saves: d20_context() exposes copied effect_origin (integer x/y/z),
  effect_origin_kind ('actor', 'actors', 'point', or 'unknown'), explicit
  effect_origin_cells, area and secondary save_geometry. Typed area centers use
  the selected aim; line/cone vertices use the activation origin. Secondary actor
  origins replace the original caster/area. Direct typed effects retain actor
  footprints; point origins never acquire a Large caster's footprint. Untyped,
  Concentration and repeated-condition saves remain unknown unless their caller
  explicitly supplies spatial roll_context. Nothing infers an active intent's
  destination. Nested scopes restore on success, pause and error; none is saved.
- engine.cover_from(origin_cells, source_actor_id, target, purpose='effect',
  target_cells=None) is a pure query returning {bonus: 0|2|5, blocked: bool}.
  Target cells default to its full volume. Empty origins mean unknown (0/False).
  Terrain/object and three-quarters zone cover reuse attack ray computation;
  physical effect queries ignore smoke/darkness and include intervening active
  bodies. blocked describes physical Total Cover separately from the bonus.
  Attack queries retain visibility and legacy attack-only scalar cover hooks.
  Existing directional_cover receives explicit start/end/crossed_edges plus
  purpose, ranged (False for effects), source_actor_id and origin_cells.
  New effect_cover(engine, source_actor_or_None, target, ray_context) -> None or
  0/2/5 is the strict spatial ability-cover query, shared by both purposes.
  Gate printed attack/effect restrictions in providers; no answer adds nothing.
  Restricted wall metadata remains owned by the terrain/rider lane.
- save_bonus_details(engine, target, ability, dc, source_id, intent) -> None or
  {bonus: signed int, contributions: {name: signed int}}. Pure strict query;
  named parts must sum to bonus. The SAME proposal is added once before drawing
  and retained as SAVE_ROLLED.save_bonus_contributions (nonzero parts only).
  A cover provider may return {bonus: 2, contributions: {'cover': 2}}. Do not also
  register that contribution at save_bonus. The existing integer-only save_bonus
  contract and invalid-return checks are unchanged. No proposal/zero parts keeps
  old event bytes; invalid proposals reject the transaction before drawing.
- Dragged creatures use movement_paths.landed_forced_step after each entered
  square: typed areas, map hazards and legacy entry/leave handlers run once;
  damage, new incapacity/Prone or displacement stops the dragging path.
  Every held creature settles an already-committed mover step before the next
  step stops. A hold that cannot remain in reach is explicitly removed/recorded.
  Preexisting Speed 0 does not itself prevent forced movement.
  Push/pull routes pass interrupt_drag=False: damage, Prone and Speed loss do
  not shorten their printed distance. Explicit zone stops, displacement, death
  and the end of combat still interrupt those routes.
  zones.on_step(..., interrupt_harm=False) resolves entry effects without treating
  damage, Prone or Speed loss as a push/pull stop; its default retains the willing
  and dragging path policy.
  movement_budget tracks an integer movement_withheld_ft only when a turn begins
  immobilized, after turn-start Speed expirations. Removing the last immobilizing
  condition restores that unspent initial allowance (capped by current Speed),
  with MOVEMENT_ALLOWANCE_RESTORED; it never refunds spent movement or creates
  extra Dash/grant allowance. CONSCIOUS actors at zero HP share the same contract.
- Reach: attack_reach_bonus(engine, actor, action, opportunity) -> None or
  {source_id: str, feet: nonnegative int, condition_id: str, stacking_group?: str}.
  Pure strict query on melee attack profiles. Providers gate ownership, profile,
  resources and own-turn clauses. condition_id is an existing condition instance
  on actor; its source must match and its expiry must not be due. Removed/expired
  records grant nothing. Duplicate source/group contributions use max; independent
  sources add. action is never rewritten. Use combat.attack_reach.maximum for
  candidate/attack reach and opportunity_distance for the bound OA profile.
  Native filtering, each-strike validation, redirection and OA departure read the
  same query. Absent providers change no state, events, catalog or distances.
  Generic reactions carry the selected weapon/Unarmed profile through eligibility,
  declaration and execution; these queries do not require an unspent Reaction and
  use opportunity=False for ordinary counterattacks. Typed target validation runs
  after all earlier d20/attacked/before-attack reactions even if no hook replies.
  Integrated callers retain bound origins, altitude-aware effect distance, full
  projectile-route validation and interception range-change checks.
- Recipe compilation: strict compile_recipe_options(owned_ids, copied_mechanics)
  returns None or list[combat.recipe_options.RecipeOption]. Both records must be
  owned; copied_mechanics contains only owned records. Effects/target/area are
  declarative; the compiler retains the base economy, costs and range, stable
  recipe IDs and ordinary modifiers. This runs before modifiers, unlike
  compile_actions. No contribution means no change. Optional recipe payment
  substitutions compose with one other modifier, applying the full substitution
  last (effects/dice, range/reach, area, duration, economy and payment); consumers inspect
  typed.selected_modifiers as well as typed.modifier. Never mutate inputs or
  create actions here. See recipe_options.py for validation and full contract.
- Explicit creature targets include the user when the action allows it. Typed
  resolution retains a selected self recipient for saves/effects; the implicit
  actor fallback of target_kind SELF retains its existing context semantics.
- Modifier usage retains modifier_once_period='owner_turn' when its printed
  activation trigger restricts use to the owner's turn. The executor checks
  current_actor_id before using that gate; other-creature resets never clear it.
  Unrestricted 'turn' modifiers retain the shared all-creature clock. Historical
  untyped gates keep their existing behavior. turn_uses.usage_explanations is the
  shared read-only Table/sheet refresh wording for turn, owner_turn and round.
  Refresh text is appended after the original action description. Each nested
  limit names its source ability (authority name), explicit effect name, or
  readable effect type; nested bonus limits preserve the action's normal rules.
- Per-turn use clock: combat.turn_uses.reset_at_turn_start(engine) -> None runs
  before expiry and triggers at EVERY creature's native turn start. It removes
  typed_once_turn:, once_per_turn: and creature_kind_once: flags from all actors,
  recording PER_TURN_USES_RESET(actor_id=owner, keys, turn_actor_id) for each
  changed actor. The reducer removes exactly those keys. No matching flags is
  default-inert (no event). Owner-turn flags, Reaction availability and round
  counters keep their existing clocks. New compiled modifier effects preserve
  an unrestricted once_per_turn limit as modifier_once_period='turn', or
  'owner_turn' for printed owner-only qualifications; ambiguous
  historical modifier_once records keep their existing owner-turn gate. An
  ability restricted to 'on your turn' must also retain its own-turn eligibility
  check; this reset grants neither a Reaction nor permission to act off turn.
- Creature passage: pure pass_through(engine, mover, occupant) returns None
  (blocked), 'difficult' (double movement cost), or 'free' (no extra cost).
  A free grant wins over difficult grants, without removing terrain costs. The
  shared ignores_difficult query also removes the creature-space surcharge.
  combat.creature_passage.geometry supplies blockers, forbidden endpoints and
  difficult cells to voluntary pathfinders. Native movement binds permissions in
  candidate metadata and rechecks after reactions; hidden actors are not disclosed.
  Unseen or remembered occupants remain actual blockers during execution so native
  contact handling stops the move, records the contacted cells and avoids charging
  an unoffered transit surcharge. Permission applies only to directly known actors.
  Grid shortest_path/reachable accept end_blocked_cells separately from transit
  blockers and test complete footprints. No grant permits ending in an occupied
  space or crossing a wall. A stopped transit returns along its committed path
  to the last free space, retaining spent movement, in the recorded transaction.
  Flight and finite-height maps use the same permissions against actual creature
  volumes; an occupied destination remains forbidden. Recovery checks placement
  at its actual altitude, so clear air above a low wall remains a legal stop.
  Recovery runs normal leave-zone cleanup and emits a readable PASSIVE_TRIGGERED
  notice; the final movement record binds the corrected position and path.
  None preserves existing movement. Forced movement and teleports do not use it.
  Strict pass_through_entered(engine, mover, occupant, intent) -> None is a
  transactional notice after first entering a creature footprint; consumers may
  record source-specific crossing limits/protection. It is never called by queries.
  The existing pure opportunity_allowed query also applies to legacy reactors.
  C16: Overrun grants bind the allowed occupant's entity id and expire at the end
  of the current turn, so choosing a short move does not discard unused passage.
  A once-only crossing records use in pass_through_entered and keeps permission
  until the mover exits that footprint, then denies re-entry. Queries never spend it.
  Changes to condition data require CONDITION_APPLIED with the instance id.
  Living Battering Ram/Fortress-Line Breaker permission is scoped to their approved
  straight move; it never waives path, target, payment or attack requirements.
- Voluntary movement: combat.voluntary_movement.destination_allowed is a pure
  knowledge-based query shared by ordinary and granted menus. Grants use observed
  occupancy; actual blockers are checked by native execution and recorded contact.
  Existing destination-only Frightened semantics remain unchanged here.
- Native movement cost changes: each iteration refreshes terrain, occupancy and
  dragging before its first budget guard, then rechecks after reactions. If a
  newly priced step is unaffordable, movement stops at the last paid square and
  records the shortened path and readable reason; it does not raise or undo the
  accepted reaction. Initial invalid candidate budgets still fail normally.

- Hook ordering: @hook(point, priority=0) runs lower integer priorities first,
  retaining registration order for ties. Default priority preserves existing
  subscribers. Use priority=-100 for native landed-zone effects so import order
  cannot offer a movement reaction after a zone already stopped the creature.
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
  flight_hover, flight_suspended, flight_disabled, cannot_gain_altitude,
  fly_speed_percent (integer 1-100, the share of the Fly Speed a creature keeps
  while the weight applies; the lowest share any row asks for wins, so two
  halvings still leave half) and fly_speed_zero ("its Fly Speed becomes 0",
  which keeps Hover, suspension and the ability to gain altitude: a creature
  that can Hover stays up, and combat/falling drops one that cannot).
  flight_disabled stays the stronger "it cannot fly or hover at all" reading.
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
- Chosen forced destinations (combat/ext/forced_destination.py, used by gravity.py's
  Orbit-Breaking Guard and Weight-Borrowing Throw): routes(engine, mover, feet,
  want=, step_allowed=) -> {destination: route} enumerates, at the mover's OWN altitude, every
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
  pauses roll back the whole transaction. combat.movement_steps.context exposes
  read-only travelled_ft and remaining_ft for this move, restored across nesting.
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
  ordinary routes require clear segments at their actual height.
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
  returns None, ADVANTAGE or DISADVANTAGE. A contribution combines
  with the full typed/native mode set; opposing modes cancel once. No contribution
  preserves existing mode behavior. roll_context carries source_actor_id, named
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
  leave-reach OAs, and rechecks again after those OAs before charging the step.

- Reaction waivers: reaction_spend(engine, actor, row, commit) returns None or
  "free". commit=False is a pure eligibility query and may repeat during previews;
  commit=True consumes the provider's own entitlement through recorded events.
  Dispatch is strict and lazy: the first "free" wins, so other grants are not spent.
  Errors and player-choice pauses unwind the transaction. An absent hook preserves
  ordinary Reaction spending. The provider owns grant limits, expiry and eligibility;
  a waiver never overrides inactive/no-Reactions restrictions. Native Opportunity
  Attacks pass the compiled reaction row plus reaction_kind="opportunity_attack";
  action_id identifies its weapon action. Legacy rows use the ordinary Opportunity
  Attack feature id/name/block. typed_reactions.spend_reaction commits once only
  after consent; reads and declined offers never consume a grant. It leaves the
  ordinary Reaction unchanged on a waiver. Querying a grant must not reserve it.
- Dynamic growth: size_change typed effects call combat.dynamic_size.apply_growth.
  An expiring source-owned condition records the largest size that fits; native
  FOOTPRINT_CHANGED records both size and nearest legal anchor, including expiry.
  No growth leaves the original footprint and serialized state unchanged. Reach
  measures from its new occupied edge; growth grants no extra reach in feet.
  size_steps(engine, actor, role, purposes) -> int or {steps, additional}; C12's
  ext.effective_size.cells adds functional steps to the current footprint width.
  Roles are act/resist; purposes are forced, grapple, shove, prone. Plain steps
  take their maximum and printed additional steps add. These never grow geometry.
- Dodge attack eligibility uses target_knowledge.can_see(engine, defender, attacker).
  Read it before temporary attack-bonus condition masks: formation suppression of
  Invisible benefits does not itself grant sight. Actual special senses still do.
  Knowing a location alone does not grant Dodge's Disadvantage against an unseen
  attacker. Other Advantage/Disadvantage sources and Dexterity-save behavior are
  unchanged. This intentionally changes attacks where Dodge previously cancelled
  an unseen attacker's Advantage; ordinary visible attacks keep their bytes.
- Concentration after damage uses the final damage taken after defenses and the
  final_damage checkpoint, before Temporary HP absorption. Positive damage asks
  for the existing Constitution save at max(10, damage_taken // 2); zero does not.
  This intentionally adds/changes checks on Concentrating creatures protected
  by Temporary HP. Ordinary damage, damage receipts and HP loss remain unchanged.
- Typed cures: strict te.condition_removal(ctx, subject, name, cause) -> None is
  called immediately before block_remove_condition deletes a condition, including
  when the named condition is only pending and has no active instance to delete.
  name is trimmed/lowercase with condition:typed. removed; cause is the normalized
  effect.cause string, default "cure". Context supplies source, caster and intent.
  Providers may cancel only their matching delayed instances and release their
  reservations using recorded events. Durable and Cold Iron Call can use this
  point; do not couple ordinary typed cures to their storage layout. Other names,
  other targets and providers without owned pending instances remain inert.
  The point does not veto the cure. Invalid replies, errors and choice pauses
  unwind the containing transaction. No request event is added without a provider.

- Damage deferral: strict damage_deferral(engine, target, packet, intent) returns
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
  condition), DISADVANTAGE:obscured (typed zone visibility contribution).
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
  -> None or {allowed: bool, reduction_bonus: nonnegative int}. Runs once per
  owned generic damage-response row, after ordinary defenses and before any
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
  park(target, attacker_id, integer_reduction, feature_id) stores paid pre-damage
  self/ally hit guards until rolled damage binds the confirmed attack. An optional
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
  attack kinds (weapon, unarmed, other). Empty attack_kinds retains the existing unrestricted defense behaviour.

- Destination squares: a typed self row carrying "picks_destination": true (with distance_ft: feet | "speed" | "half_speed")
  makes its SELF action offer squares like a self-teleport (typed_executor.teleport_reach) and passes the chosen square as
  Context.destination; the row's own effect type does the moving (rider lane C8: Black Current's River-Cut route). Rows
  without the key are unchanged.
- Self-teleport destination (the other half of the same seam): when a self-scoped teleport row (applies_to null/self, type
  "teleport" or type "movement" with mode "teleport") has no square bound to the action, typed_executor.block_movement calls
  teleport_steps.ask_destination(ctx, reach, *, name="") -> teleport_steps.Destination, the shared "where do you want to land?"
  question behind every self-teleport. It enumerates teleport_steps.destinations(engine, actor, feet) -- unoccupied, in-grid,
  unblocked, visible squares within reach -- and rides the bounded choice transport, so the answer is a real player decision
  that pauses the fight, is labelled with the ability and the creature, and rides the intent, so a reaction interrupting
  between paying the cost and choosing does not drop it. Destination.square is the chosen cell or None to stay put;
  Destination.asked says a player was actually put on the spot, so the caller can word its "nothing happened" line truthfully
  instead of guessing from an empty selection. The question is asked once per represented hop, not once per row:
  teleport_steps.hop_key keys the answer on the use, the creature, the ability, the reach and the aimed target, and
  the resolved answer is kept on Context.hop_destination (resolution-local, never saved), so the teleport row and the
  parser's movement(mode=teleport) row for one hop ask once and land on the same square. Default-inert: an AI combatant,
  an engine with no recorded control mode, no transport, no reach or nowhere legal to land returns Destination(None, False)
  and the caller keeps its own previous behaviour, so AI fights and saved fights replay unchanged; a decline returns
  Destination(None, True) and the creature stays put, its cost already spent. Only self rows ask: a row that teleports
  another creature is not answered here and keeps its GM instruction.
  Context.hop_completed records the entire player-selected attempt after gates return, including a blocked result;
  duplicate rows do not retry it. A transaction pause never marks completion. Both memos are resolution-local.
  teleport_steps.payment_text(ctx) describes the compiled economy slot and amount/pool in prompts and declines.
  teleport_steps.hop_reach(ctx, row, reach) -> int resolves null-distance within_range parser rows to the
  unambiguous explicit self-teleport reach; explicit or ambiguous multi-hop distances remain separate.
  Unbound questions use teleport_steps.teleport_requirement(typed) -> str | None: top-level teleport_where
  takes precedence over teleport-row where, matching the bound menu contract. A "darkness" requirement
  checks both endpoints using motion.obscured/obscured_at. Absent metadata leaves ordinary teleports unchanged.

Mark relationship data (combat/rules/typed_conditions.json):
  mark_aliases maps normalized names to canonical slugs (one level; targets must be canonical).
  mark_counts_as maps a required canonical slug to special slugs that satisfy that requirement, one way.
  typed_executor.mark_condition_id uses the canonical spelling for new marks; bears_mark accepts all stored
  aliases of the requested group and its declared special marks, always scoped by source actor ID.
  mark_requirement_ids(name, owner_id) returns those accepted IDs for inspecting individual instances (Miko purification).
  Missing tables retain literal names and exact matching. Queries are pure and never migrate saved state.

Hook points (arguments; what the hook returns):
  action_destination_choice(engine, action) -> True | None. Read-only table-menu
    presentation: True sets destination_choice on the group so the client submits
    a representative candidate and lets the resolving choice ask for its landing
    square. No IDs, options, legality or saved state are changed. Absent providers
    retain native placement. teleport_steps opts in only for player self teleports;
    AI, non-teleports and other-creature/area targeting retain their previous route.
  self_teleport_destination(ctx, effect, reach_ft) -> teleport_steps.Destination | None.
    Resolution-only choice for a bound self teleport before placement/gates. A reply
    supplies the player's square (None means stay); None preserves bound execution.
    Strict choice pauses roll back payment and replay through the existing transport.
    Default-inert for absent providers, AI/headless controls and other-creature rows.
    teleport_steps uses it for all ordinary paid, augmented and response teleports;
    menu narrowing and both bound/unbound choices use destination_allowed and
    destinations(engine, actor, feet, *, where=None, action=None). The list query
    enumerates the single-cell query; optional action reuses owning candidate
    restrictions without regenerating economy-gated candidates after payment.
    ask_destination(..., destination_filter=None) can further narrow that shared
    legal set for a printed escape restriction; the callable is resolution-local,
    never saved. Shadowless Reversal uses it to leave the attacker's reach.
    Darkness checks both ends through motion.obscured/obscured_at: dim light is not
    separately tracked; the existing approved darkness/smoke/fog/obscurement counts.
  Context.on_hit_context(target, **changes) creates an explicitly attached hit child.
  It preserves critical and attack roll identity across named bonus actions, while
  assigning AttackDamage.source_id to the child's catalog damage source. Deferred
  hit-triggered bonuses and Forms share the originating hit's defensive reduction budget; the
  normal packet checks still reject mismatched attacker, recipient or source.
  Unrelated saves, zones and new attacks use independent Contexts and inherit no hit.
  The deferred-bonus consumer attaches printed hit triggers only; damage-triggered
  marks are independent packets even when a hit happens to trigger them.
  Geometry queries may use typed_reactions.physical_melee_reach(engine, actor) -> integer feet or None
  (no compiled melee profile). This reuses the pure opportunity_action/opportunity_profile hooks,
  independently of Reaction availability or plans. It changes no state or opportunity-attack eligibility;
  only consumers explicitly calling it use this geometry.
  Generic ac_bonus effects may opt into duration="triggering_attack". ATTACK_DECLARED collects the
  protected recipient in the transient spec; attack_defenses.resolving_defenses installs evented AC only
  around typed/trap resolution, removes it on return/error/pause and suspends it during nested attacks.
  Other AC durations retain their existing handling. No opted-in effect means no AC change.
  typed_reactions._run_generic_effects(..., recipient=..., attack_spec=...) supplies the defensive
  recipient contract and triggering_attack_spec to the ordinary ac_bonus executor. Explicit attacker
  recipients still name the triggering source. The spec is resolution-local and never persisted.
  Core modifier targets "Melee weapon attack" / "Melee weapon attacks" select
  each actor-owned melee weapon attack, including off-hand and Opportunity Attacks,
  through the same reviewed modifier pass as Unarmed Strike. Ranged/thrown
  deliveries and already-modified variants are excluded. No matching reviewed target: default-inert. Shared by
  any hit/use modifier naming this delivery category; no ability ID branching.
  Additive on-hit modifier loadouts (SOL117): factory_compiler calls the public
  ext.attack_modifiers.capture(base) with compiled variants/composition metadata,
  then settings(actions) after delivery to add free player-only SELF settings.
  attack_modifier_capture_allowed(row) -> bool | None lets effect plug-ins veto
  independent on-hit conversion with False; unmatched rows return None and keep
  the existing capture behavior. capture checks nested effects/on_hit/on_fail/
  on_success rows too. A veto retains the original attack variant and creates no
  toggle or preference metadata. Sequence declarations use this to retain their
  primary-action selection and later-hit contract.
  Hit-time if_marked prerequisites also veto conversion: their marks must be
  sampled from the attack's embedded rows before that hit applies new marks.
  Settings collect damage types and unique payment alternatives from every
  option. Payment values index that stable union (first-option indices stay
  unchanged); hit resolution validates against the selected option. A preference
  unavailable for that option asks again rather than dropping or mispricing the
  rider. Presentation filters choices to the fixed option, or shows their union
  for Ask me. Only integer/string preferences persist; no new fight-state fields.
  No matching owned modifier leaves actions unchanged. Sealed
  typed.attack_modifier_loadout retains one talent, effect options and alternative
  payments; attack_modifier_variant marks legacy full-attack variants for player
  presentation only. settings(actions) copies the final parent loadout onto
  delivery variants, excluding modifier/selected_modifiers already embedded in
  their effects. attack_modifier_family names the parent preference identity,
  shared by attack_modifiers and paid_hit to keep their routes mutually exclusive.
  No parent loadout or matching owner leaves variants unchanged. Optional Ask-me
  activations retain accept/decline even with one affordable option; mandatory
  single failed-save outcomes may resolve directly. AI catalogs,
  candidates and payments retain legacy behavior.
  after_hit_choice consumes persisted integer/string choices, asks via Needle's
  transactional transport when requested, checks eligibility/affordability before
  paying once per triggered use, and runs only the chosen rider on the hit target.
  attack_modifiers.effect_can_apply(ctx, row) is a pure pre-payment query on the
  hit context: checks ordinary owner-mark wrappers and nested eligibility before
  offering consent or spending. Self gates use the actor; target gates use the
  hit creature. Explicit hit-time gates use only their captured snapshot and
  still veto detachment. No loadout means no execution or presentation change.
  Shared ext.paid_hit.apply_paid_effects binds the selected rider ID as the child
  Context.effect_source, retaining the triggering action, typed metadata and hit
  identity. Sibling effects may read that activation identity; the parent context
  remains unchanged, and no activation identity is persisted as new fight state.
  effect_description(row) -> str | None supplies plain player explanations for
  named marks or custom effect rows in modifier descriptions and choice prompts.
  It is a read-only presentation hook; unmatched rows return None (default-inert).
  effect_player_text(row) -> str | None replaces evidence with a complete plain
  description of that row and its nested effects/save outcomes. Used by the
  shared paid_hit.effect_text helper for tooltips and prompts; unmatched rows
  return None, retaining reviewed evidence and recursive nested descriptions.
  Captured variants are hidden only when settings emits an owned parent toggle;
  absent parents/settings retain the original player menu and sheet route.
  Shared attack_modifiers.variant_replaced(action, actions) repeats that read-only
  check for table and sheet presentation of older sealed capture markers, without
  migrating stored actions or changing engine candidates.
  Old catalogs without metadata are inert. ext.attack_modifiers.presentation
  extends tabletop_service._shapes with modifiers/selectors; setting actions only
  update evented UNTIL_REMOVED preferences, never attack or pay. Darkness is unchanged.
  Plain paid hit riders (no precondition, limit or augment traits) compile into
  typed.paid_hit_choices: [{id, name, options: [{id, label, costs, effects}]}].
  ext/paid_hit.py consumes this through after_hit_choice(ctx, target, kind):
  the actor must also own the compiled paid_hit choice-owner passive row, so
  borrowed/copied delivery metadata cannot grant another character's ability;
  manual owners may decline or choose an affordable option on any creature's turn;
  AI owners choose automatically. Each hit pays separately and retains remaining
  ordinary attacks. No metadata means no hook effect, including old saved fights.
  Sword's after_hit_choice consumer also covers approved Sword Opportunity Attacks
  whose catalog lacks a captured paid_hit_choices row. It requires the actor's
  owned life_severing passive and reuses that actor's compiled Life-Severing loadout
  effects/payments through paid_hit.apply_paid_effects. Captured choices retain
  the shared owner's route; absent ownership/loadout metadata is inert. The
  shared effect-eligibility query on the actual hit target gates both the menu
  and payment, so exhausted riders never report a paid activation. The
  completed-hit hook replaces only the newest reduction delivered by that hit,
  and effect duration anchors halving to the swordsman's next turn off-turn too.

  Reviewed typed modifiers may set replaces_effect_slot="name": the compiler removes only
  effects labelled effect_slot="name" from the base effect tree, including nested branches,
  while retaining damage and unrelated riders before applying the modifier's changes.
  This works for individual variants and composed augments; omitted fields preserve all
  base effects. Labels are compile-time metadata, not conditions or player-facing text.
  Reviewed typed area data may set preserve_size=True: persistent zones keep the resolved
  size_ft (including size_ft_by_cl) for any shape, with affected cells clipped to the actual
  map. Omitted preserves the legacy 60-foot zone cap; no ability ID is checked by the seam.
  compile_equipment_items(items)             -> replacement item list or None. Pure normalization before equipment
                                                 compilation and the sheet item list. Optional combat_item_key and
                                                 combat_weapon_key bind individual copies across attacks and inventory.
                                                 combat_name supplies a plain item/attack label for distinct copies.
                                                 No replacement preserves existing stacks and identities.
  attack_allowed(ctx, target, effect)        -> False to stop this attack sequence before declaration or reactions.
                                                 Pure query, checked for each attack and target, and rechecked after
                                                 declared-attack reactions and native checkpoints; no answer is inert.
                                                 Equipment stock/possession providers opt in through compiled metadata.
  Scoped event provenance: attack_scope.current(engine) includes frame['context'] (the resolution-local Context),
    actor_id, target_id, source and effect. An owning nested event hook may consume physical equipment on matching
    ATTACK_ROLLED, before hit reactions/damage, recording a local per-scope flag against rerolls. No context survives
    resolution or is saved. Existing roll capture/attack_roll_finished behavior is unchanged for all other providers.
  Secondary typed saves may set Context.save_geometry = {origin_ids: [actor IDs], range_ft: integer}.
  This resolution-local geometry overrides the action's original range/area for post-movement save revalidation;
  distances use the engine's footprint rules against any supplied origin. Unset preserves the original check.
  if_marked effects may opt into "at": "hit": named marks are sampled immediately before each typed attack resolves,
  before damage, reactions and on-hit riders. The resolution-local cache is refreshed per attack, shared with nested
  effects, and never persisted. Unset checks current marks; no snapshot/absent mark means the opted-in gate fails.
  additional_actions(engine, actor)         -> iterable of catalog action IDs, offered through normal action candidate
                                                 gates to every actor, including roster/summoned actors. Pure query;
                                                 definitions must already exist (e.g. installed at match_start).
                                                 Deduplicated against actor.action_ids and other providers. No hook
                                                 returns no candidates and changes no saved actor/catalog membership.
  damage_source_alias(engine, source_id) -> catalog action id or None, when a derived packet has no catalog row.
                                          One owned resolver; generic defense queries reuse the parent typing.
                                          No answer retains the empty derived typing. No state or serialization change.
  attack_magical(engine, source_actor_id, typed) -> bool: True when this attacker's packet counts as a magical
                                          attack, whatever weapon made it ("attacks you make count as magical",
                                          Sovereign Needle Incarnation). Consulted by typed_reactions only for a defense
                                          row printed against nonmagical attacks or damage (mundane_only: true), so an
                                          ordinary defense is untouched. Pure query; any True answer wins; it changes
                                          no saved action typing, no event and no state. General: any printed benefit of
                                          this shape may register it.
  soak_dice(engine, target, row, spend, dice) -> DiceSpec or None: the dice a damage_soak reaction (Stamina Guard) rolls
                                            after its spend is paid; the last owning answer wins (Gilded Guard 2d8 per
                                            Stamina, Iron Shirt d12s). Transactional (run_strict): may ask its owner.
                                            Display provenance: engine.damage_context() identifies confirmed attack
                                            packets only; None for hazards and other non-attack/derived packets.
                                            Never infer their source from event history or the outer intent.
                                            Lock-round item: expose immutable source/actor/target context for every
                                            damage packet, clearing/restoring it across nested damage and pauses.
  soak_total(engine, target, row, roll) -> int or None: a raised total for that roll (a per-die floor, maximum dice,
                                            one die rolled twice); the highest answer counts, never below the roll.
                                            Both default-inert: no owner, the ordinary 1d10-per-Stamina roll (rider lane C7).

  forced_movement_reduction(ctx, subject) -> nonnegative integer feet; reductions add before typed push/pull.
    ctx.forced_movement_distance_ft is the remaining triggering distance after ordinary reactions, only while these hooks run.
    Default-inert: absent handlers leave distance unchanged. Activation-local rider records may use ctx.damage_cache;
    they are shared with nested effects of this activation, never persisted or carried into later activations.
                                            Ownership belongs to the plug-in; absent hooks leave movement unchanged.
  prefight_ai_allowed(action) -> False to exclude this compiled buff from automatic pre-fight picks only.
    Pure query; action is the owned ActionDefinition. None/True preserves the default. Player options and
    validation remain unchanged; the pre-fight option stores ai_eligible=False only for vetoed rows.
    Combat-disabling forms own their veto in their plug-in; no subscribers leaves ordinary buffs eligible.
  prefight_setup_choices(bundle) -> list of declarations for choices needed to initialize an actor's fight bundle.
    A declaration has id, label, kind="integer_range_list", count, item_label, minimum, maximum, and default.
    Optional help is plain player-facing text explaining the choice, its effects and costs; the UI renders it generically.
    The service validates submitted integer lists against that range and seals values under
    bundle.prefight.setup_choices[id]. No declarations is inert and leaves setup choices absent.
  Generic reaction min_cp_cost data gates technique-used responses on actual CP expenditure, independently of
  other resource payments. Omitted or zero leaves legacy eligibility unchanged.
  ANY_CREATURE target kind                    -> active enemies, allies and self; ordinary shared sight and range.
                                                 This is a neutral creature selection, not a hostile attack for Charm.
                                                 Existing kinds and persisted action definitions are unchanged.
  targeting.attack_missed spec seam          -> optional before_attack_d20(engine, actor, target, spec) callback.
                                                 Called after final declaration/movement checks and a passing
                                                 concealment percentile, before the attack d20. Return is ignored;
                                                 it may shape spec or pause for paid d20 consent. No callback is inert.
                                                 Used by all typed attacks; spec and callback are transient, never
                                                 fight state. Misses invoke no callback and pay no d20-reaction cost.
  target_sight_bypass(engine, actor, target, action) -> None (abstain), True (owned knowledge/sight exception),
                                                 False (veto that exception; not the action). Any False defeats True.
                                                 Pure strict query consumed by target_knowledge.knowledge,
                                                 location_missed and ext/reaction_sight's generic reaction qualification.
                                                 The owner's universal targeting rule overrides this hook at creature
                                                 admission: non-attacks still require actual line of sight and effect;
                                                 attacks still require effect; optional positive concealment checks use actual senses.
                                                 True can supply DIRECT knowledge and satisfy printed lost-sight or
                                                 generic-reaction qualifiers, but cannot grant actual can_see sight,
                                                 update observations, or bypass range/team/other recipient restrictions.
                                                 Reactions query it with a transient action carrying their feature_id.
                                                 Dawnmark Scripture limits it to Mark talents, own mark within 60 feet,
                                                 known direction and an open route. No subscriber is default-inert.
  requires_compiled_actions typed metadata    -> nonempty list of exact action IDs, checked by activation_requirements
                                                 before candidate/reaction admission and spending. Every dependency
                                                 must be owned and present in the catalogue; malformed lists fail closed.
                                                 Missing metadata is default-inert. No missing action is implemented.
  min_cl typed metadata                       -> integer N, the printed "Prerequisite: CL N+" construction gate. The
                                                 same admission check compares it against the actor's own compiled
                                                 Cultivation Level (typed numbers.cl, baked when the character was
                                                 compiled), and a character below the gate is offered neither the
                                                 action nor the reaction row before any payment. A printed
                                                 prerequisite is character construction rather than a fight rule, so it
                                                 is enforced here instead of remaining a GM rider. Missing metadata
                                                 is default-inert and leaves older saved fights unchanged.
  target_eligibility(engine, actor, target, action) -> None (abstain), False (recipient veto), True (no veto).
                                                 Pure strict query consumed by recipients.allowed before core targeting.
                                                 The owner's universal sight/effect rule overrides the former True
                                                 visibility exception: True never admits an unseen non-attack target.
                                                 Any False wins; invalid replies raise. True never bypasses active
                                                 creature, target-kind/team, range, Charm, hearing, condition or
                                                 recipient_allowed restrictions. Never mutates shared observations.
                                                 Menus and accepted-intent regeneration use recipients.allowed;
                                                 no subscriber leaves the shared targeting policy unchanged.
  recipient_allowed(engine, actor, target, action) -> None or bool, pure strict veto.
                                                 combat.recipients.allowed is the shared creature-target contract:
                                                 active/team/self, range, charm, required conditions, hearing,
                                                 sight, then owned plug-in restrictions. True cannot broaden core
                                                 legality. It excludes activation/economy/cost/readiness checks.
                                                 Native entity menus and attack_declaration.can_target share it;
                                                 this includes SELF and the creature branch of SELF_OR_CELL.
                                                 Cell-only candidates keep their separate geometry contract.
                                                 ANY_CREATURE opts into a team-neutral creature domain;
                                                 harmful=True keeps charm safeguards for harmful uses.
                                                 Hearing, visibility, range and plug-in vetoes still apply.
                                                 Existing target kinds and empty subscribers are unchanged.
                                                 Imperial Kneel uses explicit evented understanding records:
                                                 setup asks the owner; AI defaults to unknown and only targets
                                                 confirmed enemies. Manual commands can confirm missing facts.
                                                 Pair's Following Strike predicate lives only in its plug-in.
                                                 can_target(engine, actor, target, source_id, typed_profile=...,
                                                 range_ft=...) accepts the actual generic-reaction attack profile
                                                 on a transient copy, rather than its SELF activation descriptor.
                                                 Unknown sources require a supplied profile. Callers must supply
                                                 the reaction's range; no profile/catalog mutation or persistence.
                                                 Forced redirection has distinct rules and keeps its old behavior.
                                                 Unowned restrictions return None; no new effects, events or rolls.
  technique_cost_floor(engine, actor, source_id, listed, reduced) -> None or {resource_id: minimum_cost}.
                                                 Pure strict query; listed and reduced are read-only totals.
                                                 Each subscriber sees the same proposal, and maximum floors
                                                 combine after reductions/surcharges. Only listed resources,
                                                 nonnegative integers, no booleans. Cannot lower a proposal.
                                                 engine.effective_costs(actor, source_id, listed_costs,
                                                 reduced_costs=...) returns ordered (resource, amount) pairs.
                                                 Native affordability/payment and Blossom use this query;
                                                 older post-use Qi discounts bound their refund through it.
                                                 technique_costs.refund records cost_source_id on its gain,
                                                 so multiple refunds cannot collectively cross a floor or
                                                 refund more than the listed payment. Ordinary gains retain
                                                 their old payload. Refund timing itself remains post-use.
                                                 Querying never spends/consumes or mutates action metadata.
                                                 No answer = identical cost rows/events. Discount providers
                                                 retain printed costs separately and must use the same quote
                                                 for availability and payment. No ability-specific core rule.
  save_bonus(engine, target, ability, dc, source_id, intent) -> None or signed int (not bool). Pure strict query,
                                                 summed once into the native saving-throw modifier before the
                                                 d20 draw. Covers typed, legacy and Concentration saves. Does
                                                 not alter DC, mode, auto-failure or post-roll reaction order.
                                                 Current source/roller/named context is available through
                                                 engine.d20_context(); intent may be None. Explicit save/checkpoint
                                                 source actors take precedence over a known action's owner; an
                                                 unknown source stays unknown, never the current-turn actor.
                                                 Damage-triggered Concentration carries the actual damage actor
                                                 and damage_source_id through that same temporary context.
                                                 Existing typed
                                                 `save` DC adjustments stay separate: register a contribution
                                                 at one hook only. No subscriber/None = exact old bytes/draws.
                                                 Invalid returns reject the surrounding transaction.
  save_rescue_abilities(engine, target, row) -> None or a non-empty iterable of ability codes. Strict transactional
                                                 callback, run by combat/typed_reactions.py `on_save` once per
                                                 save_rescue row of a FAILED saving throw, before the ability test,
                                                 and only for a row compiled with `choose_one` (the block printed
                                                 "Choose one ..." and the sheet records no pick). Return the ability
                                                 codes this fighter's own choice covers; None or empty keeps the
                                                 compiled default, so a fight with no provider resolves byte for byte
                                                 as before. The row's `choices` carries every printed option and its
                                                 `abilities` the compiled stand-in. Answering a player question here
                                                 is allowed (the run is transactional and inside the save's own
                                                 transaction); remember the answer through an existing evented
                                                 persistent mechanism so it survives turns, commit and reload.
                                                 Default inert. Current owner: combat/ext/defensive_disciplines.py
                                                 (the Path "Choose one Defensive Discipline" menu, read from the
                                                 feature's own printed text).
  Hit Point maximum: combat.maximum_hp.change/bind/expire record MAXIMUM_HP_CHANGED.
                     Signed keyed adjustments recompute from a stable base, minimum one;
                     current-HP deltas and expiry floors are explicit. Condition-instance
                     binding expires on CONDITION_REMOVED. Unrelated adjustments survive.
                     Empty fields are omitted from old state serialization. No implicit healing.
                     maximum_hp_riders captures Analyze eligibility before damage; prior knowledge
                     is queried/recorded through mind_hidden_eye.known_characteristic/record_characteristic.
                     Recording requires explicit confirmation or an actual information result;
                     Analyzed alone is not knowledge. AI declines unconfirmed knowledge and meals.
                     maximum_hp_riders.max_hp_loss(engine, target, amount, source, name=, key=) is the shared
                     "reduce current and maximum Hit Points by N until you finish a Long Rest" step: it keys one
                     signed adjustment to its own condition, never takes a living target to 0, and stacks rather than
                     doubling (a fight contains no rest, so the reduction lasts the rest of the fight).
                     Used by combat/ext/unmaking_forms.py (unmaking_max_hp_loss) and unmaking_channels.py
                     (a printed price of {"max_hp_loss": n}).
                     life_state.is_deceased includes evented finalized death; inactivity alone is
                     nonlethal defeat. Post-hit reductions never restore HP to an unconscious target.
  hit_snapshot(engine, actor, target, attack_context, intent) -> None or namespaced JSON receipts.
                  Pure query before damage; duplicate namespaces reject. No reply is inert.
  hit_final(ctx, target, kind) -> None. Receives ctx.attack_damage_context and ctx.hit_snapshots
                  after resolution, restored in finally. Without an owning rider it is inert.
                  Shared with the fixed round7 Aegis seam, including post-terminal delivery.
  stand_allowed(engine, actor) -> None/True or False. Pure strict query; any False prevents standing.
  stand_cost(engine, actor, normal_cost) -> None or nonnegative integer. Pure strict query;
                     the lowest cost wins, bounded by the ordinary half-Speed cost.
                     Without replies the ordinary rule is unchanged. combat.posture.stand_up
                     is the shared transition; explicit abilities may supply a cost and ignore
                     zero Speed, but never a standing veto. Removes all STAND_UP conditions,
                     pays movement once and records STOOD_UP for event subscribers/replay.
                     Rejected standing has no events, cost or condition changes.
  Jump queries (combat/flight.py jump_score, read by jump_steps and jumps): the only two places
                     that decide how high a creature may jump.
    jump_ability(engine, actor)    -> None or "STR"/"DEX", the ability score that measures this
                     creature's jump height and distance instead of its Strength ("You may use
                     Dexterity instead of Strength when determining jump distance or height").
                     The last answer wins; a score the actor does not carry reads as Strength.
    jump_bonus_ft(engine, actor)   -> nonnegative integer feet added to the height that score earns,
                     before the running-start division into whole 5-foot steps (so +5 feet is one more
                     step from a run and half a step otherwise). Non-integer answers are ignored and
                     the highest integer counts. Both hooks also answer the minimum 14-score ascent
                     gate in flight.jumps: that gate is measured with the substituted score when
                     jump_ability answers one, and a positive jump_bonus_ft answers it on its own,
                     because such a printed increase is granted independently of the score ("does not
                     depend on Strength, Dexterity, or remaining movement").
                     Both are pure strict queries called once per jump quote and once per executed
                     jump path: no reply, a fighter with neither, and every saved fight compiled
                     before the rows existed jump, move and replay exactly as before. Neither hook
                     stores an ability id, grants a move or changes Speed, movement budget or terrain.
  Native turn intent: an accepted END_TURN keeps engine._active_intent and its action source through
                     end_turn, turn_end and turn_start callbacks. _active_turn_advancing marks only that
                     transition; prepared actions retain their existing action-event trigger scope.
                     Both references/flag clear on success, error or pause; direct system end_turn calls
                     inherit no previous request. Start-of-turn choices use the accepted intent directly.
                     This replaces ext/turn_intent.py; no persistent state or new events.
  resource_gain_allowed(engine, actor, resource_id, amount, source_id) -> None/True (allow) or False (veto).
                                                 Denial text uses resource_labels.resource_name; the retained GM_RIDER
                                                 receipt marks automated=True so the feed states the denial plainly,
                                                 not as an unimplemented rule. Older unmarked receipts retain their text.
                                                 Strict pre-mutation gate for every native resource gain. Any False
                                                 vetoes; other non-None types raise. Veto records a GM rider and no
                                                 RESOURCE_GAINED. Existing no_cp_regain condition data also denies
                                                 positive core CP gains here, including direct plug-in/legacy calls.
                                                 No subscribers/denying condition = exact old resource behavior.
  General compiler modifier options may overlay damage_die_steps, add_range_ft,
  add_area_ft or replace_cost. Dice steps affect damage only; area growth keeps
  the original shape and never invents an area. replace_cost substitutes a named
  prepared resource before affordability/payment; no post-use refund is needed.
  Without the optional modifier the original action and its costs stay unchanged.
  Native granted movement: granted_movement.candidates uses ordinary footprint,
  terrain, dragging and positive Speed checks.
  Menus use observed occupancy and voluntary_movement.destination_allowed, the
  shared pure native Frightened destination filter. OA immunity never waives it.
  Authoritative native step execution records unseen contact without moving in.
  (Whole-path and visibility semantics remain the separately tracked safety item.)
  The optional granted_ft budget and ignore_oa_from tuple retain ordinary movement allowance;
  the MOVEMENT_COMMITTED event has cost_ft=0 and granted_cost_ft for the distance.
  Omitted options keep ordinary movement, reactions and event payloads unchanged.
  Alchemy's rider_step effect uses this contract instead of temporary actor flags.
  rider_step rows (combat/ext/rider_step.py) take two optional keys that change only
  the question a player is asked, never what moves: ``trigger`` is the plain-words
  phrase that stood the step off, used instead of repeating the step's own name in a
  Reaction's question ("after the melee attack that missed you"), and
  ``no_oa_from_target`` says out loud that only the triggering creature's Opportunity
  Attack is suppressed, which is what a row without ``no_oa`` already does. A row using
  neither behaves exactly as before. The shared reaction teleport
  (combat/ext/teleport_steps.reaction_teleport) reads the same ``trigger`` key for its
  own question. Both prefer the action actually in flight, read through
  combat/ext/trigger_source.action_name (that creature's accepted candidate this
  transaction, else an attack that creature rolled inside the resolution being
  answered right now -- scoped to the engine's open transaction, never an earlier
  turn's attack): the question names the real action and its user, and the row's
  ``trigger`` is the fallback whenever no such action is in flight (an ability's own
  turn, or a question asked outside a resolution). A row with no ``trigger`` is not
  inert: both callers read the in-flight action unconditionally, because a question
  that misnames its own trigger is worse than one that repeats a printed phrase;
  ``trigger`` only decides whether the row's own words are kept beside it. No state,
  no event and no dice either way.
  Secondary typed saves may carry Context.save_geometry = {origin_ids, range_ft}.
  The original action/owner stays unchanged; range revalidation uses those current
  origin positions after a save reaction and the geometry is included in the
  transient checkpoint context. Ordinary saves omit it and keep their old bytes.
  Lightning Chains uses this for its secondary creature, through the shared Arc
  ledger in ext/arcs.py; no origin or ledger is persisted as an actor mutation.
  Native nested event consumers: Black Sun consumes its spend condition before
  damage, Lightning Chains removes the exact pair before snap damage, and Beast
  Tamer removes only its recorded control instances after allied damage. Each
  registers event(..., nested=True); ordinary actors return immediately. Damage
  goes through native typed effects and reactions, never a deferred GM wrapper.
  Action payment rechecks active/life state and action-denying conditions after
  event subscribers finish. An incapacitated payer keeps the spent costs and
  economy, receives a readable log entry, and skips effects and completion riders.
  Paid reactions reserve their Reaction before payment opens nested checkpoints.
  activation_payments.reaction_completed(engine, actor, source, consumes_reaction=True)
  rechecks active/life state and incapacitation; reaction-only denial applies
  only when consumes_reaction is True. It does not consult
  the already-spent reaction_available flag. False records interruption and keeps
  consumed resources/economy; generic, typed, legacy and Fire Ward callers skip
  effects/reductions/resolution. Eligible payments add no events; no-cost generic
  riders retain their existing semantics. Plug-ins supply the payment consequence.
  technique_final(ctx)                        -> None. Strict callback after a normally resolved typed technique,
                                                 even when its effects ended combat; retains that activation's Context
                                                 and outcome cache. May run explicitly chosen final typed effects via
                                                 run_effects. After a terminal result, saves against active subjects use
                                                 the shared save/defense/choice pipeline; new attacks stay suppressed.
                                                 Never called on failure, pause or canceled technique start.
                                                 Alchemy uses this for Bitter Dregs backlash and Formula Intensification,
                                                 including terminal outcomes. Activation accounting stays in ctx.damage_cache.
  damage_roll_bonus(ctx, effect, kinds)        -> int or None; adds to a real typed damage die roll before its shared
                                                 area cache is filled. Fixed amounts are unchanged. An owned subscriber
                                                 accounts for its own once-per-activation limit in the transient cache.
                                                 effect is None for the ONE set of dice an attack sequence shares across
                                                 every strike and target, and that dice is shaped before any of them is
                                                 rolled, so a per-attack bonus belongs in attack_damage_bonus instead.
                                                 For a row that offers a CHOICE of damage type ("6d8 Radiant or Necrotic
                                                 damage, your choice") kinds lists every option, while
                                                 engine._typed_pending_damage_type holds the one the dice will carry: read
                                                 it instead of kinds when the printed rule is about the damage actually
                                                 dealt. Both hooks see that value, and it is restored at once.
  damage_dice_reroll(ctx, effect, kinds, dice_count) -> int or {"reroll": int, "bonus": int} or None; how many of this damage
                                                 packet's own dice the owner rerolls and then uses the new rolls for
                                                 (typed_executor._rerolled_damage_dice), and optionally a flat amount to add to
                                                 the same packet when the reroll was taken. Called once per packet, after
                                                 damage_roll_bonus has shaped the DiceSpec and before the packet is rolled, so the
                                                 two compose on the same roll; dice_count is what the packet actually rolls. An int
                                                 is clamped to it, and the largest count and bonus win. The replacement dice come from
                                                 the same deterministic stream and die size, are recorded as their own DAMAGE_ROLLED
                                                 roll (a replay draws exactly what the fight drew) and replace that many of the
                                                 packet's lowest dice. Fixed damage has no dice and is never asked. The consumer owns
                                                 whatever the reroll costs ("spend 1 Forge Mark"); answering both halves in one
                                                 dict keeps a cost paid once. No subscriber means no extra draw, no event and no
                                                 saved-state field. Seven-Hammer Revision uses it.
  attack_damage_bonus(ctx, target, effect)     -> int or None; adds to one attempt of a typed attack's damage packet,
                                                 with that attempt's real target, before its resolution. Runs once per
                                                 strike and per target, so a retarget, a second target and a second
                                                 strike each add their own. The consumer may reserve its bonus and release
                                                 that reservation on a miss. No subscriber means identical dice and damage;
                                                 neither hook spends resources.
  Shared rider gate (not a hook): typed_executor.on_hit_rider_available(engine, actor, key, turn, target_id)
                                                 -> bool, a pure eligibility query for a bound later-hit rider.
                                                 typed_executor.spend_on_hit_rider with the same arguments -> bool;
                                                 returns False if already spent, otherwise records the existing string
                                                 turn flag and the transient resolution-moment guard. Ordinary on-hit
                                                 packets and roll_modifiers use this one gate. A miss does not spend it;
                                                 no qualifying rider means no call and no state change. The moment set
                                                 is cleared after resolution and is never persisted.
                                                 roll_modifiers.fold_confirmed_rows(ctx, target, rows) uses the same
                                                 eligibility and clock reservation for configured and paid-hit
                                                 loadouts. Their confirmed_hit_roll_bonus providers resolve consent
                                                 and payment before rolling damage; misses never reach this path.
                                                 attack_result consumes clocks for the actual redirected recipient.
  deal_bonus(ctx, subject, amount)              -> int or None; adds to ONE recipient's damage, after its roll and before
                                                 its save/Evasion division and the commit. amount is the full roll;
                                                 delivery divides the combined roll and bonuses once, rounding down.
                                                 The general seam for a printed bonus that names a single
                                                 creature and therefore cannot live in a roll an area shares between all of
                                                 its creatures. The subscriber chooses its own per-recipient limit and may
                                                 spend a gate here, because the creature is only just damaged. Damage from a
                                                 typed attack's own sealed commit does not pass here. No subscriber means
                                                 the amount is delivered as rolled with its recipient's save/Evasion scaling.
  after_save_resolved(ctx, subject, ability, named, failed) -> None; final typed save outcome after outcome rewrites,
                                                 before on-fail/on-success effects. Observers may retain transient outcome
                                                 accounting. No subscribers = no state or event changes.
  Pressure Points consumers: owned pp_patient_hand restores absent Focus at resolution_final after an actual
      Dodge/Search/Study Action only with a perceived hostile within 30 feet. Old regain_focus rows retain their
      sealed Dodge behavior. New shi_pp_point declarations may seal point_effects: Weak Pulse uses the shared
      healing intercept, Breath-Catching the next Concentration save, and Speech-Knot the existing prepayment
      voice gate. Rows without point_effects retain legacy authority-backed delivery. No owned row = no changes.
  resolution_final(engine, actor, action, candidate, intent) -> None. Strict callback after an accepted Action or
                                                 Bonus Action resolves normally, including terminal outcomes (excludes
                                                 Ready declarations). Runs after technique_final for typed actions.
                                                 Choose one owning callback per rider; registering both duplicates it.
                                                 Both final callbacks run inside the native transaction, in registration
                                                 order. Evented costs, damage, active-subject saves (including their
                                                 outcome effects) and legal movement may finish under the scoped
                                                 _final_rider_active flag. Saves use the shared save/defense/choice
                                                 pipeline; attacks remain suppressed after a terminal result. Before
                                                 combat ends, ordinary typed attacks may resolve here (Court's one
                                                 Unarmed Strike as part of Dodge), before action-completed responses.
                                                 The callback itself grants no economy or attack allowance; an owning
                                                 consumer must enforce its printed eligibility and count.
                                                 A declared result is never
                                                 cleared or rewritten; movement still validates life/speed, path,
                                                 budget and hazards.
                                                 Errors/pauses roll back; the flag always unwinds. No subscribers = no
                                                 new events or ordinary post-terminal execution. No callbacks on errors
                                                 or pauses; action-level completion can include a consumed/canceled
                                                 technique, while technique_final requires its typed effects to resolve.
  hit_snapshot(engine, actor, target, attack_context, intent) -> None or namespaced JSON receipts.
                  Pure query before damage; duplicate namespaces reject. No reply is inert.
  hit_final(ctx, target, kind) -> None. Receives ctx.attack_damage_context and ctx.hit_snapshots
                  after resolution, restored in finally. Without an owning rider it is inert.
                  Shared with the fixed round7 Aegis seam, including post-terminal delivery.
  zone_recipient_allowed(engine, zone, actor, spec) -> None/True or False. Pure strict query;
                  narrows zone triggers, ongoing inside rules and dictionary terrain rules.
                  Absent replies retain the existing team rules. A difficult-terrain mapping
                  uses the same who/eligibility schema as triggers. No mutation or new events
                  occur for default rules. Condition rules healing_denied/temp_hp_denied are
                  enforced at native recorded healing and Temporary HP grants, respectively.
  Death-prevention suppression (AUTO22, Death): a condition may carry the rule
                  death_prevention_denied (rules row "no_death_prevention"), and while it is on a
                  creature nothing that would keep it above 0 Hit Points is offered to it: the
                  would_drop plug-ins (Standard Cannot Fall) are not run, and a generic
                  drop_to_zero / ally_drop_to_zero row that carries hold_at_1hp or Temporary Hit
                  Points is skipped (combat/typed_reactions.py _offer_drop_to_zero_or_bloodied).
                  Printed as "cannot benefit from an effect that would prevent it from dropping to
                  0 HP" (No Return Edict). General: any condition may carry the rule, the key is
                  inert without it, and no saved field was added -- it rides the condition's own
                  "rule" data. Forced movement and teleports carry no such provider. A printed
                  "the FIRST death-prevention effect ... until the start of its next turn" needs a
                  per-creature first-use ledger the engine does not own, and stays Game Master text.
  Event callbacks also receive source_definition_id in kwargs, copied from the
  actual recorded event (including positional native calls); no log scan is needed.
  typed_reactions.checkpoint_response / commit_checkpoint_response are public
  shared helpers for owned reactions moved to another native checkpoint; they
  retain saved row costs, limits and plans. Eligibility never spends or consents.

  damage_reduction_bonus(engine, owner, protected, attacker, reaction_row) -> None or nonnegative int.
                                                 Pure strict query, added once to a damage_modifier reaction's
                                                 numeric reduction. Attacker may be None. No answer is inert.
  final_damage(engine, target, amount, damage_type, source_id, source_actor_id, intent)
                                             -> None or {amount?: int, hp_floor?: int}. Strict transactional hook
                                                 after all defenses/reactions, before temporary HP and HP commit.
                                                 Every native damage packet reaches it, including runtime/legacy,
                                                 zero damage and intent=None. Each subscriber sees the same defended
                                                 amount; minimum returned amount and maximum floor combine. Amount
                                                 must be 0..defended and floor 0..maximum HP (no booleans). A floor
                                                 never heals; temporary HP absorbs normally first. Invalid returns
                                                 or pauses unwind the transaction. No subscribers = exact old damage.
                                                 engine.damage_context() returns immutable AttackDamage for an
                                                 explicitly confirmed attack packet (source/attacker/target,
                                                 index, roll ID/natural/total/critical, explicit kind and
                                                 component primary/rider), otherwise None. Unknown kinds stay
                                                 other; typed on-hit packets carry component=rider. Native
                                                 and portable attacks supply it; typed on-hit damage and rays
                                                 forward it explicitly. Nested non-attack damage clears it;
                                                 outer context restores on success, error or pause. Metadata
                                                 is never saved, inferred from recent events, or inherited by
                                                 a different packet. Existing callback arguments are unchanged.
  damage_floor(engine, target, amount, damage_type, source_id, source_actor_id, intent)
                                             -> None or integer HP floor (0..maximum HP, not bool). Strict
                                                 transactional checkpoint after ALL final_damage reductions
                                                 and floors, before HP commit. Subscribers see the same final
                                                 amount; the highest floor wins, cannot heal, and respects
                                                 temporary HP. None/zero leave damage unchanged, including
                                                 overkill accounting. Merciful Hand owns only
                                                 lethal primary unarmed packets; its four choices and absent
                                                 Focus recovery share rollback. This separate phase avoids
                                                 asking to spare a blow another defense already made nonlethal.
                                                 Iron Marrow Sutra also uses this phase for its optional
                                                 once-per-round survival save, including intent=None packets
                                                 with an enclosing action. It is no longer a would_drop
                                                 subscriber; nonlethal defended packets never spend an attempt.
                                                 Its priority 10 runs after default-priority nonlethal choices
                                                 regardless of plug-in import order; accepted primary-packet Mercy
                                                 skips the redundant rescue, while separate rider packets still qualify.
                                                 Typed condition effects may set condition_label (a string)
                                                 for a readable persistent pill; omission preserves old data.
                                                 granted_movement.candidates supplies legal separate-budget
                                                 moves; _resolve_movement(..., granted_ft, ignore_oa_from)
                                                 rechecks Speed, terrain, drag and reactions, exempts only the
                                                 named reactors and leaves ordinary movement unspent. Defaults
                                                 preserve normal movement and opportunity attacks byte-for-byte.
  reaction_reduction_carried(engine, target, feature_id, absorbed_amount) -> None;
                                                 strict notification after a tagged flat budget absorbs a later
                                                 packet of the same attack. Integers only. Owning consumers may
                                                 record total prevented damage for follow-up effects; return
                                                 early for other features. A feature tag may be a string receipt
                                                 identifying an owning actor and exact stored condition instance
                                                 (Winter Stores); consumers must not credit other instances.
                                                 With no consumer it is inert.
  confirmed_hit_roll_bonus(engine, attacker, target, spec, intent, source_id) -> int or None.
                                                 Strict confirmed-hit query from critical_attacks.resolve before
                                                 rolling damage. Adds to the original damage modifier; owning
                                                 loadouts resolve consent/payment and share roll_modifiers clocks.
                                                 Misses never call it. No subscriber leaves damage unchanged.
                                                 target is the confirmed recipient after redirection; source_id
                                                 binds the scoped typed action even if its attack spec was copied.
  fresh_zero_hp(engine, target, attacker_id, source_id) -> None.
                                                 Strict notification of a positive-to-zero HP transition from
                                                 pending_damage.hp_before, regardless of dying/removal. Existing
                                                 watch/own/nearby triggers share defeat-chain deduplication.
                                                 Damage at zero and later death do not notify; healing permits
                                                 a fresh transition. No owned trigger adds events or state.
  censure_damage_component(engine, attacker, target, attack_context, intent) -> None.
                                                 Owning Censure delivery during positive DAMAGE_COMMITTED, after
                                                 the first packet's own zero-HP settlement (the checkpoint runs at
                                                 event priority 100, the lifecycle observer at priority 0).
life_state.additional_hit_component shares defended HP excess
                                                  across components without additional death failures, and a hit
                                                  whose death an owned rule already prevented stays prevented for
                                                  the rest of that same hit, including across unrelated nested
                                                  damage resolved inside it. Only a packet tagged with
                                                  life_state.HIT_COMPONENT_FLAG
                                                  shares that accounting; unrelated nested damage keeps its own
                                                  lifecycle. No Censure condition means no subscriber work.
  attack_packet_start(engine, target, amount, attack_context) -> None.
                                                 Strict callback before an attack packet's defenses and HP commit,
                                                 including zero/immune packets. amount is the incoming integer amount
                                                 (primary damage has rolled, but defenses have not yet applied);
                                                 attack_context is immutable AttackDamage provenance. Runs for native
                                                 and typed attack components; consumers select their own component and
                                                 ownership. Only a packet matching all three provenance IDs dispatches.
                                                 May deliver an attached damage type through ordinary effects.
                                                 Nested packets restore attack provenance; pending HP/resource snapshots
                                                 are captured afterwards. Pauses/errors roll back. No subscriber is inert.
  attack_damage_final(engine, attacker, target, attack_context, intent) -> None.
                                                 Strict transactional callback after all packets attached to one
                                                 typed, native or portable attack, including late on-hit bonuses, before the next
                                                 attack. attack_context is its immutable AttackDamage provenance.
                                                 Shared seam for post-attack movement and other completed-attack
                                                 riders. Default inert. Pauses/errors roll back. Native notification
                                                 dispatch calls it after after_hit riders, with portable resolution
                                                 forwarding the same explicit provenance used for damage; typed execution calls it
                                                 after its late bonuses. Never infer completion
                                                 from recent damage events or use the action boundary instead.
  button_selection(action_parameters)        -> {condition, equals?, contains?} or None; a read-only selector for standing
                                                 picks held together in one condition, including older saved bundles.
  setting_lifetime(action_dict)              -> plain lifetime/restriction string or None; pure read-only query for
                                                 free/self setting rows lacking parameters.setting_lifetime, including
                                                 legacy sealed catalogs. Owning plug-ins gate on their selector metadata.
                                                 No answer retains the default free/changeable choice text; explicit
                                                 metadata takes precedence. Never modifies the action or fight state.
  button_description(action_dict)            -> plain description or None; read-only presentation text for engine-made
                                                 buttons whose generic builder lives outside their owning plug-in.
                                                 action_text scopes setting_only selectors through option_text using
                                                 shape_talents, augment_key, attack_modifier_setting.modifier and typed
                                                 source/option_of/forged_from IDs, then exact printed option names.
                                                 Option rules precede one free-choice lifetime line; other rows are inert.
                                                 Ambiguous printed names use effect-type source metadata in
                                                 combat/rules/option_text_sources.json; the builder exports exact scoped
                                                 owner text without adding executable mechanics or changing grants.
  status_description(engine, holder, row, data) -> {text?: str, rules?: str, duration?: str, paying_pool?: str, handling?: str,
                                                 source_ability?: str, applied_by?: str, display_name?: str} or None;
                                                 Setting selectors reuse tabletop.setting_button_description for buttons
                                                 and stored pills; queries remain pure and inert for other sources.
                                                 An unambiguous named printed subsection scopes a selector's rules;
                                                 generated parent-feature fallbacks defer to that scoped reading.
                                                 pure presentation query (holder may be None for a map area).
                                                 Optional display_name replaces the presented pill name without mutating
                                                 saved state; absent/empty preserves the original label. Used for live deadlines.
                                                 row is a copied table condition/zone/resource projection; data is a
                                                 copy of its stored data. Supply specific rules and/or automation
                                                 and, when needed, a plain-language duration override for this row;
                                                 wording only for state the plug-in owns; return None otherwise.
                                                 rules replaces generic readings with retained source-backed prose;
                                                 text adds to them. paying_pool is the retained resource id (empty
                                                 means unavailable), used to explain CP without guessing a pool.
                                                 Optional markup is the same replacement rules with their printed
                                                 "**Label:**" fields and headings intact. When supplied and it
                                                 yields labelled fields it becomes this row's displayed card, so the
                                                 source record the replacement superseded is not shown beside it;
                                                 the flattened rules it covers are dropped from the body only, and
                                                 rule_text keeps them. Without markup the replacement's prose is
                                                 carried by the body exactly as before.
                                                 Provenance overrides must come from retained action ownership/data,
                                                 not guesses (some bookkeeping instances are filed under their holder).
                                                 No handler leaves generic printed/data descriptions unchanged.
                                                 Never mutate engine state, rows or data; never resolve effects.
                                                 Dispatched with query(): failures log on the server, never create
                                                 fight events (unlike run()'s observational failure reporting).
  uncommanded_summon_turn(engine, actor) -> None;
                                                 transactional behavior for an active, uncommanded summoned creature,
                                                 after start-turn reactions/zones and before its default Dodge; handlers
                                                 must be inert unless the actor's saved summon policy opts in.
  decision_text(engine, context, printed_rules) -> dict or None; pure presentation metadata for an owned reaction/choice/
                                                 Ready prompt. Optional feature_id, name, trigger, rules, summary, cost, limits, table_note,
                                                 option_descriptions (option id -> plain effect text). printed_rules is
                                                 the read-only owner text by mechanic id. Strings only;
                                                 rules may supply retained source-backed prose when no extracted
                                                 record exists. No mechanical rules, events, answer keys or fight state changes. No result leaves
                                                 the general printed-rule/compiled-cost builder in charge. Return early
                                                 unless this plugin owns the feature or prepared option in context.
  directional_cover(engine, attacker, target, ray) -> 0 | 2 | 5 or None. Pure strict query for each clear footprint
                                                 sight line, for melee and ranged attacks. ray contains start/end cells,
                                                 ranged, and ordered crossed_edges ({cell:[x,y], edge:N|E|S|W,
                                                 direction:enter|exit}); y increases south. Exact center-to-center
                                                 geometry: vertex crossings count both departure/arrival edges, not
                                                 merely grazed cells. Best cover per ray, then least covered clear ray;
                                                 ranged terrain combines per ray, global cover remains a lower bound.
                                                 Plugin owns facing/ability eligibility. No hook = legacy cover exactly.
                                                 ray.attack is an immutable attack_provenance.describe value: actual
                                                 source_id, parameters, typed metadata, effect (when known), delivery,
                                                 weapon_source_id and opportunity_of. Native/roster/Opportunity
                                                 packets and typed rolls pass their own spec; unknown stays unknown.
                                                 It never calls d20_context or reads the selected primary action.
                                                 ray.tactical marks a prospective cover query: target is a position
                                                 copy, and no scopes/state are changed. tactical_cover accepts explicit
                                                 ranged descriptors or possessed catalogue attacks and credits shelter
                                                 against eligible in-range threats, preserving the map baseline. No eligible
                                                 provider means identical legacy cover and candidate metadata.
retarget_attack(engine, attacker, defender, intent, context) -> None or {source_id, target_id, cover_bonus: 0|2|5}.
                                                  Once per declared attack before defender hooks/d20. Strict single owner;
                                                  context supplies source_id, attack_index, range_ft and typed effect.
                                                  Core validates an active non-self creature in sight/range; ally targets
                                                  are allowed for interception. Plugin owns eligibility/consent/costs.
                                                  ATTACK_RETARGETED records original/effective target and cover for this
                                                  attack only. Damage and on-hit effects follow the effective target.
                                                  No result leaves the exact legacy path; choices use choice_options.
                                                  The single owner (ext/redirection.py) answers it from two registries, in
                                                  this order: ``constraint(priority)`` first, for a printed rule about what
                                                  the *attacker* may declare (its own saving throw, its own declared target),
                                                  then ``provider(priority)`` for a rule that answers for the *defender*
                                                  ("redirect the attack to yourself"). Winning the constraint stage ends
                                                  that stage for this attack: no other constraint is asked about the same
                                                  declaration, so an attacker's own printed save is run once and its
                                                  once-each-turn clock is spent once, and a provider's answer cannot re-aim
                                                  an attack ahead of the attacker's own printed constraint. A constraint
                                                  returning None leaves the declaration alone and the providers answer as
                                                  before. Priorities count within a registry only. Both registries empty =
                                                  the legacy path. What a constraint's answer does not do is delete the new
                                                  target's own defences: the providers are then asked with the creature the
                                                  answer names in place of the declared defender, so a re-aimed attack still
                                                  meets that creature's printed defensive redirection (Reactive Cover
                                                  "when targeted by an attack roll", Defensive Rider "when an attack targets
                                                  your mount") and still answers for it.
  zero_hp(engine, target, damage_source_id, intent) -> "DYING" | "STABLE" | "CONSCIOUS" or None. One strict opt-in owner, after
                                                 damage reaches 0 HP and before default defeat/removal. Retains active
                                                 map occupancy and the team's chance to recover. DYING/STABLE disable economy,
                                                 movement and concentration; CONSCIOUS retains them. LIFE_STATE_CHANGED replays the transition.
                                                 _set_life_state(target, "STABLE", source) stabilises; healing above 0
                                                 clears the state without refunding spent economy. _defeat(..., final=True)
                                                 removes the creature permanently. Plugin owns death saves/failures,
                                                 further 0-HP damage and return rules via event/turn hooks. With no plugin,
                                                 core retains the exact default defeat path; unset life_state is omitted.
  prepare_options(engine, actor)             -> list of PreparedOption dicts (option_id, source_id, label, trigger event
                                                 name, JSON data, optional automatic_use=False). Pure, bounded by the
                                                 plugin's owned abilities. Each is a Ready table candidate spending an
                                                 Action now; stored as an evented condition until your next turn starts.
  prepared_trigger(engine, actor, option, event) -> True from exactly one owner when a declared trigger is legal now.
  prepared_action(engine, actor, option, event, intent) -> True from exactly one resolver; strict transactional execution.
                                                 During another creature's turn, an event in an accepted action opens
                                                 a bounded USE/DECLINE table choice. USE removes the preparation and
                                                 spends one available Reaction before dispatch. Decline retains it.
                                                 Plugin owns ability costs/targets/effects; use evented engine methods.
                                                 Nested prepared triggers are suppressed. No options = no new buttons,
                                                 state, or events. Genesis and turn transitions without an intent do not
                                                 trigger preparations; plugins choose action-resolution event checkpoints.
  d20_bonus(engine, roll, intent)             -> None or {source_id: str, bonus: int, user_id?: str}. After rewrites,
                                                 before outcome; composes bonuses without changing natural d20 or mode.
                                                 D20_REWRITTEN (operation bonus) records original/effective rolls.
                                                 Optional user_id names the creature that used the ability, which is not
                                                 always the creature whose roll the bonus lands on; it is validated
                                                 exactly as on d20_result and is recorded only when supplied, so a
                                                 producer that omits it writes the unchanged event shape. Missing is
                                                 inert and the log falls back to the roll's own creature.
                                                 Every d20 passes this seam, so it also reaches saves forced by native
                                                 (non-typed) catalog actions, which the typed-only save hooks cannot
                                                 see. A producer reads engine.d20_context(roll) to learn the kind and
                                                 source, and skips any source whose action is resolution_kind TYPED so
                                                 one roll is never improved by both a typed hook and this one.
                                                 No contribution is inert.
                                                 Court and Serendipity own eligibility, optional consent and saved limits.
                                                 d20_rewrite also supplies printed bonuses on rewritten checks here;
                                                 opposed_save_totals(engine, subject, source_id) is a scoped,
                                                 default-inert request for numeric rewritten-save bonuses for that
                                                 exact subject/source. Bonuses then settle against the final opposing
                                                 total; explicit forced outcomes retain their separate override contract.
                                                 d20_rewrite.Rule.outcome is None (default-inert), "success", or
                                                 "failure": an accepted rewrite explicitly forces that save/check
                                                 result through the typed outcome override, independent of final totals.
                                                 Rule.bonus remains numeric and never implies a forced outcome.
                                                 Rewrite after-riders on that save wait for after_save_resolved's
                                                 final success/failure; owned scratch is consumed before rider dispatch.
                                                 Fixed-DC and nested unrelated saves retain existing behavior.
                                                 absent a matching rewrite is inert. Opposed checks draw both totals before
                                                 invoking rewrite/floor seams with the opponent's total as DC (actor must
                                                 beat it, defender may tie). Defending saves use typed_save_modifiers and
                                                 settle_typed_save shared with block_save, including outcome metadata.
                                                 ext.roll_context.described_d20(engine, description=plain text, **d20_args)
                                                 supplies an optional resolution-local description to roll_description(engine,
                                                 roll) -> str | None. Scoped to engine/actor/reason, restored after nested rolls
                                                 or exceptions; no persisted fields, changed roll reasons or extra events.
                                                 Typed counters/contests and Intercepting Shot use it; absent context is inert.
  d20_result(engine, roll, intent)            -> None or {source_id, operation: "reroll" | "replace", natural_result?, user_id?}.
                                                 Optional user_id names the creature that used the ability, which is not the
                                                 creature whose roll is rewritten when an ally rerolls another's save; the
                                                 fight log reads it as "the user rerolled the roller". It must be a
                                                 non-empty creature entity id or None, and is recorded only when
                                                 supplied, so a producer that omits it writes the unchanged event shape.
                                                 Missing is inert and the log falls back to the roll's own creature.
                                                 Saves also accept optional save_bonus: signed integer added to the
                                                 effective modifier/total before D20_REWRITTEN observers, SAVE_ROLLED,
                                                 rescue reactions and outcome consumers. Other roll kinds reject it.
                                                 Missing/zero is inert. Reroll/replace retain their existing selection;
                                                 plugins implement keep-new/higher/lower/owner-choice and costs.
                                                 After a d20 draw, before attack/save/check consumers; initiative is
                                                 excluded. Exactly one owner, strict transactional errors and choices.
                                                 Replacement is an integer 1..20. Reroll uses the deterministic stream,
                                                 same mode/modifier, with no recursive checkpoint. D20_REWRITTEN records
                                                 original and effective rolls; the caller records/uses the effective roll.
                                                 Plugins own eligibility/costs and use choice_options for table consent.
                                                 No answer means no new events, draws, state or serialization changes.
                                                 engine.d20_context(roll) supplies native read-only metadata: kind,
                                                 actor_id (roller), target_id, ability/skill, dc/ac, source_id and
                                                 source_actor_id, triggering_action_id and triggering_actor_id,
                                                 typed named outcomes, attack_index and scalar attack spec. Unknown
                                                 values are None. Attack target follows redirection; AC uses the same
                                                 current defense query as hit resolution. The original 3-argument
                                                 callback remains compatible. Metadata is ephemeral, never saved.
                                                 _roll_save accepts separate roll_context metadata (caster/named),
                                                 without changing choice checkpoint packets. Native save/attack/check
                                                 callers own d20_scope(context); direct plug-in draws may use it too.
  roll_context_end(engine, context)          -> ignored; observational scratch cleanup when a native d20 scope exits,
                                                 including early escape, error or pause. Must not ask choices or change
                                                 fight state. The context stack is restored before dispatch; nested
                                                 scopes and preview clones have separate stack ownership. No hook =
                                                 no state/events/draws; no callable or runtime object enters a prompt.
  channel_delivered(ctx, target, weapon_id)  -> None, after Ruin Channel consumes its charge and applies its hit damage.
                                                 weapon_id is the delivered External Channel's action id, or None for
                                                 an actual Internal Channel; uncharged attacks never dispatch this hook.
                                                 Shared by Shock and Shred to remember delivery for after_hit_choice.
                                                 Strict transactional notification; no handlers means no state change.
  ruin_backlash(engine, actor, source)       -> None, after rolling each Ruin Backlash, before applying its damage.
                                                 General notification shared by Ruin Form healing locks and damage surges;
                                                 handlers own eligibility. No handlers means no change to damage or state.
  attack_result(ctx, target, hit, critical)   -> None, after each typed attack resolves, before damage_dealt/after_hit.
                                                 Transactional: choices/errors unwind through preview and rollback.
                                                 Covers hits, misses and zero-damage hits; critical means a landed
                                                 native natural 20 from this attack, not an earlier roll. A target's
                                                 event carrying critical_turned_normal=True after that roll clears
                                                 it (Helmet Discipline uses this public event signal). Expanded
                                                 critical ranges need shared provenance; no inferred 19s. No handlers means
                                                 no change. Use for optional hit/critical state benefits without
                                                 requiring positive damage or altering observational after_hit hooks.
                                                 To ask how high the AC this attack really had to beat -- a defence can
                                                 raise it after the roll was written, whether it is a typed reaction row, an
                                                 armor_class modifier or a plug-in's own hit_response -- read
                                                 combat/attack_outcomes.attack_outcome, the one outcome receipt that
                                                 combat/typed_reactions.on_attack_hit publishes for all of them, with
                                                 attack_outcomes.attempt_end as the end of the attempt you are resolving (a
                                                 hit_response that made the attack miss without comparing any AC publishes
                                                 nothing, so its receipt is None).
                                                 ctx.attack_result is the roll's own snapshot and is written before every
                                                 such defence, so it alone cannot answer that. Laughing Theft of Timing
                                                 (combat/ext/monkey.py) is the first consumer.
  attack_resolved(ctx, target, hit, attack_effect) -> None, after one actual typed attack resolves, hit or miss.
                                                 Observational; default-inert. Use compiled provenance to distinguish
                                                 an Attack action from a technique, bonus strike or reaction.
                                                 Context.attack_mode_consumption_pending is True during attack_result
                                                 and primary damage_dealt, until the current roll's attack_mode_vs
                                                 consumption sweep; False afterward, including attack_resolved and
                                                 late attached damage. on_hit_context inherits this transient flag;
                                                 independent contexts default to False. Consumers granting next-roll
                                                 benefits (Help, Vex-shaped riders) can defer only while it is True.
                                                 Provenance alone does not establish this phase. No persistence or
                                                 behavior change occurs without a consumer reading the flag.
  optional_followup_target(ctx, effect, eligible_targets, preferred_target_id) -> target ID, "" to decline, or
                                                 None when the effect is not this consumer's (check effect["type"]).
                                                 Transactional choice seam for typed effects that offer an optional
                                                 follow-up attack. Targets are already filtered for effect legality;
                                                 the preferred ID preserves the old deterministic default. A missing
                                                 consumer keeps that default. Exactly one consumer may answer for an
                                                 effect: a second non-None answer raises. Consumers use
                                                 choice_checkpoints for player-owned choices and return only a supplied
                                                 eligible ID. A decline does not spend the effect's once-per-turn use
                                                 (Cleave: combat/ext/weapon_mastery.py).
  Compiled typed.attack_action marks basic Attack actions (natural attacks and Unarmed Strike options), inherited
  by modifier variants. Consumers must also require ACTION economy and exclude reaction_attack/opportunity_of:
  a bonus/reaction clone is not itself the Attack action. This metadata is inert without an owning consumer.
  Compiled typed.replaces_attack = {"source_definition_id": <replaced action>, "mastery"?: <its weapon mastery>} marks an
  action built to take another attack's place (Combo Maneuvers' Shove/Grapple for the Paired Strike, lane4_dual.py).
  Limits on the replaced attack apply to it too (Nick's once per turn, weapon_mastery.py; weapon hand/readiness
  requirements, equipment_hands.py). Each consumer is inert without this metadata and its own relevant restriction.
  choice_options(engine, intent, checkpoint, reactor_id, choice_id, context) -> ExtensionChoice dict or None.
                                                 A plug-in whose questions ride the shared Needle transport answers for
                                                 its own choice-id prefix with one public call,
                                                 ext.needle.option_spec(choice_id, context, prefix), which reads the
                                                 options, bounds, decline flag and automatic flag that needle.ask
                                                 already published in the trigger context (needle.py owns
                                                 "choice:needle.*"; combat/ext/scoundrel_riders.py owns
                                                 "choice:scoundrel.*"). Any other choice id, or a question nobody put,
                                                 returns None and the table falls back to its ordinary Use/Pass window.
                                                 spend_choice also supports optional pool_name, labels, cost, prompt, payment_note and
                                                 target_id in trigger for non-Reaction payments (Vital Transfusion and
                                                 Demon Bone Regeneration). These describe payment; the caller owns
                                                 eligibility, spending and effects. Defaults preserve damage-soak prompts.
                                                 Optional choice_id in the choice:spend.* namespace labels an Action or
                                                 turn-start payment as an ability choice instead of a Reaction. Omission
                                                 retains the original reaction:typed.* identity and checkpoint contract.
                                                 ext.spend_choice.choose_spend(engine, row, reactor, checkpoint,
                                                 maximum, automatic, trigger) reuses this transport for any typed
                                                 spend-up-to reaction. Returns the chosen integer or 0 on decline;
                                                 non-Ask-me actors retain automatic, and the caller pays/resolves.
                                                 Pure query, one owning plugin: exact option_ids, minimum_selections,
                                                 maximum_selections (0..64), allow_decline, automatic_use and optional
                                                 preferred_option_ids. _reaction_decision(..., context=...) transports
                                                 the answer via embedded choices, cache or preview/provider. Use unique
                                                 checkpoint IDs per triggering attack/save/effect. Context carries the
                                                 actual actor_id, target_id, attack_index/effect/geometry, never callables.
                                                 Selection is bounded, unique and checked again on replay; transport
                                                 never spends a Reaction. Plugin owns costs/legality. No spec = legacy.
                                                 Optional display context from ext.choice_prompt.action_context:
                                                 source_definition_id/action_name, action_actor_id, affected_id (strings).
                                                 Needle/rider_choices prompt_context also accepts cost/paying_pool
                                                 (strings) for the current choice, e.g. a free follow-up of an active
                                                 effect. These only explain payment; they never spend resources.
                                                 Table choices show the triggering action, actor and affected creature;
                                                 AUTO71: a plugin may own its own choice_id namespace and answer this hook for
                                                 it (warleader.SECONDARY_CHOICE "choice:warleader.secondary_standard" is
                                                 the Layered Orders "choose ... one secondary Standard" menu). A plugin that
                                                 answers for its own id is inert for every other choice and every old save;
                                                 it reads the option bounds and labels ext.needle.ask puts in the trigger
                                                 context and, when the fighter's controller is on Auto, skips the question and
                                                 keeps the fixed reading so its saved replays stay byte-identical.
                                                 absent metadata keeps legacy display and decision behaviour unchanged.
                                                 Tabletop Ask me carries this spec and context.labels/context.prompt to
                                                 a bounded checkbox dialog and returns the selected option_ids unchanged.
                                                 A compile_actions passive row may set choice_owner=True to expose player
                                                 decisions during AI turns even without a generic reaction row. The service
                                                 pauses extension choices for that manual chooser; AI choosers stay automatic.
                                                 No marker leaves the existing Ask-me set unchanged (Bojutsu, 2026-09-29).
                                                 A persisted condition's data.choice_owner=1 likewise exposes its
                                                 manual bearer's choices while the benefit lasts (shared dice,
                                                 wards, granted reactions). Expiry/removal ends ownership; AI
                                                 bearers stay automatic. No flagged condition is default-inert.
  condition_choice_owner(engine, actor, condition) -> True or None
                                                 Read-only recognition of a legacy persisted grant's manual
                                                 chooser, before service Ask-me selection. Never mutate saved
                                                 conditions here. None is default-inert; AI stays automatic.
                                                 Shared dice, wards and granted reactions can use this seam.
  Standing one-ability choices (AUTO1 2026-10-04, combat/ext/defensive_disciplines.py)
                                                 A feature_blocks save_rescue spec with "choose_one": true
                                                 prints a build-time "Choose one Defensive Discipline".
                                                 typed_reactions compiles such a row to the single weakest
                                                 ability, so the printed choice used to be made for the
                                                 fighter. defensive_disciplines gives its owner one free
                                                 SELF setting_only initial-build button per printed ability,
                                                 available before spending the first turn's Action and only
                                                 until one choice is recorded. Replacing that choice and
                                                 additional-discipline progression are not supported.
                                                 The buttons are named in the
                                                 player's own words ("Tempered Response: Dexterity (Flowing
                                                 Frame)"), stores the pick as the typed condition
                                                 condition:typed.defensive_discipline:<feature>, and narrows
                                                 the engine-local save_rescue row to it at match_start and
                                                 turn_start and before a real save through save_mode (which
                                                 returns no roll mode). This also restores the chosen rescue
                                                 ability for off-turn saves after cold reload.
                                                 Integers and strings only, so a pick survives a
                                                 table commit and a reload. No recorded pick keeps the
                                                 compiled row untouched; a feature without such a
                                                 block gets no button and no condition. Feature-block specs
                                                 may set optional=true: compile_blocks preserves that general
                                                 metadata so optional paid no-Reaction choices join Auto /
                                                 Ask me plans. Absent metadata is inert for existing rows.
                                                 Save-rescue consent uses the existing transient
                                                 reaction_trigger scope to name its triggering action and
                                                 affected creature; it adds no stored field or answer key.
                                                 Applies to every
                                                 choose_one save_rescue block, so a new Path discipline needs
                                                 only a feature_blocks row. It reads no hook and adds none.
  choice_map_pick(engine, choice, context) -> {"instruction"?: str, "cancel_label"?: str} or None
                                                 Read-only presentation vote that a space choice is picked by
                                                 clicking a square on the MAIN map (owner 2026-10-03, round 24:
                                                 "you can just click on an available square on the grid rather
                                                 than a tooltip"). Consulted once by
                                                 combat/choice_presentation.py map_pick, which attaches the answer
                                                 to the choice as map_pick together with the legal squares
                                                 (choice.options[].cell and map_pick.cells). Arguments: the
                                                 engine, the choice as built (every option already carrying its
                                                 cell) and the same choice context as choice_prompt; return a
                                                 dict to mark it, None to keep the list presentation. It is a
                                                 presentation vote only: option ids, labels, the stay-put option
                                                 and the answer binding are unchanged, so legality and the
                                                 resolution cannot be affected. Only a single-square choice
                                                 (maximum <= 1) is eligible, and only a space choice reaches the
                                                 hook at all. Default-inert: with no answer every choice looks
                                                 exactly as it did, so an older client and a saved fight are
                                                 unchanged. combat/ext/teleport_steps.py map_pick uses it for
                                                 every teleport destination.
  Typed effect contexts preserve explicitly selected ALLY_OR_SELF recipients,
  including the user, for conditions, modifiers and extension effects alike.
  SELF actions retain implicit-user semantics; areas retain their area subjects.

  before_attack(engine, attacker, defender, intent, context) -> {"mode": mode} or {} when used; None on decline/no ability.
                                                 Typed attacks supply their actual action, typed profile and effect in
                                                 context (transient only), including temporary generic reaction actions.
                                                 attack_declaration.can_target queries that strike's targeting without
                                                 rechecking activation costs, economy or spent turn flags. Legacy attacks
                                                 fall back to their catalog action. No hook means no behavior change.
                                                 May also return {"force_miss": True, "source_id": owning_source,
                                                 "label": readable_ability_name}. This applies to exactly this
                                                 attack, including opportunity/typed/portable attacks and native
                                                 defenders. It overrides natural20 without changing the die or AC.
                                                 ATTACK_FORCED_MISS records the cause and roll; hit/damage/riders
                                                 do not run, and after_miss observes the settled miss once. The
                                                 attack still spends its ordinary cost. Consumers own eligibility,
                                                 choices, costs and saves (e.g. failed save -> force_miss, success
                                                 -> DISADVANTAGE). Replies live only in the current packet, never
                                                 actor flags; no reply leaves all previous events/rolls unchanged.
  before_dex_save(engine, defender, intent, context) -> same. Transactional hooks run before the d20 in typed and legacy
                                                 paths. They may request dynamic choices and eventedly move a defender
                                                 off-turn, with no Reaction unless the ability charges one. Exceptions
                                                 propagate to preview/rollback. Core rechecks supplied target geometry:
                                                 leaving an attack makes it miss; leaving a save effect skips that target.
                                                 Unknown save geometry cannot establish escape (movement/mode still work).
                                                 ADVANTAGE and DISADVANTAGE cancel. Decline resumes remaining effects.
  object_targets(engine, actor, action)      -> iterable of RuntimeObjectState IDs, only for actions the plugin
                                                 explicitly allows to affect objects. Pure/additive; action economy,
                                                 costs, range, sight and extant/non-destroyed object checks stay in core.
                                                 No plugin means no object candidates. Actor choices are unchanged.
                                                 Map objects may carry explicit integer weight_lb in component; absent
                                                 weight is unknown (never inferred from size/material). Loose-object
                                                 manipulation uses this metadata; existing damage behavior is unchanged.
                                                 Explicit simple-door metadata uses interaction='simple_door' and
                                                 integer 0/1 door_open, door_locked, door_jammed (all required).
                                                 Only door presets qualify; open state controls the object's wall.
                                                 Missing metadata preserves old maps; no unlocked-state inference.
  object_packets(engine, actor, obj, packets, source) -> None, or {"object": snapshot, "packets": [(amount, kind), ...]}
                                                 before one damage instance on an object is worked out (combat/ext/
                                                 objects.deal): extra packets join the instance and the snapshot (the
                                                 object with the answering plug-in's own component consumed) is what is
                                                 damaged and saved. Fully prevented damage keeps the pre-instance record.
                                                 Rider lane C11: Harmonic Weakness (combat/ext/sound_structures.py).
                                                 Default-inert: no answer changes nothing.
  object_damage_defenses(engine, actor, obj, packets, source) -> None, or [{"kind": "resistance", "damage_types": [...]}]
                                                 once per damage instance on an object, after object_packets and before
                                                 combat/object_rules.py work_out (combat/ext/objects.deal). The object half of
                                                 the creature damage_defenses hook: a Resistance that is not the object's
                                                 own material. Rows use the same defense-row schema; only "resistance" rows are
                                                 read. work_out applies them with ordinary halving, rounding down, the same
                                                 plain-word note and the same suppression by ignore_resistance and by the
                                                 exposure bypass, so they share non-stacking with the object's own resist.
                                                 Default-inert: no answer leaves damage exactly as it was. No new saved field
                                                 or event. Used by Stand Against the Calamity's "structures and Formation
                                                 Anchors inside gain Resistance to all damage".
  object_action(engine, actor, action, object, candidate, intent) -> True when handled, otherwise None without mutation.
                                                 Exactly one plugin owns an object/action combination. Transactional:
                                                 exceptions propagate and roll back. Costs/economy already consumed.
                                                 Use _update_object for evented creation/damage/destruction; its full
                                                 OBJECT_UPDATED record replays through the reducer. Never treat an
                                                 object ID as an actor or apply creature-only effects to it.
  shared_occupancy(engine, left, right)       -> {"rider_id": str, "mount_id": str} or None. Pure query; the plugin
                                                 validates the relationship, willingness and mounting eligibility.
                                                 Core checks exact pair identity, active actors and a strictly larger
                                                 mount footprint. Mutual collision is waived; invariants additionally
                                                 require full rider containment. Every unrelated pair still collides.
                                                 Default: no shared occupancy. No state/serialization changes.
  attack_mode(ctx, target)                    -> "ADVANTAGE" | "DISADVANTAGE" | None, before each typed attack roll
                                                 Executor-installed modes are strike-local: a reach recheck abort
                                                 removes only their IDs, with replayable MODIFIER_REMOVED events;
                                                 pre-existing and nested-reaction modifiers are preserved.
                                                 ctx.attack_effect is the actual strike effect (also for derived sources).
                                                 attack_scope.current(engine) exposes actor/target/source/effect/roll_id
                                                 during resolution, restoring the parent after nested reactions/errors.
                                                 Owners may add namespaced scratch readings to that frame and copy
                                                 them to their Context at attack_roll_finished (e.g. sight at the roll).
                                                 Default-inert: no saved state/events; roll_id is set on ATTACK_ROLLED.
                                                 Triggered actions carry effective range/reach; target_check revalidates
                                                 each strike after movement and defensive reaction checkpoints.
  unseen_ignored(ctx, target)                 -> True to drop the Disadvantage zones.attack_mode gives a typed attack at a
                                                 target the attacker cannot see (heavy obscurement, darkness, an obscuring
                                                 wall); only its "DISADVANTAGE" answer, never a Hidden target's own
                                                 condition (typed_executor.block_attack; rider lane C11: Through the Wrong
                                                 Door). Default-inert: no subscriber, or every answer None, changes nothing.
  attack_roll_finished(ctx, target, effect, roll_id) -> None, when a scoped roll exits, after damage or defense;
                                                 roll_id is empty if no roll occurred. Observational cleanup of an
                                                 owned pending benefit; no owner = no state/events. Parent scope is
                                                 restored after this hook, including on transactional pauses/errors.
  Attack declaration benefits: retarget_attack providers receive context['attack_spec'] when the caller owns a
    resolver spec. Native declarations use attack_defenses.declaration_spec(engine, actor, source, index), bounded
    by the existing native d20 scope's roll_context_end hook; typed declarations supply the same dict later
    passed to their resolver. Unscoped declarations supply None and must not grant a scoped benefit. The spec is transient,
    never catalog/condition/turn state. attack_defenses.grant_resistance(spec, recipient, source) grants Resistance
    to all damage types for that recipient on that attack only. Its single damage_defenses provider requires
    engine.damage_context() == spec['resolved_attack_context'] for typed packets. Native scratch binds the actual
    ATTACK_ROLLED roll ID/recipient, then checks the independently confirmed packet's source/attacker/index/roll/target.
    Every native declaration shadows its parent, even with no grant; typed scopes cannot bind a parent's native
    pending roll. Nested/non-attack packets cannot inherit a benefit. roll_context_end cleans native scratch only.
    On native completion, owned grants copy to that resolver's transient spec, so a ray can forward the spec and
    resolved_attack_context to its actual resolved_target_id. No pending global grant survives completion.
    Portable-character dispatch/direct/opportunity resolution uses declaration_resolution(engine) to bound
    otherwise unscoped declarations, including errors/pauses. The existing settled attack notification marks
    portable_declaration=True and finish_portable_declaration ends its scratch before hit/miss callbacks.
    bind_declared_roll(engine, actor_id, source, index, targets, roll_id) binds the portable adapter's actual roll,
    since its standalone harness lacks Gate4 event delivery; the native ATTACK_ROLLED subscriber uses the same helper.
    Destructive Blast forwards its explicit Context packet provenance and attack_defense_spec around its direct damage
    commit; save/area blasts have neither and retain ordinary defenses. This also preserves a redirected ray's recipient.
    Native scopes use indexed ATTACK reasons; portable reasons may omit index (confirmed packets still supply it).
    Context.attack_defense_spec carries that same spec only with explicitly attributed typed on-hit damage.
    typed_executor._deal uses attack_defenses.packet_defenses(engine, spec) to restore/clear parent packet metadata
    on success/error/pause. Misses/cancellations grant no damage benefit; old guardian_bodyguard turn flags are
    ignored. Unowned/unannotated specs return no defense rows; no new saved state, event, roll or schema.
  attack_sequence_start(ctx)                 -> None, once before a typed attack sequence. Owners may apply their own
                                                 evented costs/conditions; absent ownership returns early. No hooks =
                                                 no extra state/events or change to the legacy sequence.
                                                 barrage_hits accepts typed['barrage_sequence_continuation'] = True
                                                 on a nested primary context to retain the originating weapon's
                                                 counter; absent/False starts a new Barrage as before. This is
                                                 transient plug-in metadata, with no new persisted field.
  attack_damage(ctx, dice)                   -> DiceSpec or None, before a typed sequence rolls its damage. Only an
                                                 owning ability replaces dice; other values are ignored. No answer =
                                                 original dice unchanged (dice may be None for a non-damaging attack).
                                                 Equipment resizes only the weapon's own damage die, to the printed die
                                                 the hands actually free allow, in EITHER direction: a weapon compiled
                                                 one-handed returns to its two-handed die when the hand frees up, and
                                                 one compiled two-handed falls back when an occupant takes that hand.
                                                 The die count and any added fixed bonus are untouched, and damage a
                                                 technique printed with its own die is not weapon damage, so it keeps
                                                 that die whichever weapon delivers it. That boundary is
                                                 Context.weapon_damage_dice, a transient flag block_attack sets before
                                                 these hooks run: True for weapon dice, including a flat-only hit row
                                                 added to them; False whenever the attack's dice came from a
                                                 technique's own row, and False outside a typed attack. Numbers alone
                                                 cannot answer it, because a technique's printed die may equal the
                                                 weapon's. Fixed Two-Handed attacks are refused through
                                                 attack_allowed instead of changing their damage.
                                                 Compiled weapon metadata may include ability_modifier (the actual
                                                 attack/damage ability component), properties, and omits_ability_damage
                                                 (an off-hand restriction). Weapon-rule plug-ins may inspect these;
                                                 absent metadata must preserve older compiled/saved bundles. Choices
                                                 shared with attack_bonus belong in this Context's transient cache.
  damage_roll_bonus(ctx, effect, kinds)     -> int or None, additive modifier to a typed damage roll, after dice
                                                 selection and before rolling, save halving and defenses. Shared by
                                                 attack sequences and damage effects; cached area rolls add it once.
                                                 Fixed amounts/non-damaging attacks never call it. Owners check their
                                                 own conditions/rows. No contribution preserves dice/events exactly.
                                                 effect is the damage-effect row, or None for attack-sequence dice;
                                                 kinds is the effect's possible damage types, or [] for attack sequences.
                                                 Effect-specific owners return early for None; attack owners use
                                                 attack_damage/attack_damage_bonus for per-attack contributions.
                                                 Force Mantle uses the non-weapon effect and kinds; Bitter Dregs uses
                                                 the original effect row; Turning Wheel applies to both roll paths.
  attack_resolved(ctx, target, hit, effect)   -> None, after each typed attack resolves (hit is bool; effect is the
                                                 attack row). Owners consume their conditions/trigger their effects;
                                                 missing ownership or hook leaves state/events unchanged.
  evasion(ctx, subject, ability, failed, fail_effects) -> non-None to replace the failed-save damage branch with its
                                                 half-damage path and suppress the successful-save damage path.
                                                 Owners implement their stated eligibility/costs. No answer keeps
                                                 normal save effects; ownership-free calls must return None.
  attack_damage_types(ctx, attack, kinds)      -> list of allowed damage types for this typed attack, or None;
                                                 before damage type selection, leaving dice and damage unchanged
  damage_type_choices(ctx, kinds) -> list[str] | None; typed_executor.choose_damage_type asks this once per damage row that
                                                 really offers a choice of types (weapon damage and save damage alike), after
                                                 damage_choices() and before the automatic "lands hardest" pick, and chooses
                                                 among the returned list. For a printed ability that lets its user choose types
                                                 the row does not list (Alchemy's Seven-Flavor Furnace: "When an Alchemy technique
                                                 lets you choose Acid, Fire, Poison, or Force damage, you may choose one of your
                                                 selected damage types instead"): the owner returns its own types *beside* ``kinds``
                                                 (the printed ones stay legal, so a resisted prepared type loses to a printed one
                                                 that lands), not instead of them. Dice, the pick itself, the recorded damage type
                                                 and every other subscriber are unchanged; a single-type row is never asked about, and
                                                 no subscriber keeps the old behaviour exactly. The last non-empty answer wins, as with
                                                 attack_damage_types. An owner whose printed choice has no in-fight boundary asks it
                                                 once up front instead, on the general ``technique_start(engine, actor, action)``
                                                 seam that runs before a typed action's effects (combat/typed_executor.resolve_typed):
                                                 combat/ext/alchemy_riders.py's seven_flavor_prepare
                                                 puts Seven-Flavor Furnace's Long Rest damage types there, so the choice never
                                  lands in the middle of a rolled damage packet. That up-front question counts only the rows
                                  the engine itself resolves (``typed_executor.BLOCKS``); a row only a plug-in handles
                                  (``@effect``, which the executor hands to its rider printer) records state and prints a rider,
                                  so the types it lists describe damage dealt on a later trigger and the printed choice belongs
                                  to that trigger's own question -- asking here would put the question before anything it could
                                  apply to. Returning nothing never stops the activation.
  attack_damage_type_choice(ctx, attack, target, kinds, attack_index) -> one of ``kinds`` or None; called once per
                                                 strike (attack_index counts from 1) after target declaration and
                                                 before its roll/damage, also for reaction attacks that borrow a
                                                 weapon. ``target`` is the creature this strike is made against;
                                                 ``kinds`` the upper-case types the attack may deal. A value outside
                                                 ``kinds`` raises. None (the default for every non-owner) keeps the
                                                 executor's automatic pick. Lets a plug-in ask the owning player
                                                 separately for each attack (Iron Fist, combat/ext/body_iron_fist.py).
  after_hit(ctx, target, kind)                -> None, after a typed attack hits (kind: "unarmed", "weapon" or "other")
                                                 ctx.critical_hit records the resolved critical (including cancellation).
                                                 ctx.on_hit_context(target, **changes) carries it to a bonus/Exploit/Form;
                                                 switching its catalog action clears inherited display attribution
                                                 unless effect_source is explicitly supplied. Same-action children
                                                 keep their rider source; critical-hit ownership is unchanged.
                                                 all damage dice in that hit context double, including weapon
                                                 enchantments typed as damage; flat amounts do not. New attack/save/zone
                                                 Contexts default False. This adds no saved state or default events.
                                                 ctx.with_source(retained ability ID) attributes rider rolls/damage/
                                                 conditions without replacing the triggering action or its numbers.
                                                 Used by Hidden Strike, Pressure-Point Strike, Forms and Exploits;
                                                 core damage/save rows with source_modifier use that retained ID.
                                                 No attribution leaves legacy sources unchanged. Save branches carry
                                                 attribution but start a separate damage context (no critical bonus).
                                                 Damage uses ctx.damage_source (original catalog action) for rolls,
                                                 defenses and commit; payload.display_source_id carries the rider's
                                                 display attribution only. History resolves that optional ID generally.
                                                 ATTACK_ROLLED may carry attack_sequence_index (integer ordinal)
                                                 or attack_label (plain auxiliary-attack name). History never infers
                                                 entitlement from internal roll reasons; absent metadata is inert.
  history_event_metadata(event, events)       -> dict of presentation payload fields, or None; pure, read-only
                                                 Optional rider_display_text supplies the exact manual remainder of a
                                                 known legacy reminder. history_hidden omits a row with no remainder.
                                                 Missing metadata preserves the recorded text; neither changes events.
                                                 legacy adapter run with ext.query. Persisted fields take priority.
                                                 display_name names an outcome; display_source_id resolves a rider ID;
                                                 completed_outcome_sequence references an earlier recorded outcome
                                                 to suppress a duplicate GM_RIDER for the same actor/intent. No metadata
                                                 means ordinary rendering. Iron Fist owns Opening mode names here
                                                 and persists them through its existing event hook for new records.
                                                 history_hidden=True omits an event from the player feed only;
                                                 absent/False is inert. Concentration's timer adapter uses this
                                                 for legacy/transient deadline rows without altering replay data.
                                                 ctx.attack_result is this attack's ATTACK_ROLLED payload or None,
                                                 bounded to its resolution, actor, source, index and target; transient
                                                 and reset on every attack. Bonus damage cannot replace it. Shared by
                                                 critical-hit riders; natural_result 20 is the engine's critical rule.
  after_hit_choice(ctx, target, kind)         -> None, transactional typed-hit decisions, immediately before after_hit;
                                                 same arguments, after damage_dealt and after_hits_effects. run_strict
                                                 propagates choice pauses for rollback. Used by Canon extra targets
                                                 and Hidden Strike's post-damage rider choice;
                                                 any ability may use it. No handlers means no change. No native coverage.
  paid_hit_applied(ctx, target, source)       -> None, strict transactional callback after apply_paid_effects has paid
                                                 and delivered a selected rider through paid_hit or attack_modifiers.
                                                 ctx retains the triggering attack and immutable hit provenance;
                                                 source names the selected rider. Declined/unpaid riders never call it.
                                                 Used by Sword's completed-hit choice; any paid-hit ability may use it.
                                                 Owners may record integer/string provenance for attack_damage_final;
                                                 errors/choice pauses roll back. No handler means no change.
  damage_dealt(ctx, target, amount)            -> None, after this typed damage packet/attack commits positive HP or
                                                 temporary-HP damage, after defenses; called transactionally via
                                                 run_strict so player-choice pauses propagate. Used by Metal domain
                                                 Weight/Sharpen triggers; no handler means no change. Does not include
                                                 native legacy attacks or no-intent damage outside typed execution.
  after_hit_effects(ctx, target, kind)         -> None, after this one hit's own on-hit effects have executed, once per
                                                 strike, after _on_hit_bonuses and before any attack_damage_final rider.
                                                 Same arguments as after_hit (kind: "unarmed", "weapon" or "other"), and
                                                 only when the hit landed on a target that is still active, so a printed
                                                 trigger whose own method is executed by those rows can observe the
                                                 execution: typed_executor.strike_record(ctx) is this strike's own
                                                 transient dictionary (empty until typed_executor._begin_strike starts
                                                 the next one, shared with this hit's own rider Contexts and never
                                                 saved), and typed_executor.executed_weapon_methods(ctx, target) answers
                                                 every Weapon Method that ran on this very hit. A reaction attack
                                                 resolving between the damage and this hook runs its own strike in its
                                                 own Context, so it can neither clear nor inherit this record; while a
                                                 strike is being resolved its own record is the whole answer, and only
                                                 resolution with no strike of its own reads the engine-level fallback. A
                                                 rider that runs after this hit builds its Context by inheriting
                                                 strike_record (combat.ext.weapons_sphere.sub_context), so what it
                                                 executes stays on this hit as well. The per-strike record starts
                                                 empty, so an Extra Attack's second hit never
                                                 reads the first hit's method or committed damage, and a method refused
                                                 by the one-per-turn limit is not reported. Used by Iron Against Iron
                                                 (combat/ext/weapons_sphere.py).
                                                 No handler means no change, and no saved state or default event is added.
  # effect_choices uses the existing choice_options transport for post-resolution
  # choose_effects bundles (Listening Sutra checks and Heaven-Piercing Nail saves).
  # riders_shared.sphere_check supplies the margin count; preference_menu supplies
  # AI/default picks only, and result names the resolved outcome in the prompt.
  # tabik_ninpo's pressure_point_failed_choice uses the same public choice_options
  # transport after a failed Constitution save; standing picks are AI/default
  # preferences, and its owned passive row marks choice_owner for off-turn asks.
  # Its match_start handler copies that marker into engine-local passive rows
  # for legacy owners, without editing the bundled documents or emitting events.
  effect_allowed(ctx, effect)                 -> False to skip this typed effect before its once-use gate is consumed;
                                                 effect_permitted(ctx, effect, subjects, exclude=callback) queries
                                                 this gate plus recipient vetoes for a folded delivery, omitting only
                                                 the caller's suppression callback. No providers means permitted;
                                                 errors propagate and the query consumes no use clocks.
                                                 Borrowed Second repayment uses movement_semantics.moves_user:
                                                 ordinary/custom self travel is denied, including nested packets.
                                                 Custom travel may declare self_movement=True. A movement_role
                                                 of "rider" permits activation but never its forbidden travel.
                                                 Air's reviewed air_slashing_rider flag gates an on-hit bonus/save
                                                 on positive slashing damage from the current strike, recorded by
                                                 attack_result before bonuses. air_requires_concentration also
                                                 requires a currently held technique. Absent flags are inert;
                                                 snapshots are resolution-local and reset for each marked strike.
                                                 effect_denial uses reviewed deny_effects type lists for nested/free
                                                 commands, plus candidate/reaction filters. Source-expiring conditions
                                                 are inert without an owned applied effect; no existing benefit is removed.
                                                 None preserves execution. Transactional run_strict; handlers must
                                                 be pure queries. Used when an optional bonus already supplied a
                                                 base expression on this hit. No handler means no change.
  native_attack_scope(engine, context)       -> context manager or None, around an accepted native reaction attack,
                                                 before reaction-used publication through all rolls and packets.
                                                 context names actor_id, target_id, source_id and economy.
                                                 Transactional run_strict; ExitStack restores on errors/player pauses.
                                                 Default inert; prior_event_resources shares the typed provenance
                                                 stack so mixed native/typed attacks restore their enclosing event.
  effect_resolution_scope(ctx, effect)        -> context manager or None, around the selected effect block, including
                                                 nested effects and their event hooks. Transactional run_strict;
                                                 ExitStack restores scopes on errors/player pauses. Default inert.
                                                 Attack blocks enter here even for direct block_attack callers;
                                                 prior_event_resources restores enclosing grant provenance.
                                                 granted_movement exposes ordinary movement to reaction effects
                                                 here, then restores the separate native traversal allowance.
  hit_benefit_allowed(ctx, target, benefit)   -> False to replace a named automatic hit benefit; None otherwise.
                                                 Runs before that benefit spends its use limit, after independent
                                                 marks. Currently open_guard offers "open_the_gate". General seam
                                                 for optional Disarm and other hit-benefit substitutions; no ability
                                                 IDs in core, default unchanged. iron_open_hand uses an action-local
                                                 choice flag, reset at each hit; unowned/old bundles are inert.
  after_miss(ctx, target)                     -> None, after a typed attack misses
  after_miss_choice(ctx, target, spec)         -> None, independent post-miss decisions after ordinary missed
                                                 reactions; spec is the resolved attack specification. Transactional
                                                 pauses/errors propagate via run_strict. Owners check hostility,
                                                 reach, activity, consent and their own use limits. No economy is
                                                 spent by dispatch; default-inert without owned configuration.
                                                 triggered_context in typed_reactions supplies normal typed strike
                                                 delivery for both generic reactions and independent triggers.
                                                 Triggered melee attack effects may supply integer reach_ft to
                                                 attack_reaches for their own weapon's reach; omitted retains the
                                                 existing opportunity reach. This checks reach without movement.
  mark_applied(ctx, name, subject)            -> None, after block_mark places or refreshes a named mark, including
                                                 automatic Opening. Transactional: pauses/errors propagate for
                                                 preview rollback. Default-inert; plug-ins own trigger, eligibility
                                                 and limits. Shared seam for mark-triggered ability follow-ups.
  hit_reduced(engine, defender, attacker, source_id, before, after, reducers) -> int | None.
                                                 After a parked hit reduction lowers actual rolled damage;
                                                 before zero-damage follow-ups. reducers is a tuple of feature IDs.
                                                 Return additional damage reduction; returns add, clamped at zero.
                                                 Default-inert; ownership and printed trigger gates belong to plug-ins.
                                                 Transactional: choice pauses and errors propagate to preview/rollback.
  Outcome notification scope: after_hit and after_miss cover typed, legacy, opportunity and portable
                                                 runtime attacks notify exactly once. Return values never change
                                                 the settled result. Legacy Context.attack_notice is immutable
                                                 (source/attacker/target IDs, attack index, hit, melee, kind, roll_id);
                                                 action/typed metadata are copies. Unknown kinds remain "other".
                                                 These are read-only outcome notifications: owning riders may
                                                 emit their own evented effects, not rewrite the attack. Typed
                                                 attacks retain their original notification timing and Context.
                                                 Native hits are settled after defensive AC rechecks, including
                                                 attacks without damage and hits whose damage is reduced to 0.
                                                 A provisional ATTACK_ROLLED hit is not this notification.
                                                 Use after_hit for ordinary outcome riders, not DAMAGE_COMMITTED
                                                 or provisional roll events.
                                                 No subscribers = no new events or saved state. New owners such
                                                 as Unbroken Bolt intentionally add their printed miss rider.
  hit_snapshot(engine, attacker, target, attack_context, intent) -> None or a mapping from unique nonempty string
                                                 namespaces to JSON-like receipts. Pure query after the final hit
                                                 and defense rechecks, before damage (including damage-less hits).
                                                 Copies preserve hit-time eligibility through concentration loss,
                                                 sacrifice, or terminal damage. Duplicate namespaces/invalid replies
                                                 fail the transaction. Receipts stay per attack, never in saved state.
  hit_final(ctx, target, kind)                -> None, strict once-per-confirmed-hit notification after resolution.
                                                 ctx.hit_snapshots contains copied receipts from hit_snapshot;
                                                 ctx.attack_damage_context is the immutable confirmed AttackDamage.
                                                 Both fields are scoped to this callback and restored in finally,
                                                 including nested hits and failures; later damage inherits neither.
                                                 Native, typed and portable attacks use the actual settled target.
                                                 Explicit final riders may finish after terminal damage under the
                                                 existing guarded final-rider scope; they cannot rewrite a declared
                                                 result. Misses never capture or deliver. No subscribers means no
                                                 event/state change. Punishment Aegis uses these two hooks; an
                                                 ordinary after_hit consumer keeps its existing timing and behavior.
                                                 Native and typed multi-attacks recheck active/life/condition action
                                                 eligibility between strikes, so retaliation can stop the sequence.
  reaction_consent(engine, row, reactor, checkpoint) -> None for ordinary Ask-me confirmation, or exactly one owning
                                                 boolean reply after the plug-in's readable dynamic choice. Called
                                                 only for a manual Ask-me reaction; automatic plans/AI keep the
                                                 existing automatic decision. Consumers must not spend resources or
                                                 resolve the reaction here; True consents, False declines. The
                                                 native transaction handles player pauses. No subscriber preserves
                                                 the legacy prompt. Punishment Succor names its sacrificed ward,
                                                 affected ally, attacker and damage through this seam.
                                                 A provider may select an alternative price on a fresh trigger-local
                                                 row prepared by generic_reaction_costs; it must not alter compiled
                                                 rows. Normal payment and reaction_spend consume that selection.
                                                 Active Defense uses this for Focus-versus-Reaction consent.
  mark_consume(ctx, effect, subject)          -> True when the owning handler consumed the requested mark and its
                                                 linked effects; None leaves ordinary block_spend_mark behavior.
                                                 The handler must check effect.mark and the subject's owner-bound
                                                 mark before changing anything. Use normal evented removal. A
                                                 sacrifice is not another hit notification; Punishment's captured
                                                 hit receipt already owns its eventual retaliation.
  attack_reveal(ctx, target, hit)             -> False to skip the automatic "Hidden ends after an attack roll" for
                                                 this attack (typed_executor.py, eye 2026-09-28: Assassinate); the
                                                 plug-in that returns False is then responsible for the reveal itself
  save(ctx, subject, ability, named)          -> {"bonus": int, "modes": [...]} or None, before a typed save is rolled
                                                 (named: the conditions a failure imposes, plus "forced_movement" and
                                                 "damage:<type>" for a failed-save damage row whose type is fixed,
                                                 and "damaging_save" when either outcome contains damage/extra_damage,
                                                 including recipient own_turn_start damage in an applied state
                                                 (save_damage.has_damage, shared with charm_rules action gating),
                                                 independent of damage-type choices or eventual damage dealt).
                                                 The generic tag serves fragility/other damaging-save riders;
                                                 fixed-type tags retain type-specific save defenses. Without an
                                                 owning hook these tags do not change resolution.
  after_save(ctx, subject, ability, named, failed) -> None
  forced_movement_bonus(ctx, subject, effect): one hook for C7 (Gather and Return) and C14 (push_lengthening) -- see the
                                                 C14 entry below.
  forced_movement_distance(ctx, subject, effect, maximum_ft) -> int | None, before a typed push/pull.
                                                 One integer in [0, maximum_ft] chooses the requested distance; conflicting
                                                 or invalid answers preserve maximum_ft. Default inert. May ask a replayable
                                                 choice for any optional push/pull; leaves ordinary save defenses, forced
                                                 movement reactions, legal-space checks and movement events in core.
  forced_movement_restriction(ctx, subject, effect, maximum_ft) -> int | None, a MANDATORY cap on that same push/pull,
                                                 resolved before the optional distance choice above. One integer in
                                                 [0, maximum_ft] caps the distance the moved creature actually travels;
                                                 the smallest of several answers is the cap; a cap of 0 ends the movement
                                                 and asks no optional choice at all. Default inert. This is the contract
                                                 for a printed clause that overrides a distance rather than choosing one
                                                 ("Failed Save: the forced movement fails" -- Stand Against the
                                                 Calamity), so two abilities that both answer on one push can no longer
                                                 cancel each other out.

  forced_movement_direction(ctx, subject, distance_ft) -> (dx, dy) | None, once per push, before any step.
                                                 One two-item step, each an integer in -1..1 with at least one nonzero,
                                                 sets the square the moved creature steps toward for the whole route
                                                 (Hard Whip: "up to 10 feet in one legal direction other than directly
                                                 upward", combat/ext/wrestling.py). For a printed line that leaves the
                                                 direction to its user instead of deriving it from the caster. Any
                                                 other answer is ignored, so an unanswered or malformed hook keeps the
                                                 ordinary away/toward/centre routing. Default inert, and asks only of
                                                 pushes; pulls keep re-aiming at their anchor. The route stays one
                                                 straight line, so legal-space checks, forced-movement reactions,
                                                 Impact Collision and the movement events are unchanged.
  condition_attempt(ctx, subject, effect)    -> False to prevent a typed condition before immunity/reactions/application.
                                                 Strict lazy dispatch stops at the first prevention, before another
                                                 provider can ask or spend. Optional owned rescues may consent/pay;
                                                 pauses/errors unwind the action. None is default inert.
                                                 Context supplies the source actor, action and compiled numbers,
                                                 effect is the exact condition row. None leaves legacy behaviour unchanged.
                                                 Source-qualified defenses can distinguish physical from magical holds.
  condition_state(ctx, subject, effect)      -> {"data": dict, "expires_on": str} | False | None, after defenses,
                                                 before application. One owning answer merges stored data/overrides expiry;
                                                 False skips application. None/conflicting answers preserve defaults.
                                                 General seam for dependent conditions/hold lifetimes; saves, immunity,
                                                 condition reactions and companion handling remain in core. Default inert.
  The bar a Charm/Captivated condition carries (AUTO52 2026-10-05).  A ``condition`` row's ``condition_data.bar`` is the
  rule the creature is under, put there by the effect that imposed it; combat/ext/charm_rules.py owns it and publishes
  ``charm_rules.bars(actor)`` so another plug-in may read the same data.  Two keys added here are general -- they name
  the printed rule, never an ability:
    ``declare_save`` {"ability", "dc", "vs", "perception", "remedy", "on_success", "immune_until", "resists", "passes"}
      "the first time on each of its turns that it declares a hostile action, it must make a saving throw".
      ``vs: "others"`` (the default) is the barred creature's own rule about what it declares and is read only when
      that creature is the attacker; ``vs: "source"`` is a rule about the creature being attacked and is read only on
      the defender (a self aura).  ``dc`` is stamped by charm_rules' own ``condition_state`` answer from the applier's
      compiled numbers, exactly as ``repeat_save`` is.  The once-each-turn clock is the engine's ``turn_flags``, so no
      stored state is added for it.  ``remedy`` is the printed failure consequence and is what keeps one bar key
      reusable across rules with different failures: ``"choose"`` (Captivated) makes the creature decide between the
      consequences the engine can actually carry out -- ``redirect`` really re-aims that attack at the applier as a
      ``redirection.constraint``, ``lost`` makes it a forced miss -- and its absence keeps the bare loss its own text
      prints (Beauty Beyond Form), which is also what every saved fight and every older row gets.  The save is asked
      at the attack's ``retarget_attack`` declaration, the only checkpoint before the die that can still change a
      target; because it constrains the attacker rather than the defender it is registered as a ``redirection.constraint``
      and is therefore asked before Defensive Rider, Meat Shield, Misdirected Attack or Harmonious Body, which cannot
      re-aim the attack without running the save (AUTO52r2f1).  ``{"force_miss": True}`` on ``before_attack`` applies
      that one attack's loss.  A failed declaration whose remedy is ``redirect`` really changes who is hit.  A one-option
      question is not asked.  The rule
      constrains only the declaration that failed, so no later target is withdrawn from the menu.  The question names
      the charm, the attack, the charmer the attack must be aimed at and the creature it was aimed at; the option
      labels say what each consequence does.  The condition also
      answers ``condition_choice_owner`` while it carries a ``remedy: "choose"`` bar, so a manually controlled bearer
      is enrolled to decide even with no other choice feature.  Default inert: no bar, or a bar without the key, gets
      no answer anywhere.
      ``on_success``:
      "end_condition"; ``immune_until``: "start_of_source_next_turn"; ``passes``: how many successful declarations
      make the creature immune to that ability from that applier (one evented pass condition each, so the tally
      survives a commit + reload).  Default inert: no bar, or a bar without the key, gets no answer anywhere.
    ``retaliate`` {"damage", "damage_type", "vs", "first"}
      "the first time on each of its turns that it damages a creature other than you, it takes <damage> damage".
      ``damage`` is resolved once by charm_rules' ``condition_state`` answer from the applier's compiled numbers (an
      integer, stored on the bar) and answered from ``damage_dealt``, so the wound is ordinary damage with its own
      Resistance, Temporary HP, Concentration check and defeat, and -- because it is not raised inside an event hook --
      its own damage riders still see it.  ``first``: "turn" (the default, the printed per-turn clock).
  after_save_resolved(ctx, subject, ability, named, failed) -> None, after after_save and all pending outcome overrides;
                                                 failed is the final typed save result. For outcome-dependent riders,
                                                 not rerolls or outcome overrides. Default inert (no registrations).
                                                 Event consumers may query typed_executor.active_save_pending(engine,
                                                 source, subject_id) during SAVE_ROLLED to defer active saves here;
                                                 repeated/legacy saves remain separately observable. The query is
                                                 context-local, nestable, read-only and cleared on exceptions/pauses.
  attack_bonus(ctx, actor)                    -> int or None, a flat modifier added to the attacker's own attack roll
                                                 before it is rolled (forged-worker 2026-09-29: Exhaustion's -1 per
                                                 level -- attack_mode only offers Advantage/Disadvantage, no flat number)
                                                 During typed strikes, trigger_occurrence.current_strike(engine)
                                                 exposes actor, actual target and namespaced transient scratch through
                                                 the roll and all follow-ups. Nested strikes restore the parent;
                                                 exceptions/pauses clear the frame. No events or saved state changes.
                                                 Default inert unless a provider reads/writes this scratch frame.
  ability_check_mode(engine, actor, ability, skill, against) -> "ADVANTAGE" | "DISADVANTAGE" | None.
                                                 Called by check_modes/check_mode with engine and against_creature;
                                                 modes combine with native conditions and cancel normally. Default-inert.
                                                 Single-target Analyze, opposed Sleight of Hand and source-owned skill_check
                                                 provide provenance; missing/multi-target provenance never guesses a target.
  skill_check_mode(ctx, subject, ability, skill) -> "ADVANTAGE" | "DISADVANTAGE" | None.
                                                 Before a source-owned skill_check effect rolls, with the full typed
                                                 originating-effect context. Combines with native and opposing-creature
                                                 modes before cancellation. Default-inert; no standalone Study action
                                                 or inference from the caster's owned abilities. Returning None preserves
                                                 legacy rolls and events. Discern Illusions uses explicit Illusion tags.
  check_bonus(ctx, actor)                     -> int or None, a flat modifier added to one of typed_executor's own
                                                 ability checks (escape a grapple, a wall breach, an R6 contest) before
                                                 it is rolled (forged-worker 2026-09-29, same reason as attack_bonus)
                                                 The shared escape resolver supplies ctx.escape_hazards (tuple of
                                                 names for the selected hold only) on an ephemeral context copy.
                                                 A resolver that runs a check against a named ongoing effect may
                                                 likewise supply ctx.resists_gravity on an ephemeral context copy
                                                 (the source_definition_id of the effect the check resists); it is
                                                 absent on every other context, so a bonus that needs to know the
                                                 check answers a Gravity effect asks for it and stays inert elsewhere.
                                                 Absent/empty scope grants no hazard-qualified bonus by itself;
                                                 the bonus provider must still check its owned active effect.
  technique_used(ctx)                         -> None, after a typed action's effects ran
                                                 Builders may set parameters['setting_only'] = True only for free
                                                 self actions storing a future selection or showing rules, with no
                                                 immediate gameplay activity.
                                                 Unflagged saved actions keep ordinary hooks and reaction windows.
                                                 Setting-only selectors (setting_choices.is_setting_action) never
                                                 call technique_start, technique_used or action_completed. Their
                                                 INTENT_ACCEPTED bookkeeping also skips event hooks; setting
                                                 condition events still run normally. Other actions are unchanged.
  attack_damage_bonus(ctx, target, effect)    -> int or None, added to each typed attack's damage modifier immediately
                                                 before resolution (also to fixed damage); dice are not multiplied.
                                                 after_hit/after_miss confirm whether this attempt rolled damage.
                                                 Default inert; distinct from attack_damage's sequence-wide dice shaping.
  technique_start(engine, actor, action)     -> True to stop the activation as it starts (typed_executor.resolve_typed, after its costs
                                                 are paid; Speech-Knot Point). It also runs from combat/prefight.py while the match is
                                                 being constructed: listed costs have been paid, but there is no action intent and event
                                                 hooks are suppressed by cast_all. A plug-in may rely on the actor, action, engine state,
                                                 and activation timing; it must not rely on a player turn, action intent, or event-hook
                                                 delivery, or require an in-fight choice in this context. combat/ext/qi_instability.py also
                                                 uses it to fire zones.py's moment "technique" -- the creature inside a Turbulent Field
                                                 activating a technique that costs CP (sys-resources-states 2026-09-29) -- and returns None
  event(engine, event_type, kwargs)           -> None, after each root event (Gate 4 engine). @hook("event", nested=True)
                                                 opts that subscriber into child events produced inside event/turn
                                                 hooks. Legacy subscribers retain root-only delivery. Children are
                                                 recorded first, delivered depth-first in registration order, once
                                                 per subscriber/event. Eight active dispatch levels maximum; the
                                                 first overflow records one GM_RIDER per root cascade and suppresses
                                                 deeper extension delivery, preserving the child event itself.
                                                 Pauses propagate; native transactions roll back the whole cascade.
                                                 No nested subscriber = exact legacy extension delivery.
                                                 mounts.on_prone_applied consumes root and nested CONDITION_APPLIED
                                                 Prone events, including persistent companions of Unconscious.
                                                 It resolves the existing mounted fall save and is inert without
                                                 a rider/mount bond; other mounted event delivery stays root-only.
                                                 life_state._events opts in to share HP-before bookkeeping,
                                                 death-save failures, massive-damage death and life/healing
                                                 settlement between native and plug-in-dealt damage. It returns
                                                 None; without owned life/death rules or life-state conditions,
                                                 no life-state consequence is added. Its event writes use the
                                                 same bounded depth-first dispatcher; damage is not recommitted.
                                                 daemonic_riders.black_sun_resource_spent opts in to consume
                                                 Black Sun's first positive CP/Stamina spend inside event riders;
                                                 its native damage delivery reaches nested-aware ongoing damage saves
                                                 and fragile charm endings. These shared consumers opt into nested
                                                 DAMAGE_COMMITTED events and remain inert without owned conditions.
                                                 No armed Black Sun condition = inert.
                                                 daemonic_riders.black_sun_blocks_resource_gain vetoes positive gains
                                                 to represented CP/Qi/Stamina/Resonance pools while that condition
                                                 remains; temporary CP has no separate provenance in ActorState.
                                                 beastmastery_riders.allied_damage_ends_control opts in so
                                                 positive allied HP damage or Temporary HP absorption inside
                                                 event riders ends only the recorded Beast Tamer control.
                                                 No owned harm-ending ledger, zero damage or enemy damage = inert.
                                                 glass_refraction.domain_terrain_end_events opts in so a Glass
                                                 Domain that ends inside another event still takes its own Shattered
                                                 Glass Terrain with it: it only reads ZONE_REMOVED and only removes
                                                 patches whose own record names that Domain, so it is inert without a
                                                 tied patch and never disturbs unrelated zone removal.
                                                 CONDITION_APPLIED / MODIFIER_APPLIED / ZONE_CREATED with payload
                                                 retained_instance_update=1 are replay-only upserts of an existing
                                                 instance (suppression/restoration/area movement), never fresh applications.
                                                 run and run_nested skip every event subscriber for these records;
                                                 journal readers use retained_updates.is_retained_update as well.
                                                 The reducer still records full identity, source, data and expiry.
                                                 Absent the marker, delivery and old saved fights are unchanged.
                                                 kwargs["originating_event"] is the exact recorded Event preserved by
                                                 remember_recorded_event before Ready delivery (also for nested events).
                                                 prepared_actions.on_event restores that identity after its cascade,
                                                 before Gate 4 dispatch; use the Event's source/sequence,
                                                 never the mutable log tail, to attribute this event. Read-only,
                                                 dispatch-local metadata: no added saved fields or event bytes.
                                                 Summoned-creature policy plug-ins may observe SUMMON_APPEARED and
                                                 append evented conditions, or act on a due effect_expiring hook.
  effect_expiring(engine, holder, row)        -> None, before a timed condition or modifier is removed; default inert.
                                                 Radiance uses this for Heavenly Radiance's ending cost. Its nested
                                                 event subscriber records CP current/maximum and the form instance
                                                 on MATCH_ENDED while the form exists; the exemption uses that saved
                                                 receipt, never a later resource balance. CONDITION_REMOVED shares
                                                 the once-per-instance cost guard with timed expiry. Other actors
                                                 have no form or receipt and retain their previous behavior.
                                                 linked_holds reconciles persisted orphan parent_hold links here
                                                 and at turn boundaries after duration sweeps; unlinked rows are inert.
                                                 grapple_range ends only range-bearing typed Grappled/Pinned holds
                                                 after MOVEMENT_COMMITTED separates either participant beyond reach.
  became_incapacitated(engine, actor, event)   -> None, called once per newly applied condition that makes that actor
                                                 Incapacitated, after the normal event is recorded. Shared lifecycle
                                                 consumer seam for ending concentration and physical holds; default inert.
  grappling_body_parts(engine, actor)          -> iterable of {id, label} parts currently legal for this owner to
                                                 maintain a physical Grapple with. Owners register only while the
                                                 feature is owned and eligible; activation need not precede the choice.
                                                 No answers means two ordinary hands.
                                                 Newly compiled typed.physical_grapple=True opts granted physical Grapples
                                                 into the same free-part candidate check and condition_state allocation as
                                                 Unarmed Strike Grapple (Opening Strike also uses it). Missing metadata is
                                                 inert for old catalogs; magical Grappled effects consume no physical part.
  hand_parts(engine, actor)                   -> iterable of additional hand ids usable for equipment and physical
                                                 Grapples. Default: left/right hands. Only owning features contribute.
  hand_occupants(engine, actor)               -> {part_id: occupant_id} for another rules-defined occupied part;
                                                 pure query, no contribution for unowned/inactive features. Default inert.
                                                 combat/ext/scoundrel_riders.py uses it for the one printed case where an
                                                 ordinary object really is in a hand ("take the object into a free hand"),
                                                 and only for the records it filed itself.
                                                 hand_occupancy is the shared public model used by equipment_hands
                                                 and grapple_parts: physical holds, held weapons and shields consume
                                                 parts; worn/carried non-held items and nonphysical restraints do not.
                                                 Two-Handed weapons occupy one resting hand, two while attacking.
                                                 Initial gear fills at most the ordinary hands (shield first, then
                                                 catalog weapon order); spare inventory is stowed. equipment_grip
                                                 Draw/Stow effects override that default using string/integer condition
                                                 data and normal journal events, with no Action cost as for existing
                                                 table equipment handling. Dropping never auto-draws a spare.
                                                 Managed weapon grips opt in for catalogs with equipment_grip
                                                 actions or equipment_hands_model=1 on the compiled acquisition
                                                 action (including initially unarmed actors). The compiler
                                                 publishes that policy marker only during fresh compilation.
                                                 Older immutable catalogs retain their historical weapon
                                                 policy (no new grip restrictions or inferred weapon occupants).
                                                 Stow releases possessed unusable weapons without removing their
                                                 disabling conditions. Paired acquisition needs two free hands;
                                                 any overflow blocks managed weapon attacks.
                                                 Legacy holds allocate ordinary hands deterministically. No derived
                                                 occupancy is saved; existing drop/disarm/held_by state is authoritative.
                                                 A bound/unusable weapon still occupies its grip; weapon_hits.available_weapons
                                                 include_busy=True supplies physical possession, while its default supplies
                                                 usable weapons for attacks and delivered techniques. One physical weapon
                                                 is one grip: its alternative attack modes (an off-hand copy, an
                                                 extended-reach variant) resolve to the same identity for possession,
                                                 occupancy, Draw/Stow and hand capacity, while staying distinct attacks
                                                 in the menu, so one weapon never fills both hands of itself.
  grappling_part_selected(ctx, target, part)  -> dict of persisted condition data or None, after a legal physical
                                                 part is chosen, before Grappled is applied. The owning feature may
                                                 eventfully activate its maintenance state and supply integer/string
                                                 per-hold data. Unowned/unselected features return None (default inert).
  grapple_eligibility_changed(engine, actor, released=()) -> None, reconcile holds after an owning feature ends;
                                                 released is a tuple of explicitly relinquished part ids, even if
                                                 they remain eligible for a future hold. Each
                                                 consumer removes only its own holds whose maintaining part is gone.
                                                 Default inert.
  effect_expiring_choice(engine, holder, row) -> None, strict transactional checkpoint before the extension duration
                                                 clock removes a due condition or modifier and before effect_expiring.
                                                 Providers may ask consent or eventfully resume a delayed effect;
                                                 pauses and errors roll back the enclosing action even through
                                                 observational turn hooks (run_checkpoint). Default inert. Sweep
                                                 rechecks that the row exists after delivery; a provider that ends
                                                 its own protection can remove it before reattempting the effect.
  effect_expiring(engine, holder, row)        -> None, before the extension duration
                                                 clock removes a due condition or modifier.
                                                 May eventfully end dependent state; default
                                                 inert. Sweep checks row still exists afterward.
  analyzed(engine, actor, target) -> None
                                                 After mind_hidden_eye marks one target Analyzed. Default-inert;
                                                 owned riders may offer rival choices even inside turn/event hooks.
  analyze_checked(engine, actor, target, payload) -> None
                                                 After one Analyze CHECK_ROLLED, successful or failed. Payload holds
                                                 actor roll, dc and success. Owned riders count attempts and learn
                                                 facts here, including checks nested inside an event hook. This does
                                                 not redispatch observational events or damage, and returns nothing.
  Fight rules: state.rules is an optional string-to-string genesis rule set,
              recorded in MATCH_CREATED. Absent keys retain historical behavior.
              finalized_turns=skip_finalized_v1 is stamped only by new-fight
              service creation. Gate2 queries turn_decisions.omits_turn before
              starting each subsequent slot. Inactive non-Dying/non-Stable and
              dead creatures retain their slots but get no turn events/callbacks.
              effect_durations.nominal_slot supplies expiry-only boundaries;
              per-effect integer offsets in turn_flags keep counted deadlines
              advancing without incrementing turns_started, including revival.
  nominal_slot_boundary(engine, actor, checkpoint) -> None; expiry-only hook at
              an omitted slot's START_OF_TURN / END_OF_TURN. Never reset actions,
              roll saves, damage, offer choices, or dispatch turn_start/turn_end.
              No subscriber means no extra effects. Used by custom round/slot
              deadlines as well as generic condition/modifier/zone clocks.
              Custom counter consumers use effect_durations.custom_turn_due:
              (actor, deadline, persisted storage, record key, nominal=False)
              -> bool. At the matching nominal boundary pass nominal=True once;
              real expiry callbacks use False. Per-record integer offsets retire
              when due; actor flag storage retains _round_ keys through revival.
              stored_token_due(engine, name, storage, key, actor=None,
              checkpoint=None, ending_id=None) -> bool gives custom stored
              tokens the same per-record clock (placements, panes, summons).
              Lifetime-preserving replacements use the public duration helpers:
              apply_condition_preserving_clock(engine, holder, previous,
              condition_id, source_id, source_actor_id, *, expires_on, data=None,
              previous_holder=None) -> None applies through normal events and
              transfers only the old instance's integer offset. previous=None
              is a fresh lifetime. transfer_expiry_clock(holder, previous,
              recipient, replacement) -> None also supports modifiers/movement;
              if the original remains its clock is copied, otherwise retired.
              No existing offset means no change; renewed effects never inherit.
              continuing_expiry(holder, previous, name, source_actor_id) -> name
              retains the original counted anchor when a stamped lifetime is
              continued by another applier, using existing explicit turn tokens.
              Import these helpers inside consuming functions so lazy plug-in
              discovery retains the existing boundary hook registration order.
  placed_deadline_expiring(engine, zone) -> None; expiry-only cleanup before a
              placed until-token expires at a nominal boundary. Default inert;
              placed removes the zone afterwards if still active. Force uses
              this to retire the associated clinging condition as well.
              Service-created fights use zero_hp=dying_2024; low-level stock
              controls retain their legacy defaults. life_state owns that rule.
              The default excludes summoned combat bodies (their normal zero-HP
              destruction still applies). life_state's late turn_boundary_start subscriber
              ends combat against only ordinary Stable opponents without killing
              them; Dying actors, scheduled recovery and active allied summons
              preserve recovery opportunities. Absent rules leave results intact.
  ai_downed_damage_worthwhile(engine, actor, candidate, action, targets) -> None/bool:
              a printed ability benefit may opt an owning AI into damaging a
              downed enemy. Pure query; no answer leaves life_state's new-fight
              restraint intact. Soul Warden uses it for a finishable Soul Harvest.
  turn_start(engine, actor), turn_end(engine, actor) -> None, observational turn events. Start-turn choices and zone
                                                 effects have not yet resolved at turn_start; companion following
                                                 belongs in uncommanded_summon_turn, after those effects.
  action_completed(engine, actor, economy, source_definition_id) -> None, after an Action/Bonus Action resolves;
                                                 covers legacy attacks negated after their attack roll. No registered
                                                 hook or no owned stored condition leaves behavior unchanged.
  turn_start_choice(engine, actor)            -> None, transactional turn-boundary decisions, before zone/start-turn
                                                 reactions (typed_reactions.on_turn_start). Unlike observational
                                                 turn_start hooks, choice-provider pauses/errors propagate through
                                                 the transaction and preview. Use for expiry costs or start-turn
                                                 benefit choices; absent registrations are inert. No implicit
                                                 choice or Reaction cost. Hooks own eligibility and saved state.
  settings_batch_key(action)                  -> hashable setting key or None. Explicitly opt a sealed free SELF
                                                 setting_only action into Gate3 SETTINGS_BATCH_V1 storage-only
                                                 execution. Default inert. The plug-in must validate its exact
                                                 effects; no costs, gameplay, toggles, decisions or reactions.
                                                 Duplicate keys in a transaction are rejected. Gate3 records
                                                 the policy and exact sources for crash recovery/re-execution.
  settings_batch_rows(engine, actor_id, sources) -> optional list of affected modifier presentation rows. Read-only;
                                                 return [] or None for unrelated settings. Receipts do not require
                                                 any presentation schema or ability-specific action parameters.
  settings_project_rows(actions, actor_id, saved_sources, affected_sources) -> optional list of modifier rows for
                                                 project defaults, using the plug-in's own schema and renderer.
                                                 affected_sources is None for a full sheet; read-only and default inert.
  match_start(engine)                         -> None, once when an engine is built (Gate2Engine.__init__'s end, so a
                                                 fresh and a reloaded fight both run it); map objects are made here
                                                 before genesis and the very first menu. Must be idempotent and use
                                                 evented state methods; loaded saved state replaces constructor state.
                                                 setting_choices uses match_start (priority 100, after sheet choices)
                                                 and applies roster.settings_presets_v1 (priority 50), validated
                                                 through settings_batch_key. Absent recorded defaults are inert;
                                                 later project edits never substitute for the saved roster.
                                                 and turn_start for opt-in parameters.ai_setting_default on free
                                                 SELF setting_only actions. Metadata: condition_id, source_definition_id,
                                                 data (persistable condition data). Installs UNTIL_REMOVED only for
                                                 LOCAL_AUTO/API_AUTO owners without that condition. Returns None;
                                                 manual owners, existing choices and unflagged saved actions are inert.
                                                 May install deterministic supplemental action definitions in the
                                                 engine-local catalog; this does not change serialized actor action_ids.
                                                 No registered hook or absent map objects leaves legacy bytes unchanged.
  healing_received(engine, subject, amount)   -> int | None: restrict ordinary healing before assignment or HP gain.
                                                 Sequential reduction: each hook receives the surviving amount,
                                                 may lower it, and zero stops the stage. No hook leaves it unchanged.
                                                 Used by typed healing and life_state.heal_to; explicit HP restoration
                                                 (soul return, recorded HP reset) does not represent ordinary healing.
  healing_assigned(engine, subject, amount)   -> int | None: assign surviving ordinary healing before HP gain (even at
                                                 maximum HP). Runs after all restrictions, never for denied healing.
                                                 Same sequential reduction contract; each hook may spend only the
                                                 amount it receives. Both stages are transactional and propagate pauses
                                                 and errors. Absent applicable conditions/owners must return None.
  speed(engine, actor)                        -> int feet added to its Speed
                                                 May return speed_contributions.SpeedContribution,
                                                 an int with transient sources: (source_id, plain name,
                                                 signed feet). Movement diagnostics read these same
                                                 contributions; no second ability calculation or state.
                                                 Pure query; absent ability/condition returns None/0.
  ac(engine, target)                          -> int added to its Armor Class
  opportunity_allowed(engine, reactor, mover) -> False to forbid that opportunity attack
                                                 granted_movement.choices/move reuse native legal paths and
                                                 resolution for immediate movement capped to its granted feet.
                                                 Reeling Step and Swaying Guard pass exempt creature IDs;
                                                 the mover-specific scope is transient and restored in finally.
                                                 No scope = no change to ordinary movement or saved fights.
                                                 Its event hook restores ordinary movement at the willing native
                                                 commit, before movement observers and post-move reactions.
  opportunity_profile(engine, actor, action)  -> temporary ActionDefinition for this actor's melee Opportunity Attack,
                                                 or None to retain the compiled action and reach. First non-None wins.
                                                 Used for both threatened reach and execution; must be pure and retain
                                                 the action's identity/economy and typed weapon/source identity (defenses
                                                 read the catalog). No saved row or catalog mutation. Supports
                                                 temporary melee reach/damage profiles (Bojutsu Barrier); default inert.
  opportunity_action(engine, reactor, action) -> replacement ActionDefinition for the Factory opportunity attack;
                                                 its range also determines opportunity eligibility (Axes form reach).
                                                 Pure, default-inert. First answer is then passed to opportunity_profile;
                                                 the same composed temporary profile is used for reach and execution.
  opportunity_attempt(ctx, mover)            -> None, after a Factory OA is accepted, before its typed attack runs;
                                                 may shape that attack or consume a first-OA effect (Beauty in Motion)
                                                 Factory then publishes reaction_used before rolling, exactly once.
                                                 typed_reactions.publish_reaction_used(engine, actor, row) is the
                                                 shared seam for already paid reactions; free triggers omit it.
                                                 Answers nest up to 16 dispatch levels. The transient
                                                 engine._typed_answered_reaction frame holds actor_id, row and
                                                 penalty, restored on unwind (including Ask-me pauses).
                                                 typed_reactions.reaction_penalty(engine, actor_id, feature_id)
                                                 returns that accepted reaction's penalty or None; with no answer
                                                 this is inert. No new stored fight state or hook registration.
  reaction_allowed(engine, reactor, other)    -> False to forbid a reaction of reactor's that answers other
  row_allowed(engine, actor, row)             -> False to reject a reaction row at generic/explicit admission and
                                                 opening (_can_trigger, _can_react, _open). Pure, default-inert;
                                                 weapon prerequisites and reaction-economy owner-turn deadlines
                                                 use this general seam. Receipted spending does not recheck a
                                                 deadline set by the same opening.
  Delivery of committed damage (combat/ext/damage_delivery.py): while a damage roll is committed, the
  delivering site states what is delivering it -- the catalog id, one general hazard class (TRAP, FALLING,
  AREA) with the area's zone id, and the number of this single activation -- on the transient
  engine._typed_pending_damage_source frame, which is saved and restored around the commit.
  combat/typed_executor.py opens it with the delivering action's own id for every typed damage row and
  typed attack, exactly as it already stashes the damage TYPE beside it (_typed_pending_damage_type);
  combat/falling.py opens it for a fall, combat/zones.py for an area's own trigger and move-through
  effects, and combat/ext/trap.py for a trap (whose Dart Mechanism resolves a native attack outside the
  typed executor). Opening it WITH a hazard class starts an activation and names it, so one springing
  of a tripwire is never the next one; the name is built from how many events the fight had journalled when
  that delivery began (the journal is saved with the fight and read back on load, so a name that outlived
  a table commit still cannot be read as a later activation's) and, after it, which activation began there;
  opening it with only an id continues the activation around it when
  that id is the source the delivery site itself opened it with (the executor passes its Context's own
  typed source, which is exactly that string), and otherwise starts a delivery of its own with no hazard,
  no area and no activation, so a Reaction's returned damage or a talent fired by an area's trigger is
  never read as that trap's or that area's damage. A printed "damage from a trap / a collapse / a stone,
  crystal, sand, earth or mineral environmental hazard" limit reads it in row_allowed / ally_row_allowed,
  so such a guard is offered for the deliveries its trigger names and not for every wound (source-sphere
  Source Skin and Mine-Shelter Reflex, combat/ext/source_sphere.py); damage_delivery.event(engine) is
  the one activation's name, for a printed rule that names one triggering damage rather than the thing
  doing the damage. Nothing is journalled or stored: replays and fights saved before it are
  unchanged, and with no frame open (engine-internal damage) such a row stays off rather than firing blind.
  reaction_subject_allowed(engine, reactor, other, row) -> False to keep one generic reaction row from answering this
                                                 creature (combat/typed_reactions._subject_ok; Charged Countermeasure
                                                 answers only a Charged or Conductive one)
  ally_row_allowed(engine, reactor, subject, row) -> False to keep one generic ally reaction row (ally_hit, ally_damaged, ...)
                                                 from answering this ally of the reactor (combat/typed_reactions._ally_row_ok;
                                                 placed-effects 2026-09-29: Flower of False Death answers an ally that carries
                                                 the reactor's Blossom -- reaction_subject_allowed only sees the attacker there)
  native_reaction_roll_mode(engine, context) -> "ADVANTAGE" | "DISADVANTAGE" | None, before a native accepted
                                                 reaction attack's own d20. Context names actor_id, target_id,
                                                 source_id/reaction_source_id, economy="REACTION", kind="attack".
                                                 No answer leaves the existing mode unchanged; opposing modes cancel.
                                                 Runs only inside native_reactions.attack_scope, after payment and
                                                 publish_reaction_used, for the matching attacker/source. Parent
                                                 scopes and penalty frames restore on completion or Ask-me pause.
                                                 d20_context exposes the same Reaction identity to rewrite hooks.
  reaction_roll_mode(ctx)                     -> "ADVANTAGE" | "DISADVANTAGE" | None, before the reactor's own d20 in a
                                                 reaction that is not an attack -- a contest or a chance roll
                                                 (typed_executor._reaction_roll_mode); attack_mode covers its attacks
  collision(ctx, target, blocked_at, remaining_ft) -> None, after a push (not a pull) stops short of the distance
                                                 asked for (typed_executor._push); blocked_at is the Position it
                                                 could not enter, remaining_ft the distance cut off (Brute's Impact
                                                 Collision, gu 2026-09-28: no existing hook told a plug-in that a
                                                 shove hit a wall or a creature, so the smallest one was added)
  forced_distance(engine, mover, source, distance_ft) -> int feet cut from a typed push or pull before any forced_moved
                                                 reaction (typed_reactions.on_forced_movement; rider lane 9 2026-09-29:
                                                 Mountain-Rooted Rim's standing "reduce forced movement ... by 10 feet")
  would_drop(engine, target, pending, source_actor_id) -> the damage left to apply (an int), when this hit would take the
                                                 target to 0 HP (typed_reactions._offer_drop_to_zero_or_bloodied, before any
                                                 drop_to_zero reaction; placed-effects 2026-09-29: Standard Cannot Fall
                                                 keeps an ally at 1 HP); the smallest answer counts, None leaves the damage
  save_gate(ctx, subject)                    -> False to leave that creature out of a typed save effect: it is unaffected, no roll (typed_executor.
                                                 block_save; rider lane 3 2026-09-29: "immune to your Beauty Beyond Form for 24 hours")
  teleport_gate(ctx, start, destination)      -> False to stop a creature's own teleport before it happens (typed_executor._teleport;
                                                 placed-effects 2026-09-29: Cut the Road Behind You's seal makes the follower roll
                                                 a Cultivation Check; the plug-in records the roll and says why in the log)
  hit_response(engine, attacker, target, spec, total, natural, effective_ac) -> (new_effective_ac, False) to turn a hit into a
                                                 miss, or None; called for a typed target once the roll is a hit
                                                 (typed_reactions.on_attack_hit; sys-resources-states 2026-09-29: Brace
                                                 the Line's "would miss after adding +2 to the ally's AC"), first hook to
                                                 answer wins
  damage_pending(engine, target, pending, source_definition_id, source_actor_id) -> int, the damage a plug-in lets through
                                                 (the lowest answer counts), or an unchanged number; called for a typed
                                                 target just before its Temporary HP absorb (typed_reactions.on_damage,
                                                 so only damage dealt during an action, at reaction depth 2 or less), and
                                                 free to grant Temporary HP first (Legion Unending: "Apply these
                                                 Temporary HP before the triggering damage"). combat/ext/damage_sharing.py
                                                 splits damage through it: the taker's portion is committed with
                                                 engine._commit_damage(..., None, reaction_depth=2) while
                                                 engine._damage_unreduced names a taker whose own Resistance must not
                                                 apply a second time (typed_reactions.defend returns the amount at once)
                                                 During a typed attack, engine._typed_damage_packet supplies delivery
                                                 provenance: source, actor, target (ids), kind (attack_kind), weapon/ranged
                                                 (bools), interceptable (bool, default True). It is None for standalone
                                                 typed damage, restored after nested resolutions, and never persisted.
                                                 Inspect it only when its three ids match this pending packet. Without an
                                                 owning interception plug-in it has no effect (Bojutsu, 2026-09-29).
  damage_shared(engine, taker, target, row, source_actor_id, taken) -> None, after a plug-in reaction row made ``taker`` take
                                                 ``taken`` of the damage aimed at ``target`` (combat/ext/damage_sharing.py
                                                 _take, after its log line; sys-resources-states 2026-09-29: the Heartbinder's
                                                 Devotion pays out on a share it makes or a marked creature makes)
  condition_immune(engine, actor, name)       -> True when the creature is immune to the named condition (typed_executor.
                                                 condition_immune, after its own condition_immunity rows; sys-resources-states
                                                 2026-09-29: Imperial Mandate's "immune to Frightened while they can see or
                                                 hear you" depends on the leader, so no static row can carry it)
  generic_reaction_costs(engine, reactor, other, row, costs) -> replacement list of {resource_id, amount}, or None.
                                                 Pure pricing of owned generic reactions before affordability, consent
                                                 and payment; the same fresh row carries the price through all three.
                                                 Preserve paying pools and leave compiled rows untouched. ``other`` is
                                                 the attacker for missed/natural_1/ally_missed, None at other checkpoints
                                                 until a caller supplies its triggering creature. No hook/None = original
                                                 cost; return early for unrelated rows or missing trigger context.
  compile_block(block, spec, row, numbers)    -> list of rows for the bundle's typed_passives, or None (not this block)
                                                 numbers carries the compilation's own resolved numbers: pb, key_mod, cl,
                                                 armor, shield, and ``record`` -- this feature's typed record from the
                                                 same authority the compiler was given (compile_character's
                                                 typed_authority). A plug-in that prints its own numbers in reviewed
                                                 data reads them from ``record``, so an injected or revised authority
                                                 compiles its own numbers rather than rereading the file on disk.
                                                 Default-inert: ignoring the key compiles exactly as before.
  compile_weapon_traits(info)                 -> dict of typed weapon traits to merge, or None; info contains owned_ids,
                                                 weapon profile and current typed action. Ability owners qualify their
                                                 own weapon family. Default inert; no registrations means no changes.
                                                 Optional inventory_key binds a physical item to the base action and
                                                 its variants, including refined/given copies. Absent retains legacy mapping.
                                                 Thrown equipment uses existing dropped_at/disables_action/held_by
                                                 conditions; Returning Inscription checks active zone rule.no_teleport
                                                 or rule.no_extradimensional_movement at the landed item's cell.
                                                 Printed returning actions may retain one launched copy across targets
                                                 and recover it at technique_used, subject to clear-path/possession gates.
  compile_actions(info)                       -> list of ActionDefinition to add (info: owner_sheet, spheres, owned_ids,
                                                 mechanics, passives, numbers, short, actor_id, pb, mods, primary,
                                                 pools (available Path pool names), actions (original catalog), weapon_kinds).
                                                 pools lets optional paid abilities omit unavailable/duplicate payments;
                                                 adding it is inert unless a plug-in consumes it.
                                                 A passive row may set trigger_owner to its plug-in's name, claiming
                                                 complete trigger delivery for its feature_id, including choices/costs.
                                                 The compiler omits that feature's generic reaction rows. Absent metadata
                                                 preserves generic delivery; claim only owned features handled in full.
                                                 Free setting actions may supply parameters.setting_description for plain
                                                 sheet and persisted-status handling text (cost, benefit and choice lifetime);
                                                 absent text preserves the ordinary changeable-setting explanation.
                                                 parameters.setting_lifetime may supply the owning plug-in's plain
                                                 selection restriction for sheet/table descriptions and hovers.
                                                 It replaces the default changeable lifetime, not activation rules;
                                                 Absent metadata queries setting_lifetime, then retains the existing
                                                 free/changeable choice text if no owning plug-in answers.
                                                 scoped_checks uses owned check_against data to add explicit skill
                                                 escapes, gated by candidate_allowed while that buff is active.
                                                 check_modes/check_mode(actor, ability, skill, *, engine=None,
                                                 against_creature=None, hazards=()) is the shared check seam.
                                                 Named hazards are supplied by the roll site; both contexts combine
                                                 before cancellation. Missing contexts are inert. Never use for saves.
                                                 The roll site names what a check relies on:
                                                 combat.ability_checks.hide_check_mode resolves every source for a
                                                 Dexterity (Stealth) check made to hide and carries the
                                                 VISUAL_CONCEALMENT hazard, and a contest_against check spec may carry
                                                 its own "hazards". A "check_against" rule naming that hazard therefore
                                                 reaches a Hide or a check that declares it (Radiance's Expose False
                                                 Form: "Dexterity (Stealth) checks relying on visual concealment") and
                                                 leaves a Stealth check made for any other reason alone. Absent the
                                                 hazard, every check and every saved fight behaves exactly as before.
                                                 A check_against rule may also name skills; omitted/empty means
                                                 any skill on that ability, preserving legacy conditions. A named
                                                 skill and hazard must both match for the mode to apply.
  compile_basic_actions(info)                 -> list of ActionDefinition to add after all compile_actions outputs,
                                                 before basic-option modifiers and delivery/binding. Read-only info:
                                                 actions (feature/weapon catalog), short, actor_id, numbers, pb, mods,
                                                 attack_count (shared Attack action count), attack_profiles (weapon and
                                                 unarmed: on_hit passive effects and expected_extra_damage per Action).
                                                 Reusable for missing basic attack options; copy supplied effects before
                                                 editing. Return [] unless this creature needs the option. No registrations
                                                 or no additions leaves the catalog unchanged; saved catalogs are untouched.
  compile_resources(info)                     -> list of ResourceDefinition to add to the fighter's resources (info: owned_ids,
                                                 spheres, numbers, mods, pb); an id already declared is kept as it was
                                                 (rider lane 9: the Talismans sphere's Prepared Talisman Limit), except a
                                                 named pool (resource:named.*) the character's typed rows declared from its
                                                 printed resource row: the plug-in that owns that pool's printed size
                                                 replaces the default (rider lane C10: Reagent Stock's "Proficiency Bonus +
                                                 Alchemy key ability modifier" prepared uses, combat/ext/alchemy_stock.py).
                                                 Return a named pool only for a character that owns its sizing rule.
  compile_attack_ability(options, info)       -> ability abbreviation or None. Options are printed allowed abilities;
                                                 info: owner_sheet, owned_ids, mods, source, kind. Used for natural
                                                 and weapon attacks. Default is highest modifier, ties in option order.
                                                 Owned grants may add options; legal sheet choices take precedence.
  compile_action(action, info)                -> replacement ActionDefinition or None. Runs after basic actions exist;
                                                 replacements compose in registration order, each sees its predecessor.
                                                 info: owner_sheet, owned_ids, numbers, mods, pb, carrying, mechanics
                                                 (the supplied typed-authority records). Never mutate
                                                 inputs. Default inert: no replacement preserves the original action.
                                                 Shared by weapon-stat and armor-check plug-ins; ability choices remain
                                                 owned by their plug-in or typed data, never compiler id branches.
                                                 option_payments promotes fixed, unconditional self-payments on owned
                                                 typed options into admission costs; other effect payments are unchanged.
                                                 save_trigger_riders uses this to hang a typed modifier that the
                                                 compiler drops on an activated record (action/bonus_action/reaction
                                                 economies) onto that record's own action, and runs it from the
                                                 after_save_resolved seam. It adds the modifier scope
                                                 "own_path_features" ("one of this character's own Path or Subpath
                                                 features", resolved to concrete ids at compile time through
                                                 ability_source.is_path_or_subpath_feature, which counts the Path,
                                                 Subpath and tradition namespaces); the rider only fires on the
                                                 owner's own turn, for a creature inside a live area the feature
                                                 itself created, and honours the modifier's own limit. No other
                                                 scope is read by any plug-in.
  effect_choice(effect_type, actor) -> list[str] | None, the options a player chooses between for one effect
                                                 type, the actor's standing preference first so it is the answer
                                                 offered by default. None means nothing is chosen between, so a
                                                 caller asks nothing. Default inert (no registrations).
  effect_text(effect_type, option, target_name) -> str | None, one plain sentence naming what that effect does to
                                                 target_name and how long it lasts, asked of the plug-in that owns
                                                 the effect type so a caller never hardcodes one ability's wording.
                                                 "" / None means the owner has no wording and the caller falls back.
                                                 Default inert (no registrations).
  unresolved_roll_mode_text(ctx, effect, mode) -> str | None, plain GM wording for an Advantage/Disadvantage row
                                                 that the typed executor cannot resolve. First nonempty text wins;
                                                 None/no provider preserves the original summary. Presentation only:
                                                 no roll, payment, expiry or once-per-turn bookkeeping changes.
                                                 rider_outcomes supplies printed evidence for missing roll descriptors
                                                 across generated abilities; complete descriptors remain inert.
  reaction_geometry_allowed(engine, reactor, source, subject, row) -> False to reject a generic reaction before consent
                                                 and spending. source is the triggering attacker, subject the attacked
                                                 creature (including an ally). None/True preserves eligibility. Named
                                                 zone-line requirements are opt-in row metadata; absent metadata is inert.
  candidate_allowed(engine, actor, candidate, action) -> False to leave that choice out of what the fighter is offered now
    portable_steps uses this existing hook only for owned sealed C3AR Combustive
    Step actions. Its pure route query checks ground paths, observed occupancy,
    terrain, drag and voluntary restrictions against the separate 15-foot grant;
    the portable adapter executes through grant_movement with the same query.
    Range/teleport distance and radius-area geometry are unchanged. No new hook,
    action-catalogue field or saved-state field is required; other actions return None.
                                                 Persistent Darkness gates its separately compiled paid conversion
                                                 to an owned, active Darkness created this turn, current or held.
                                                 End Aegis gates selected bearers to that creator's existing marks.
                                                 Both return None for every other action; normal affordability applies.
                                                 Gate 5 restores only base setup/End Turn if every choice is vetoed.
                                                 system_bookkeeping records sorted vetoing_hooks provenance and a
                                                 plain log at INTENT_ACCEPTED, never during menu generation; ordinary
                                                 non-vetoed choices produce no diagnostic event.
                                                 frightened_movement checks every canonical MOVE path square against
                                                 visible sources of owned Frightened conditions; absent conditions
                                                 are inert. Shared path_allowed also guards free physical rider routes.
                                                 target_eligibility enforces caster-owned named-mark targets for reviewed
                                                 and older serialized actions.
                                                 Repayment denies primary self travel, while reviewed movement_role
                                                 "rider" keeps mixed powers available. Both predicates are pure
                                                 and repayment is inert without its owned payment condition.
                                                 equipment_hands uses shared hand_occupancy for physical weapon attacks
                                                 (Two-Handed, Versatile and Light/off-hand), delivered techniques and
                                                 legacy actions, and rechecks through attack_allowed during execution.
                                                 Unarmed Grapple/Shove retain weapon_source_id for Extra Attack
                                                 follow-ups: only those weapon attacks check the grip, after the
                                                 unarmed option resolves. The option itself is never weapon-gated.
                                                 Natural/unarmed actions are inert. Grapple uses the same free parts.
                                                 creature_targeting reads typed target.creature_types_any: a list of
                                                 alternatives, each a list of required explicit creature labels. All
                                                 labels in one alternative must match; unknown labels fail closed.
                                                 Inert unless that owned action carries reviewed target restrictions.
                                                 (Creeping Lethargy: an Action or a Bonus Action, not both); called only
                                                 when some module registers it
  cost_available(engine, actor, resource_id, amount, context) -> False to refuse one cost payment now
    A general payment seam, asked once per pool a cost is counted for, so no ability id is ever
    named in the payment path (combat/typed_reactions._holds). The caller has already read the plain
    engine count; this is asked only when the fighter holds the amount. context is a read-only dict
    of what the caller knows (the reacting block, the row), advisory: a subscriber answers from the
    actor, the pool, the amount and the event window it can observe, and must not mutate fight state
    or raise to refuse. Return False to make the payment unavailable (a reaction this fighter can no
    longer afford, an offer a printed rule withdraws); None for no opinion. Every subscriber must
    answer True to keep the payment available, so an ordinary fighter with no subscriber is unchanged
    and no subscriber is inert. Typed subscriptions are not used: this is a live gameplay query.
    prior_event_resources.prior_event_only holds a pool a passive trigger generated inside the event
    window now being paid for, which is the Foundation "a Pulse generated by an event cannot be spent
    on that same event" rule; the hold is resolution-local (engine.__dict__), rebuilt from observed
    events and never saved, so a fight saved before the rule existed is unchanged.
  success_deferred(feature_id)                -> True when that reaction's own plug-in decides its success later: its
                                                 "when: success" modifier talents compile to an ``on_success`` wrapper the
                                                 plug-in runs (Flowing Response, combat/ext/flowing_river.py)
  ai_candidate_allowed(engine, actor, candidate, action) -> False to keep that choice from the built-in AI only (a
                                                 player's menu keeps it; combat/gate4_context.py for_ai; fight audit
                                                 2026-09-29: the AI spent every spare Bonus Action recasting what was up)
  maneuvers(info)                             -> {"actions": [...], "rows": [modifier report rows]}: core maneuvers built
                                                 from the character's weapons and the talents applied to them (info:
                                                 actions, owned, mechanics, primary, pools, automated, foundation_resource,
                                                 actor_id, numbers, spheres)
                                                 iron_forms also freezes owned supported Form effects on natural
                                                 actions here; iron_form_on_hit offers one eligible choice on a
                                                 damaging reaction strike. Default-inert without the marker.
                                                 Elbow in the Door uses iron_elbow_space for its shared adjacent
                                                 square; zones.difficult_cells accepts optional difficult_target_ids
                                                 (actor id strings; absent = unchanged area policy). Its persisted
                                                 placement expires through turn_start at the owner's next turn.
                                                 iron_bell separately captures owned Bell-Ringing Body Shot effects;
                                                 iron_bell_on_hit asks its Meridian choice on Counter Palm's hit on
                                                 an already-Opened target (damage not required). It reuses the typed
                                                 modifier, leaves ordinary menu presets intact, and is default-inert
                                                 without the compiled iron_bell_effects marker.
  zones(engine)                               -> list of ZoneState worked out from the fight as it stands (never stored):
                                                 an aura centered on its owner (combat/zones.py typed_zones)
                                                 Compiled persistent areas may carry source_profile. The public
                                                 combat.zone_sources.of(zone) returns a copy of sealed reviewed tags,
                                                 source CL/save DC and source/duration provenance, or None for legacy
                                                 areas. Tags are explicit reviewed zone source_tags, never inferred
                                                 from sphere origin, Fire damage or visual material. This metadata
                                                 does not suppress an area or alter its cells/triggers.
                                                 Map-owned persisted zones are also safe: legacy turn/entry handlers
                                                 only process their known kinds with an extant actor owner; they do
                                                 not dereference the owner of unrelated typed/map zones. CHARGE_SPACE
                                                 retains its existing entry behavior.
  cover(engine, attacker, target)             -> int cover bonus against a ranged attack; the best one counts
                                                 (Gate4ControllerEngine._cover_bonus_actor_to_actor)
  stealth_search_mode(engine, searcher, hidden_foe) -> "ADVANTAGE" | "DISADVANTAGE" | None, before a Search action's
                                                 Perception check against one hidden creature (combat/stealth.py
                                                 search(); eye 2026-09-28: Stealth Surge)
                                                 stealth.search_modes collects native, Search and target contributions
                                                 unresolved. Sweep reuses one dice pair: NORMAL takes the first die,
                                                 Advantage the higher, Disadvantage the lower; no target rerolls.
  hide_check_override(engine, actor)          -> int check total to use instead of rolling for a Hide action, or None
                                                 (combat/stealth.py hide(); eye 2026-09-28: Cooperative Stealth)
  sense_range(engine, actor, sense)          -> int feet added to the current sense range; senses.of clamps at zero
                                                 before environmental range reductions. Evented modifiers own expiry.
  passive_perception_override(engine, creature, observed, baseline) -> int replacement or None, qualified by the
                                                 observation and both creatures' available senses and line of sight.
  passive_perception(engine, creature)       -> int bonus to Hidden Eye passive detection (eye_common.passive_perception;
                                                 lane 14: Court's chosen allies within 60 feet of its active owner). It is
                                                 the one bonus every Passive Perception reader sums, so a printed
                                                 reduction is a negative bonus (Scoundrel's Filthy Distraction, -5). Scoped
                                                 by the provider to the creature that owns the printed effect; 0 and None
                                                 are both no change.
  search_mode(engine, creature)             -> "ADVANTAGE" | "DISADVANTAGE" | None for an actual Search action,
                                                 excluding Analyze even if it chooses Perception (lane 14: Incarnation)
  steal_check_waiver(engine, actor, target, source, effect_row) -> True/False/None, asked by the Scoundrel Check
                                                 (combat/ext/tabik_scoundrel.py) before it rolls, for its own printed
                                                 Disadvantage row ("securely fastened, worn tightly, or held in two
                                                 hands"). True waives it for this roll (Master Thief, paid for with
                                                 Martial Focus by the provider), False forces Disadvantage on, None keeps
                                                 the printed reading. effect_row carries "object_difficult", whether the
                                                 object actually chosen is one those words name, so a provider is never
                                                 asked to waive a Disadvantage that was not printed; providers gate on
                                                 their own owned row and may ask through combat/ext/needle.py; nothing is
                                                 spent unless it is waived, and an unanswered or declined question
                                                 leaves the roll exactly as printed.
  scoundrel_object_choice(engine, actor, target, source, effect_row) -> {"difficult": bool, "on_success": [rows]} or
                                                 None, asked by the Scoundrel Check before it rolls for the printed
                                                 "Choose one accessible object" of a Steal-family check; source is that
                                                 ability's own typed source. The returned rows are effect rows run only
                                                 when that check succeeds, and replace the check row's own on_success,
                                                 because a chosen object IS the printed choice. "Take nothing" and a
                                                 decline are answers too: the provider returns the dict with no rows, so
                                                 the check is still made (it is what the action is) and nothing moves,
                                                 instead of falling through to the row's own default object. No
                                                 provider, another maneuver, an engine with no choice transport, or a
                                                 question nobody answered (a fight saved before the seam) returns None
                                                 and leaves the row exactly as compiled, which is what such a fight
                                                 replays. Owned by combat/ext/scoundrel_riders.py.
  incoming_damage(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int, points of damage
                                                 to take off this packet before Resistance and flat reductions, called
                                                 when a Factory fighter takes damage (typed_reactions.defend);
                                                 the results are summed. Critical cancellation uses critical_cancel.
  incoming_damage_bonus(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int or None,
                                                 pure additive bonus to a positive, non-immune Factory-target packet
                                                 before Resistance/reductions. Results sum; absent state is inert.
                                                 next_damage_bonus uses this for target-bound type/sphere benefits;
                                                 consumption follows positive DAMAGE_COMMITTED evidence, including
                                                 temporary HP. No-intent damage is included. Native/object targets
                                                 do not pass through defend and require a future general seam.
                                                 Shared portions barring reductions receive additions at commit;
                                                 damage_sharing sets _damage_bonus_already_applied to the taker ID
                                                 when defend already ran, then restores both transient flags.
  immunity_as_resistance(engine, kind, typed, source_actor_id, target) -> True when this packet's source treats the target's
                                                 Immunity to damage type ``kind`` as Resistance (which resistance_ignored
                                                 may then ignore): typed_reactions._defenses; rider lane C7, Myriad-Venom
                                                 Immortal. No handler: Immunity unchanged.
  resistance_ignored(engine, kind, typed, source_actor_id, target) -> True to ignore the target's Resistance to damage type ``kind``
                                                 (upper case) in this damage packet: ``typed`` is the source ability's
                                                 typed spec, ``source_actor_id`` who dealt it, ``target`` the creature taking
                                                 this packet (None when the packet has none) (typed_reactions.
                                                 _resistance_ignored; auto-lane5 2026-09-29: Edge Before Blood). AUTO56f2
                                                 2026-10-05 added ``target`` so a printed bypass can name one chosen creature and
                                                 one source ("your Spear talents against it"); a handler that does not need it
                                                 ignores it, and default-inert (no handler -> every target keeps its Resistance)
  hit_absorbed(engine, target, attacker, reduced_by) -> None, when the reaction(s) named in ``reduced_by`` (their feature
                                                 ids) took a melee hit's damage on ``target`` down to 0 (typed_reactions.
                                                 on_damage; auto-lane5 2026-09-29: Needle-Catching Reversal)
  apply_exploit(ctx, target, **kwargs)        -> list of the Exploit ids applied, called by typed_executor.apply_exploit when a
                                                 melee attack hits (task F 2026-09-29: combat/ext/needle.py owns the Piercing
                                                 Needle's Exploits: once-per-round allowance, Advantage/ally condition, Martial
                                                 Focus costs, Skewer / Court's two at once, and the choice among them).
                                                 kwargs: counted, qualifying, maximum, exclude, reason
  hold_tracking(engine, actor)              -> True | None; pure opt-in query for source-exact linked hold markers.
                                                 No owner means legacy marker data is unchanged. No events or mutation.
  linked_hold_tracking(engine, actor, topic) -> True | None; pure opt-in for dependent holds on this actor.
                                                 Condition rows use condition, parent_condition, hold_kind,
                                                 tracking (topic). Link to one same-source parent, choosing if needed;
                                                 default-inert: unowned/old bundles run the original condition row.
                                                 Tracked holds last UNTIL_REMOVED and end with their parent through
                                                 event/turn checkpoints; parent_hold and hold_kind are stored strings.
  hold_source(engine, condition)             -> (ordinary_physical: bool, source_cl: int | None) | None.
                                                 Pure classification for dynamically generated holds not present in the
                                                 action's typed effects. One owner; conflicting or invalid results fail closed. No inference
                                                 from condition names. Used by physical_holds.source.
  hold_companions(engine, actor, instance_id) -> iterable of linked condition instance ids | None; pure query.
                                                 physical_holds.end_hold removes the selected hold and existing linked
                                                 markers with replayable instance-specific events. Default: selected only.
  escape_grips(ctx, grips)                   -> list/tuple of instance ids or None; grips is an id -> ConditionInstance
                                                 mapping for the current escape Action (pins first; Trap supplies net
                                                 markers). One valid nonempty
                                                 unique subset narrows both the roll and removals. No result, conflicting
                                                 hooks or invalid ids preserve the legacy aggregate escape. May ask a
                                                 replayable choice through choice_options; default-inert for old bundles.
  escape_mode(engine, escaper, grips)         -> "ADVANTAGE" | "DISADVANTAGE" | None, before a hold's escape check
                                                 (typed_executor.block_escape_grapple and tracked Trap nets;
                                                 grips: the ConditionInstances holding it;
                                                 Formations, Binding Array: Disadvantage against a grip its side put on)
  escape_save_mode(engine, escaper, grips)    -> "ADVANTAGE" | "DISADVANTAGE" | None, before a grip's printed escape save.
                                                 Conflicting hook modes cancel. None retains the original save mode;
                                                 separate from escape_mode so check-only benefits never affect saves.
  close_ranged_ok(ctx)                        -> True when a hostile creature within 5 feet does not give this typed ranged
                                                 attack Disadvantage (typed_executor._enemy_adjacent_to_ranged; rider lane C7
                                                 2026-09-30, Bow Body). No handler: the 2024 rule unchanged.
  teleport_check(engine, actor, start, destination) -> False when a self-teleport fails (typed_executor._teleport; the caller
                                                 has already paid; Formations, Sealing Gate: a Charisma save to teleport through)
  masked_conditions(engine, attacker, target) -> {entity_id: {condition instance ids}} whose Advantage/Disadvantage does not count for this
                                                 attack, merged into senses.masked_conditions (Formations: Sensing Eye, Radiance)
                                                 target_knowledge.can_see also uses these target-specific masks for
                                                 Hidden/Invisible concealment. Full concealment masking permits sight
                                                 only through the ordinary geometry query; independent obscuring
                                                 areas, cover and unmasked Hidden remain effective. No masks: unchanged.
                                                 Shared perception reads plug-in masks through plugin_condition_masks;
                                                 innate sense masks are derived afterward and may query perception.
                                                 Keeping these queries separate prevents recursive Hidden checks.
                                                 PER-PROBE CALL: senses.perceives_cell asks about one empty square by passing a
                                                 lightweight stand-in (senses.cell_probe) through the same policy, so a fog
                                                 projection calls this point once per visible square per viewer. That probe
                                                 carries exactly senses.PROBE_FIELDS -- entity_id ("perception:cell"),
                                                 position, active, conditions (empty), summon, perception_cell -- and
                                                 NOTHING else: no team_id, turn_flags, display_name, modifiers, resources or
                                                 position-free queries. A hook that reads a creature attribute must first
                                                 return early unless senses.is_creature(actor) is true for it; a square can
                                                 never own a printed rule, so skipping the probe is always correct and never
                                                 changes a real actor. Reading a creature attribute off the probe raises
                                                 AttributeError, which ext.run catches and logs once per call (MMX105: 292,774
                                                 log lines in 3 hours from one subscriber). tests/test_ext_probe_shapes.py
                                                 guards every subscriber against the shape the engine really passes.
  summon_check(engine, owner, creature, spot, was_active, source_id) -> False when summoning ``creature`` to ``spot`` fails
                                                 (summons.summon restores it and logs SUMMON_BLOCKED; Formations: Spirit-Lock, Mountain-Sealing)
  command_reachable(engine, owner, group, creature) -> False to keep ``creature`` out of one command
                                                 (summons.commandable, the list an order actually reaches; the same list
                                                 feeds summons.command, so the creature neither acts nor receives the order).
                                                 ``group`` is the command group key and ``owner`` the summoner, for a rule
                                                 that is about the order rather than the creature. Pure query, default-inert:
                                                 with no subscriber the group's own command_range_ft decides, exactly as
                                                 before.
  zones.nonmagical_difficult_cells(engine, actor) -> map-owned difficult squares without applicable ability-created
                                                 overlap, before square exemptions. Pure shared source query;
                                                 Earth Packed Road Step may call it from difficult_exempt.
  difficult_exempt(engine, actor)             -> a set of (x, y) squares ``actor`` does not treat as Difficult Terrain
                                                 (combat/motion.py exempt_cells; zones.difficult_cells and
                                                 spatial_areas.difficult_at read it for an ability's or the map's own
                                                 terrain areas, combat/flight.py step_cost and combat/motion.py
                                                 terrain_for for the map's own difficult squares). For a benefit scoped to
                                                 an AREA (Formations, Court of the Ninefold Array: keyed allies; Sand Step;
                                                 Death, Court of the Ninth Grave: its servants inside the Domain) return the
                                                 area's squares while the creature stands in it. A live per-call query,
                                                 so the benefit is priced where its creature actually stands; empty/None
                                                 when it does not apply. Default-inert: no subscriber, every square is
                                                 charged as usual.
                                                 Return ``motion.TerrainExemption(cells, nonmagical_only=True)`` instead of
                                                 a bare set when the printed benefit says "nonmagical": the squares are
                                                 then free on the map's own ground (never magic) but ground an ABILITY
                                                 made there is still charged, because that is not what the line promises.
                                                 A bare set keeps the unrestricted scope, so an existing subscriber covers
                                                 both. Death's Court of the Ninth Grave is the nonmagical case.
                                                 Under an AREA-scoped exemption a wall an ability raised keeps its own
                                                 price to cross: "4 feet of movement for every 1 foot moved" is what that
                                                 wall costs to climb or wade, not ground underfoot, so no area-scoped
                                                 terrain exemption above removes it, and a square OUTSIDE the published
                                                 area keeps the full price the map gave it (combat/motion.py
                                                 wall_traversal_cost/unimpeded; combat/zones.py sync_walls keeps the two
                                                 layers apart). A whole-creature exemption, whose reach is the whole
                                                 map, still takes the wall's price with it: pre-existing behaviour,
                                                 deliberately unchanged.
  condition_excluded(engine, actor, condition)  -> True to retire ONE saved condition instance whose benefit an
                                                 ability no longer grants, so its rule row is not read at all
                                                 (combat/typed_executor.py condition_rules, consulted only when the
                                                 caller passes engine context; combat/motion.py ignores_difficult
                                                 does). For an ability that changed a printed effect and whose OLD
                                                 builds wrote a condition for it: a save made during the actor's own
                                                 turn is continued with that turn already begun, so the removal
                                                 boundary it waits for has not arrived yet and the stale instance
                                                 would keep applying the old rule. Returns bool; default-inert (no
                                                 subscriber, every instance reads normally); a pure query that never
                                                 edits the saved state or its record; must match only instances
                                                 the registering ability itself wrote (condition id AND its own
                                                 source), so other abilities' copies are untouched. Death, Court of
                                                 the Ninth Grave uses it for the whole-map ``ignore_difficult`` its
                                                 retired build wrote; its turn_start hook still removes that instance
                                                 outright, as a recorded CONDITION_REMOVED.
  difficult_zone_exempt(engine, actor, zone)  -> True to excuse ONE area's difficult ground for ``actor``,
                                                 False or None to leave it costing (zones.difficult_cells, asked
                                                 about each area that is difficult for this creature).
                                                 Unlike difficult_exempt, whose squares are removed from the
                                                 finished set, this answer belongs to that one area: a square
                                                 it excuses still costs when a second, unexcused difficult area
                                                 covers the same ground (Source's Quarry Walker over stony map
                                                 rubble with a magical stone area laid over it). A named
                                                 difficult_exempt square still wins over both. Default inert.
  zone_subject_allowed(engine, zone, subject) -> False to exclude a map/typed zone's triggered packet
                                                 and continuous inside conditions/modifiers;
                                                 None is default-inert. Pure query, before trigger accounting,
                                                 rolls and effects in zones._run.
                                                 Arguments retain the actual ZoneState and ActorState, including
                                                 map ownership even when its typed context uses a synthetic caster.
                                                 zones.sync_inside reconciles only zone-derived effects;
                                                 eligibility-owning plug-ins call it when their restriction
                                                 starts/ends, restoring eligible effects without stacking.
                                                 Does not suppress victim-carried conditions or legacy native zones.
  zone_talent_immune(engine, zone, subject)   -> True when one of the subject's own abilities makes it immune to
                                                 the negative effects this area's talents create, so the area leaves
                                                 it untouched. None is default-inert (nothing is immune). Pure query,
                                                 asked for the area's own creator by zones.clear_sighted, which uses it
                                                 for the continuous inside rows (zones.sync_inside), the area's
                                                 triggers (zones._fire), movement through the area, the AI hazard test
                                                 and the Dark sphere's own Darkvision reading (combat/senses.py).
                                                 The owning plug-in names the ability and recognises its own areas
                                                 (by the area's visual profile, not a display name); a subject that
                                                 is not the area's creator is never exempt here, so the printed
                                                 "an allied cultivator may choose to let your Clearsight apply"
                                                 clause stays GM-run rather than automatic.
  effect_subject_allowed(ctx, effect, subject) -> False to exclude a declared ordinary typed-effect recipient,
                                                 or skip a save/forced-movement subject; None is default-inert.
                                                 Pure query: it cannot add recipients or change state. Applies to
                                                 effect_subjects and ordinary damage, conditions, healing and other
                                                 rows using the shared subject resolver, including zone packets.
                                                 Saves, attacks and forced movement recheck at their own checkpoints.
                                                 Extension effects use public typed_executor.effect_subjects for the same filter.
                                                 Eligibility belongs to the owning plug-in (Force size limits,
                                                 Fold Prison isolation); absent restrictions preserve old execution.
  reaction_amount(engine, actor, row, effect) -> int replacing a reaction effect's amount, or None for ordinary dice/formula.
                                                 Default-inert; Needle owns weapon-damage parries.
  condition_applied(ctx, name, subject)      -> None, after a typed condition and companions land, outside its event dispatch.
                                                 Default-inert; catches/reactions can use normal attack resolution here without
                                                 suppressing downstream damage events. Not called for prevented conditions.
                                                 Generic condition reactions opt into this moment through typed
                                                 after="condition_applied"; prevent_condition always stays before
                                                 application. reaction_target="creature_in_reach" selects a legal
                                                 granted-attack recipient through the ordinary choice transport
                                                 before consent/payment; no targets means no offer or spending.
  mark_apply(ctx, effect, subject, expires, data) -> True if a plug-in performed placement/refresh; None uses ordinary marks.
                                                 Counted marks retain count and lifetime on the actual instance.
                                                 Handled refresh may retain an existing longer lifetime (Blood Thread's
                                                 Crimson Mark); the handler also emits mark_applied for that application.
                                                 Default-inert without the owning mark/ability.
  mark_consume(ctx, effect, subject)          -> True if a plug-in performed spending; False if it cannot pay; None uses ordinary removal.
                                                 Default-inert; mark_spent fires only after a handled successful spend.
  mark_spent(ctx, name, subject)              -> None, after typed_executor.block_spend_mark actually removes a
                                                 named mark the actor placed (charge-worker 2026-09-28: lets a
                                                 passive react to "once per turn when you consume a Charge...").
  mark_duration(ctx, name, kind)              -> a mark-expiry kind ("until_end_of_your_next_turn") to use instead of ``kind`` for a
                                                 mark named ``name`` the actor is placing, or None (typed_executor.block_mark; rider
                                                 lane 1 2026-09-29: Current Beyond the Skin's Charge lasts a turn longer)
  condition_turns(engine, actor, name)         -> a positive number of turns for the condition named ``name`` (the bare name, no
                                                 "condition:typed." prefix) that this actor is placing, or None to keep the printed
                                                 length. Consulted by an effect that places a named condition for a stated number of
                                                 turns (combat/ext/docket_maneuvers.py's ``batter``: "the target becomes Battered until
                                                 the end of your next turn"; Berserker's Beat Down makes it the second turn). The
                                                 writing ability still owns the expiry name it uses, so no other creature's condition and
                                                 no other ability change; pure query, no state. Default-inert: nobody registered means
                                                 the printed length.
  effect_turns(ctx, effect)                   -> a number of turns greater than 1 for one effect row whose expiry already names the
                                                 applier's NEXT turn (typed_executor.effect_expiry's START_OF_SOURCE_NEXT_TURN, from
                                                 the row's own expires_on, its duration kind or its printed "until the start of your next
                                                 turn"), replacing it with the start of that later turn of the applier
                                                 (effect_durations.token). For a printed "your Exertion effects that normally last until
                                                 the start of your next turn instead last until the start of your second turn" (Berserker's
                                                 Beat Down, combat/ext/berserker.py), which reaches every nested row of the talent's own
                                                 effects and its compiled "Batter: <talent>" attack variants alike. It only ever moves an
                                                 applier-next-turn expiry later, so no other name and no other ability changes; pure
                                                 query, no state, and values of 1 or less are ignored. Default-inert: nobody registered
                                                 leaves every expiry exactly as it was.
  mark_cap(ctx, name)                         -> {"add": n} and/or {"mul": k} changing the limit on how many marks named ``name`` the
                                                 actor may keep, or None; summed as (cap + adds) * muls (typed_executor.block_mark;
                                                 rider lane 1 2026-09-29: Charge limit +1 / +PB / doubled)
                                                 typed_executor.mark_capacity(ctx, name) exposes that same effective limit to
                                                 placement and optional replacement menus; absent caps/hooks impose no new limit.
  after_search(ctx, effect)                   -> None, after a Search action's own Perception check for hidden creatures
                                                 ran (typed_executor.block_search; effect["bonus"] is the searcher's
                                                 Wisdom (Perception) bonus). placed-effects 2026-09-29: lets a Search
                                                 also find a concealed Trap (combat/ext/trap.py) -- no hook told a
                                                 plug-in a Search happened, so this smallest one was added.
  check_floor(engine, actor, roll, dc)        -> int, the lowest d20 a plug-in lets this ability check count as
                                                 (Complete Mandala Auspice: "treats a d20 roll of 9 or lower as a 10"),
                                                 or None; ``floored`` below applies it where a skill check is rolled
                                                 (sys-resources-states 2026-09-29; no hook could change a d20 result).
                                                 To narrow a floor to the printed "one *such* ability check", read the
                                                 check's own ability from ``engine.d20_context()``; ``floored``'s
                                                 ``ability=`` keyword publishes one for a caller outside a d20_scope.
                                                 Returns None to leave the roll alone, which is how a printed "it may"
                                                 records a decline (AUTO20f1, combat/ext/d20_floor.py)
  Shared condition data (typed_conditions.json; typed_executor.condition_rules):
      condition_aliases resolves legacy IDs without rewriting saves. persistent_companions
      imposes independent, event-persisted conditions which remain after the parent ends
      (condition_lifecycle). damage_resistances lists damage types or ALL; condition_immunities
      uses the existing condition immunity query. roll_modes_require_source_visible qualifies
      attack/check modes using the recorded source and target_knowledge.can_see; callers supply
      engine context. Missing keys are inert. standard_conditions.roll_rules is the pure
      save eligibility query; attack_modes.condition_rows applies the same
      disabled_if_incapacitated_or_speed_zero flag to attack modes. state_event
      permanently removes forfeited benefits. condition_id_aliases preserves legacy core
      Dodge IDs. Masked attack rows keep real sight without rewriting actor conditions.
      critical_hit_within_ft uses attack_critical_qualification only after a confirmed hit,
      before cancellation and damage; qualifying hits record ATTACK_CRITICAL_RESOLVED.
      The resolved packet preserves cancellation provenance.
      duration_turns names {edge: start|end, anchor: source|holder}; effects, abilities and marks
      use duration_turn(). Counted units use duration_round_count(), also shared by zones/dockets.
  damage_defenses(engine, target, damage_type, typed, source_actor_id) -> list of defense rows or None; pure, default-inert
                                                 additions to the normal defense query. Rows use the compiled defense schema
                                                 (kind, damage_types and optional qualification fields). Resistance shares
                                                 suppression, attacker penetration, rounding and non-stacking with ordinary
                                                 defenses. Used by Energy Resistance and Protected Health Aegises; no saved
                                                 state is changed and removing the granting condition removes the benefit.
                                                 standard_conditions also reads data-defined damage_resistances (ALL or
                                                 damage types) from active conditions, using this same non-stacking path.
  damage_reduction(engine, target, damage_type, typed, source_actor_id, applied=False) -> int, a flat amount taken off a
                                                 packet of damage after Resistance (combat/typed_reactions._defenses; Ironclad
                                                 Line, sys-resources-states 2026-09-29). Called with applied=False while damage is
                                                 only being weighed (keep that call pure) and once more with applied=True from
                                                 defend() when the reduction really took damage off, for a side effect
  reaction_ally_allowed(engine, reactor, subject, row) -> False to keep one generic ally row from answering this harmed ally
                                                 (combat/typed_reactions._ally_row_ok; Warleader Command Responses)
  ally_subjects(ctx, effect) -> list of actors, whom an "ally" effect of this ability reaches instead of the nearest-allies
                                                 default (combat/typed_executor._allies_near; Warleader Shouts, whose audience includes
                                                 the leader and is limited to those who perceive it). None leaves the default alone.
  reaction_reach(engine, reactor, other, row) -> True when a generic reaction row reaches ``other`` although it is beyond the row's
                                                 range from the reactor (typed_reactions._generic_in_range; rider lane 10 2026-09-29:
                                                 Counterpressure measured from one of the reactor's Pressure Anchors, combat/ext/force.py)
  darkness_lifted(engine, zone, viewer, seen) -> True when this area of darkness does not keep ``viewer`` from seeing ``seen``
                                                 (combat/zones.py _blocks, after the senses; rider lane 10 2026-09-29: Radiance's
                                                 Revealing Light, Court, World and Heavenly Radiance suppress ordinary darkness,
                                                 combat/ext/radiance.py)
  zone_visual(engine, zone) -> dict | None: presentation-only extra facts for a zone's ``trigger_profile.visual``,
                                                 merged in by combat/gate5_service.py when the table's zone payload is built.
                                                 The plug-in reads the area's own typed provenance (source_profile.mechanic_id,
                                                 triggers[].id, inside[].id, augment_ids) -- never its display name -- and
                                                 returns only strings and booleans, e.g. which of a family's looks to draw.
                                                 Return None (the default) to add nothing: the area paints as it does today, no
                                                 saved field changes, and an area saved before this hook keeps its old look.
                                                 The table has to honour that too -- an absent or unreadable value is "draw this
                                                 exactly as before", never a default to pick for it, or every area the hook did
                                                 not answer for changes (static/tabletop/zones.js darknessComposition).
                                                 Sight, fog and obscuration rules never read this; it is how the table draws
                                                 (owner 2026-10-03 03:38, "a more transparent darkness for regular darkness and still
                                                 slightly transparent but almost pitch black for pure darkness"; combat/ext/tabik_dark.py)
  size_steps(engine, creature, role, purposes) -> int | dict | None: effective size categories for a comparison.
      role is "act" for the creature imposing an effect or "resist" for its target; purposes is a frozen set of
      "forced", "shove", "grapple", "prone", or "comparison". Pure owned query, default footprint unchanged.
      effective_size.cells adds answers from distinct features, including explicitly "additional" steps.
      Each owner resolves its own replacement clauses before answering, so "rather than one" never adds both.
      C7 and C12 use this single interface; purposes_of reads the typed effect rows, never an ability ID.
      C16 uses the same engine/role/purposes contract: brutal_shove effects add
      "shove" and "brutal_shove" purposes; brute_overrun adds "overrun". The Brute
      plug-in answers only for these comparisons and its owned rows/states.
Typed keys read by C12 plug-ins (absent = unchanged behaviour):
 requires_physiology: {"any": [trait names]} on an effect row: combat/ext/physiology.py
      uses effect_subject_allowed(ctx, row, subject) -> False to skip an ineligible
      recipient before its save/effect; otherwise None. candidate_allowed(engine,
      actor, candidate, action) -> False only for a wholly gated single-target
      action with no eligible recipients; otherwise None. Area creation is unchanged.
      The same key on a zone's "inside" rule, trigger or move_through row (the spec
      zone_recipient_allowed asks about) gates that row's recipients, so a standing
      area can be written for one kind of creature alone; without the key the rule
      keeps its printed who.
      Defaults and printed traits are in rules/creature_physiology.json; the shared
      combat.physiology.trait(actor, name) reader returns bool or None (unknown anatomy).
      Factory identities and summon records accept physiology: {trait: bool}; explicit
      values persist as reserved string labels through existing creature_types storage.
      Rows without this key, including old saved bundles, retain their behaviour.
  bound_object effect (combat/ext/bound_objects.py): an object with printed AC/HP guarding the condition instances / area this
      activation just made; destroying it ends them (and runs on_destroyed rows), their ending first removes it. Shared helper
      bound_objects.place(ctx, spec, holder=, instance_ids=, zone_ids=, position=) for plug-ins.
  choose_willing effect (combat/ext/willing_targets.py): one recipient is chosen and asked to accept.
      unwilling_save {ability, evidence, on_success?} adds the printed refusal path of a save-gated benefit
      ("If the target is unwilling, it makes a Wisdom saving throw"): the refusing target makes that save
      against the caster's own Cultivation Save DC and the row's effects land on a failure. In such a
      flagged row only, the willing branch drops every repeat_save in it, because a target that was
      never made to save has none to repeat; the refusal branch keeps them ("an unwilling target repeats
      the saving throw"). A row without unwilling_save is plain consent and is left exactly as authored,
      including a repeat_save its own effects carry. variant_suffix names the
      non-ally button allow_hostile_target adds (absent = " (willing creature)"); consent_text is the printed
      sentence read with the accept/refuse question. All three are inert without the key, and every existing
      choose_willing row (Muffle Footfall, Press Seal, Harmonic Healing Tone, Sky Mantle, Second Silhouette)
      keeps its original menus, labels and consent-only refusal.
if_creature_kind effect, and keys bonus_if_kind (damage rows, also on an attack's on_hit damage row), unless_kind (any row:
      not offered when all targets are excluded / filtered per recipient even on mixed targets; except_owner_modifier),
      disadvantage_if_kind (save rows) -- the shared kind
      classification combat/ext/creature_kinds.matches(actor, kinds) over persisted printed creature labels; "unclean" is the
      printed Radiance list. Unlabelled creatures never match.
      only_kind (any row: list of required printed kinds) uses the same candidate and per-recipient filters;
      absent = no restriction. Mindless, Possessed, Animated and compound spiritual labels are explicit labels,
      never inferred from names or immunities. Animated does not imply Construct.
      path_passive kind unarmed_kind_bonus {kinds, evidence}: owned passive adding PB to an unarmed hit's
      damage roll once per turn; attack_damage_bonus(ctx, target, effect) returns int or None, after_hit
      stores a round/current-actor string after a hit and after_miss clears pending state. Comparing that
      persisted turn identity permits off-turn reactions while suppressing a second hit on the same turn.
      A legacy nonzero integer flag conservatively spends the current turn on its first qualifying
      attack and becomes that turn's stamp, preserving eligibility on later creatures' turns.
      No matching owned row = no bonus or state.
      summoned_targets_only.or_kinds: optional printed kinds accepted in addition to a persisted summon record.
      exorcist_rite.target_kinds: optional printed kinds filtering its hostile selection list; absent = unchanged.
      Reviewed option include_in_menu: true (factory_compiler) preserves that printed branch beyond the legacy
      six-option cap. Original option indices/action IDs are retained; absent = original cap. This general
      data seam applies to any reviewed menu, with no ability-specific compiler dispatch.
  escape_option effect (combat/ext/escape_options.py): a condition record giving the held creature a "Break free" Action (and an
      adjacent ally "Help a creature next to you break free") with the printed check or repeated save; success ends exactly the
      guarded instances. Offered only through additional_actions to creatures holding a record.
      Multiple printed abilities use the existing choice transport: the rolling
      player chooses, AI prefers the estimated success chance including check
      Advantage/Disadvantage. Optional end-of-turn attempts ask that creature;
      AI accepts. No record = no choice or changed turn behavior. Public helper
      names/signatures and persisted record fields are unchanged.
  held_at_distance effect (combat/ext/approach_lock.py): a typed row that stops a creature WALKING
      toward or away from the creature using the ability, until the row's own duration ends. The
      row is {"type": "held_at_distance", "applies_to": <the ordinary subject key>, "mode":
      "closer" | "farther" | "both", "duration": <the printed turn>, "evidence": <the printed
      sentence>}; the anchor is always ctx.actor, because every printed version of this sentence
      names the user ("cannot willingly move closer to you"). It answers through the documented
      strict movement_attempt hook (see "Per-step movement"): the step that would cross the boundary
      is refused BEFORE it is paid, so position, step cost and the movement budget are unchanged and
      the refusal appears in MOVEMENT_COMMITTED.interruptions. Default-inert: a creature holding no
      record is never inspected, and no zone, mark or ability of another plug-in is consulted. Forced
      displacement and teleports do not pass through movement_attempt and are deliberately not
      restricted, because the printed words say *willingly*; granted movement DOES share the same
      checkpoint (see "Per-step movement"), so a step bought with a printed "move without provoking"
      grant is stopped as well. The saved record is strings only (data: anchor_id, mode, label,
      until, reading), so a table commit and reload round-trips; `until` spells the printed turn out
      in words (combat/ext/turn_words.py.until_words, shared with resistance_bypass) so the condition
      pill says when the lock ends, not merely that it does.
      Public helper: records(engine, actor) -> the creature's records (empty for anyone else).
      Printed uses (authority/typed_mechanics/rules_text.json): Pinning Strike "Prevent Approach",
      Meteor-Net Spear Art, World-Transfixing Point and The Point That Pinned Heaven to Earth's
      "Held at Distance" option. The condition's own label and reading come from the record, so the
      pill and the refusal read the same plain sentence (no condition_text.py edit, no new name).
  target_resistance_ignored effect (combat/ext/resistance_bypass.py): a typed row that sets aside ONE
      chosen creature's own Resistance to the damage types it names, for the row's own duration, and
      answers through the documented resistance_ignored hook, which takes the packet's target (see
      above; AUTO56f2 2026-10-05) and so can be scoped to that creature. The row is
      {"type": "target_resistance_ignored", "applies_to": <the ordinary subject key>, "damage_types":
      [...], "by_sphere": <the sphere whose abilities may ignore it>, "attacker_scope": "chooser" |
      "anyone", "duration": <the printed turn>, "evidence": <the printed sentence>}; by_sphere is
      optional and its absence means the printed sentence named no sphere. attacker_scope says whose
      damage the printed sentence lets ignore it, which is printed and not inferred (AUTO56r1f1
      2026-10-05): "chooser" (the default) is a sentence naming the chooser's own talents, "anyone" is
      a sentence naming no source at all. The pill's two lines name two different creatures without
      confusing them (AUTO56r2f1 2026-10-05): the first names the creature whose Resistance is set aside,
      and the handling line names the BENEFICIARY and promises no more than execution does -- a
      sphere-limited "anyone" row still requires the packet's own sphere, so it promises every creature's
      techniques of that sphere rather than every creature's damage, and a sphere-less "chooser" row
      covers every one of the chooser's techniques rather than only the technique that placed it. No
      subject, no condition and no rider. The record sits on the
      chosen creature and is strings only (data: anchor_id, damage_types, by_sphere, attacker_scope,
      label, until, reading), so a table commit and reload round-trips. Default-inert: a creature with
      no record, a damage type it does not name, a source outside the printed attacker scope and an
      ability from another sphere all keep the target's Resistance. Public helper: records(engine,
      actor), scope_of(row), SCOPE_CHOOSER, SCOPE_ANYONE.
      Printed uses (authority/typed_mechanics/rules_text.json): Heaven-Piercing Spear Light ("does
      not apply to your Spear talents against it", attacker_scope chooser + by_sphere spear) and
      World-Transfixing Point ("does not apply", attacker_scope anyone).
  move_without_provoking effect (combat/ext/quiet_step.py): a typed row for a printed "move N feet
      without provoking opportunity attacks from <creature>", resolving now through the shared public
      adapter combat.granted_movement.resolve_path(..., ignore_oa_from=...), so ONLY the printed
      creature's opportunity attack is skipped and every other enemy stays eligible (unlike the
      movement row's no_opportunity_attacks flag, a turn-long pool that spares everybody). The row is
      {"type": "move_without_provoking", "applies_to": "self", "distance_ft": N,
      "exempt_from": "target" | "creatures_hit", "optional": true, "evidence": <the printed
      sentence>}; "creatures_hit" spares one of the creatures this activation hit, which the user
      chooses, and spares nobody when every attack missed (the row says so). A hit is the settled hit
      reported by the documented attack_result hook ("covers hits, misses and zero-damage hits",
      AUTO56r1f1 2026-10-05), not a creature that lost normal HP: a hit soaked by Temporary HP or
      removed by Immunity still counts. That hook hands over the ORIGINALLY DECLARED target while native
      resolution may redirect the attack (AUTO56r2f1 2026-10-05: Guardian Interpose moves a blow onto the
      creature behind the guardian), so the name recorded is the confirmed hit's own provenance,
      Context.attack_damage_context.target_id -- the AttackDamage the engine built from the resolved
      target, which the executor itself reads for attack completion -- and the declared target is a
      fallback for a hit that carries none. hits_this_activation(ctx) is the public reader of that list.
      "optional" is for a printed "you may": a manual/Ask-me user may decline and an AI actor takes the
      step. The printed feet are the row's own allowance, not the creature's remaining movement
      (resolve_path's default use_movement=False), which the creature keeps; terrain, difficult ground,
      occupancy, volume, footprints, the voluntary-path restrictions and the exempted creature's reach
      still apply. Both questions (which creature, which square) go through the normal choice
      transport, so a manual or Ask-me user is asked and an AI decides. Default-inert: has_step(ctx)
      reads the activation's own typed rows (branch containers and the option rows the engine really
      executes -- rider_menu and choose_effects run option["effects"], and One Line Cannot Be Crossed
      prints its only step there -- never an ability id), and both the recorder and the effect return
      before doing anything else when there is no row,
      so no other character's attack writes into this plug-in's bookkeeping. No saved state is added.
      Printed uses (authority/typed_mechanics/rules_text.json): One Line Cannot Be Crossed ("move 10
      feet without provoking opportunity attacks from the target") and Flowers in the Storm ("You may
      move 5 feet after resolving all attacks without provoking opportunity attacks from one creature
      hit by this talent").
  until_words(engine, expires_on, actor=, holder=) is combat/ext/turn_words.py, a shared helper (not a
      hook): the plain words for a turn-bounded expiry, "until the start of Mo Ruo's next turn", or ""
      when the name is not a turn edge. Consumers: approach_lock.py, resistance_bypass.py.
Effect types: @effect("name", harmful=True/False) registers an executor block
  called as (ctx, effect) and declares pure leaf harm semantics for compiler
  recipient policy, reaction eligibility and risk. Omitted harmful=None is
  unclassified and retains caller fallbacks; it changes no execution behavior.
  effect_harm(name) -> bool | None loads registrations and returns this metadata.
  combat.effect_harm.classify_effect shares built-in and nested payload semantics;
  recipient filtering remains the caller's responsibility.
  Space-sphere effects (AUTO23 lane, 2026-10-04), each inert without the talent that types it:
  ``space_blink`` (combat/ext/space_blink.py): a Reaction hop. The row's ``distance_ft`` is the printed
      reach and an optional ``distance_ft_by_cl`` list of ``[low, high, feet]`` rows replaces it at that
      Cultivation Level (read exactly as the ability compiler reads one). The hop itself is the shared
      reaction teleport (combat/ext/teleport_steps.reaction_teleport: every legal unoccupied square is
      offered, the one farthest from the triggering creature first, a player is asked and may stay put,
      an unanswered fight takes that default), so teleport locks and zone entry apply as usual.
  ``space_swap`` (combat/ext/space_swap.py): the user and one chosen creature exchange squares. Every cell
      each arriving body needs is judged at the height it arrives on (``grid.volume_legal`` against the
      occupancy of everybody except the two swapping, plus the square the other one is arriving on), so
      neither creature blocks the other and a body that would reach over the other's new square is refused;
      refusing one square refuses the whole exchange. The creature that would be moved is asked through the
      bounded choice transport whether it agrees, because the printed "cannot force an unwilling creature to
      move" forbids the exchange without its answer: a creature on the user's own side that nobody can
      answer still goes along, any other creature's silence is not consent. Both hops answer the sealed-
      creature rule, ``teleport_gate`` and ``teleport_check``. Both moves are recorded as
      MOVEMENT_COMMITTED (integers only), so a saved fight replays the exchange.
  ``space_blades_no_oa`` (combat/ext/space_blades.py): the engine's own ``no_opportunity_attacks`` rule on
      the row's target, with ``against`` set to the reactor, for a printed "cannot make an Opportunity
      Attack against you". The bound form is what the printed line says; the turn limit comes from the
      row's own ``expires_on``. Inert without the condition.
  ``space_blades_bonus`` (combat/ext/space_blades.py): one condition on the reactor naming the creature a
      printed "the next melee attack you make against it" bonus is bound to, until the end of the reactor's
      own next turn. The ``damage_dealt`` hook spends it on the first melee attack that damages that
      creature, dealing the row's formula as its own typed packet, then removes it. Stored values are the
      bound creature id and the pill text only (strings), so a table commit and reload keep it.
  ``space_phase`` (combat/ext/space_phase.py): one condition on the user until the end of the user's own
      turn (END_OF_CURRENT_TURN), during which ``opportunity_allowed`` refuses every opportunity attack
      against that creature and ``condition_attempt`` refuses Grappled and Restrained *from an ordinary
      physical blow* (a landed unarmed strike or melee weapon attack; a spell, a zone, a conjured hand and a
      ranged blow are not ordinary physical means). Re-using the talent replaces its own earlier instance;
      an existing grapple is not cancelled.
  ``sword_magical_weapon`` and ``sword_manifestation`` are owned by the Sword sphere's plug-in
  (combat/ext/sword_sphere.py). Both are inert unless a reviewed row types them: the first applies the
  "the weapon counts as magical" condition an infusion prints, the second records which of an area's
  printed manifestations was chosen (its row may carry the ordinary "menu"/"option" tags, so
  combat/ext/menus.py gates it like any other option effect and supplies the player's free choice buttons).
  Sword-core's public sword_attack(ctx) and wielding_sword(engine, actor) queries are shared with
  sword_sphere: approved Sword delivery and readied grips govern rolls, AC and payment consistently.
  sword_sphere alone owns Iron Sword Body's Constitution roll hooks and Stamina alternative; it reads
  new owned passive blocks and historical modifier bundles, skipping already compiled Constitution variants.
  ``mist_form`` is owned by the Blood sphere's Scarlet Mist Form plug-in
  (combat/ext/blood_scarlet_mist.py). The row is a marker for the ability's own
  duration (effect_expiry, so Concentration ends it too); while it holds, the
  plug-in answers the documented creature-passage seams -- pass_through ->
  'difficult' ("move through occupied spaces as difficult terrain") and
  pass_through_entered -> its Blood Thread. The Thread question rides the
  documented choice transport: any creature the user moves through counts,
  asked of a player (taking it applies the Thread through the ordinary mark row,
  declining keeps the turn's use), taken automatically by the AI, and the use
  itself is the shared per-turn clock, so it is available again at the start of
  the next creature's turn. Inert without that talent; every other creature
  keeps the ordinary passage rules.
  ``diagnosis`` is owned by the Blood sphere's Physician's Pulse plug-in
  (combat/ext/blood_diagnosis.py). The row examines its target and records one
  readable PASSIVE_TRIGGERED line naming the printed ailments the table can see
  on that creature (bleeding, poison, disease, exhaustion); it changes nothing.
  No condition, resource or position is touched, and a target with none of them
  is reported as clean. Inert without that talent.
  ``spark_instrument_choice`` is owned by Lightning's Spark-Instrument plug-in. Its
  typed row names a feet range; on use it checks Charge on the primary target,
  offers one legal secondary creature to the owner (manual/Ask-me for player
  owners, automatic for AI), and applies one next-Perception-check penalty.
  Other mechanics are inert unless they explicitly type this effect.
  illusion_substantial_phantasm(ctx, effect) -> None: an owned Create Figment
  variant selects creatures inside its new figment, excluding creatures that
  recognize it as false, then runs the reviewed linked modifier's save/Study rows.
  Inert without the owned talent; the ordinary Create Figment remains unchanged.
  figment.creation_costs(engine, actor, action) -> tuple of (resource, amount)
  payments: public pure quote for Create Figment and linked variants. Combines
  engine-effective upfront costs with selected option costs (including Court's
  free sight/sound); candidate filtering sums payments by resource. No kit adds
  no option cost. Existing helper contracts and payment order remain unchanged.
Typed keys and seams added by the Scoundrel sphere (AUTO11 2026-10-04; absent = unchanged behaviour):
  ``cover_anchor`` (combat/ext/scoundrel_riders.py, typed row: evidence): a Bonus Action that names the adjacent
      creature that covers the user. Three printed things are asked through combat/ext/needle.py ask rather than
      assumed: which adjacent ally, whether that ally agrees ("one willing adjacent ally"), and whether it really
      can cover half the user's body ("must plausibly cover at least half your body"). The answer is stored on
      ``condition:typed.bob_and_weave_anchor`` until the start of the user's next turn, and the
      ``directional_cover`` hook in the same module then gives Half Cover (+2 AC) to every attack crossing a sight
      line while that anchor is still adjacent and still able to stand in it (gone, defeated or Incapacitated ends
      it). The anchor gains nothing and spends no Action: only the creature that paid answers. An AI ally agrees to
      an ally and refuses an enemy. No adjacent ally, no agreement, no cover. An adjacent OBJECT is not offered: a
      loose object is an item's dropped_at square on the creature that dropped it (combat/carry.py), not a free
      standing anchor, so that half of the printed Requirement stays with the GM (a rider).
  ``rerun_ability_option`` (same module, typed row: ability): a Bonus Action that runs that ability itself. Its own
      option actions give the printed "Choose one" menu when the ability has one (Dirty Trick); an ability with a
      single resolution (Steal) runs its own typed row whole. Either way the effects run under the rerun ability's
      own typed source, so its printed results, saves, riders and Difficult-Object branch stay its own, while the
      triggering action keeps its cost, economy and target. Used by Quick Thievery, once per turn for 1 Martial
      Focus (its compile_actions twin); other mechanics are inert unless they type this effect.
  ``steal_check_waiver`` hook, ``scoundrel_object_choice`` hook and the Filthy Distraction condition are documented
      with their hooks above. Filthy Distraction lasts until the end of the thief's next turn
      (``scoundrel_riders.end_of_your_next_turn``). Dirty Trick hindrances end at the start of that same
      thief's next turn; both use the source's clock, with different start/end boundaries.
  ``steal_equipment`` (same module, typed row: disadvantage, steal_object): Steal Equipment's own Action. It is
      published by the module's ``steal_equipment_actions`` for a creature that owns that talent's
      ``scoundrel_talent`` block row (combat/rules/feature_blocks.d/auto11_scoundrel.json), costs 1 Martial Focus,
      and runs the shared Scoundrel Check with its printed Disadvantage as one more source of that roll. Absent the
      talent: no action is published at all.
  ``transfer_object`` (same module, typed row: item, as, from, ability, object): the printed result of a chosen
      object -- into a free hand (``held_by`` plus the ``hand`` it went into, which ``stolen_object_hands`` reports to
      the ``hand_occupants`` query so the object really occupies that hand), into a legal unoccupied square within reach
      (combat/carry.py's own DROPPED record with ``dropped_at``, asked with the shared Needle cell helpers), or into
      the target's hands (planting). ``object`` names WHICH object of several identical ones the row moves
      (``scoundrel_riders.object_id``: whose bundle lists it, and its item), so one object never takes another's
      record. ONE record per object, filed on the creature whose bundle lists it -- which is
      what combat/carry.py reweighs from, and what gives the object its name and weight -- and moved in place by
      ``_transfer_record`` on every later handover, so one object never has two homes at once and its ``owner`` /
      ``item_name`` / ``object_id`` travel with it; an object handed back to its own owner loses its record, because
      it is home. A record written before ``object_id`` existed is still that creature's own object, because it is
      filed on the bundle that lists it. A handover
      moves both loads in the same event and replays from a saved fight; a weapon also carries the action it
      disables. One implementation serves Steal, Cleaned Out, Switcheroo and Steal Equipment; nothing here reads
      another plug-in's private state.
  ``utilize_end`` registrations: ``combat/ext/utilize_end.py register_ending(key, spec)`` is the table's public way
      for a plug-in that files a marker condition to add its own Utilize ending (target_kind may be ANY_CREATURE
      when the printed line lets any creature within reach do it, not only an ally). Entries are compiled like the
      built-in Face Strike and Bleed Air ones -- one Action per entry, offered only against a creature bearing that
      marker -- so a fighter compiled before still carries no such action and saved fights replay unchanged.

Effect types added by AUTO75 (absent = unchanged behaviour; combat/ext/ash_talents.py):
  periodic_damage_state effect: a printed "takes <dice> <damage types> damage at the start of each of its turns"
      state that outlives the activation that made it. The row carries ``name``, ``label``, ``applies_to``, an
      ordinary ``duration`` (the engine's expiry names), an optional ``requires_condition`` (the printed state the
      damage hangs on, e.g. "Restrained by accumulated ash", matched on the holder's own conditions by the same
      source and caster) and ``damage``: a list of the printed damage rows
      ({"dice": {"count", "sides", "bonus"}, "flat", "damage_types"}). It is stored as one typed condition
      (condition:typed.periodic_damage_state.<name>) whose data holds only those printed numbers, names and the
      anchor's name, so it survives a table commit and reload; the turn_start hook delivers each row through the
      ordinary typed path (a Context on the ability that put the state on, as rider_damage_states does for its own
      turn-start riders), so the holder's damage reactions and Ash Ward answer it, the best of a listed choice of
      damage types is chosen by typed_executor.choose_damage_type, the damage_dealt subscribers are notified, and
      a creature that dies to it dies the ordinary way. It ends with its own expiry or with the group that
      recorded it (a repeat saving throw, Concentration). No row, no anchor, or no compiled action = no damage.
  move_typed_area effect: a printed "As a Bonus Action, move one of your <areas> up to N feet". The row names
      the base ability whose areas move (``area_source``, compared against each compiled action's typed source,
      so every modifier variant of it is included), the reach (``distance_ft``), a ``choice`` id and a ``label``.
      The owner is asked which of its own active areas to move (only when it has more than one, and each area is
      labelled with where it is, because two areas of one kind share a printed name) and then which square it
      lands on: every legal centre within the printed reach, labelled with the distance the area will travel,
      chosen by clicking a highlighted square on the map and answered automatically for an AI. Both questions may
      be declined; declining either one leaves every area where it was and logs a plain line saying so (an AI still
      answers both automatically, and a fight nobody is answering still takes the preferred square). The area
      keeps its identity, cells, duration and printed rules and is published again, so a saved fight replays it
      as the same area. No such area, or nowhere within reach, = a GM line saying so. Shared API:
      ash_talents.area_destinations / in_ash_or_fire; the two choice ids are namespaced
      (choice:needle.move_area_to:<choice>, and <choice>.which_area: for the "which area" question).

Typed keys and seams added by rider lane C14 (absent = unchanged behaviour):
  suppress_area effect (combat/ext/area_suppression.py): an action aimed at a square suppresses a stored area there (whole, or the
      aimed square; plug-ins may pass any squares to area_suppression.suppress) after an optional check against the area's own save DC, until a printed turn boundary; the
      squares leave zone.affected_cells and come back when the record is due (turn_start/turn_end sweep), unless the area ended.
      Records live in zone.trigger_profile["suppressed"] (JSON only). Seam in combat/zones.py: follow() keeps suppressed squares
      out of a re-centred area (_unsuppressed); zones.moves_with_owner / zones.area_cells are public. No record = cells as before.
      Shared API: area_suppression.areas_at / suppress / suppressed / records / save_dc.
      Effect-row mundane: true = nonmagical, false = magical; absent = unknown.
      zone_sources.mundane_rows(rows, default=None) -> bool | None checks inherited
      flags including nested rows; disagreement or missing flags = unknown.
      zone_sources.compile_profile seals unanimous zone-row flags as integer mundane (0/1)
      in source_profile; legacy areas are never reclassified. area_suppression.magical(zone)
      returns True/False/None. areas_at(engine, cell, excludes=(), magical_only=False)
      filters only when requested, using the same eligibility for execution, player and AI.
      suppress_area and end_effect accept magical_only: true (unknown sources are ineligible).
      Summoned constructs have no sealed classification and are ineligible for this filter.
      effect_mundane(engine, source, actor_id) -> bool | None reads unanimous explicit
      flags in saved actions or owned passive options; existing action-level mundane is
      the fallback for unannotated action rows. end_effect uses it for creatures.
      No flag/filter = prior behavior; no new hook or engine patch.
  ability_lockout effect (combat/ext/ability_lockout.py): a condition record on a creature barring one named ability
      (candidate_allowed, player and AI alike) or watching it ("watch": its next use runs the locker's on_reuse rows, "before" at
      INTENT_ACCEPTED or "after" at resolution_final). Before-reuse NEXT_ATTACK attack-mode modifiers affect only the
      reused activation: the engine consumes them on its first attack, and resolution_final removes unused ones by ID
      with ordinary removal events. Other modifiers and after-reuse effects keep their existing scope; no watch = inert.
      Existing saved watches need no migration. Which ability: pick "triggering" / "last_used" / "seen" (+ "mode":
      "choose" then "pick": "chosen" across a save). Named ability = an action compiled from a typed mechanic
      (ability_source.mechanic_of); the table's own buttons and weapon attacks are never locked. Shared API: used / last_used /
      triggering / lock / records. Optional ctx.typed.effect_name carries a delivered effect's display identity
      separately from its action/intent (Touch the Point supplies the selected seal's name). Absent = action name.
      Records add optional source_name and label_text presentation strings; existing mechanical fields remain unchanged.
      Stored label includes the deadline; status_description renders native source/holder and counted turn deadlines
      against current counters, including old records without these optional strings. No record = no presentation change.
  choose_effects (combat/ext/effect_choices.py) also runs in a generic reaction row's context (its feature id is the source).
  forced_movement_bonus(ctx, subject, effect) -> int | None. Pure additive query in typed_executor.block_forced_movement: feet
      added to a typed push/pull's printed distance before the forced_movement_distance choice, the moved creature's reactions
      and forced_movement_reduction. Non-positive or non-int answers are ignored; no answer = the printed distance. Answered
      from feature-block rows by combat/ext/push_lengthening.py (Weighted Links, Gravity Domain, Storm Without Direction) and by
      rider lane C7's combat/ext/momentum_body.py (Gather and Return: +5 to the next forced movement ctx.actor imposes).
  concentration_mode_removed(engine, actor) -> iterable of "ADVANTAGE"/"DISADVANTAGE" | None. Pure query in
      combat/concentration.py save_mode: those modes do not count on the actor's Concentration save ("cannot benefit from
      Advantage on Concentration saving throws": Meridian Stillness Field, combat/ext/pressure_points.py). No answer = the
      modes as before.
  Opening Phrase's "+PB to one Concentration saving throw" uses save_bonus with source system:combat.concentration
      (combat/ext/music.py); the SAVE_ROLLED of that save uses it up. The delivered roll_id and actor identify
      the original save even if earlier event hooks append more events. No held bonus = no change.
  object_damage rows (combat/ext/objects.py) take needs_condition: the row counts only while the attacker holds that condition
      (Mountain-Felling Axe Body's form).
  summons.json sources (combat/summons.py): "control"/"load" share a control_limits pool at compile time (Death Control
      Limit = PB); "group"/"name" reuse a creature's stats under another group; "command_group" gives several groups one
      Command; a creature's "footprint": "large" makes a 2x2 summon. Absent keys = the old per-group behaviour.
Typed keys and seams added by rider lane C15 (absent = unchanged behaviour):
  hold_escaped(engine, record) -> None. A creature got out of a hold (grip, restraint, pin, Chains Bound), reported by the
      shared helper combat/ext/hold_escapes.py ``escaped(engine, holder, held, how, by=, source=, way=, object_id=)`` from every
      path that frees a creature: the table's escape-a-grapple Action (typed_executor.block_escape_grapple), Break free and its
      help (escape_options), a bound object destroyed (bound_objects), a Chains tether that breaks (chains_sphere), a grip whose
      held creature was moved out of reach (grapple_range), and the engine's own end-of-turn repeat saves (read from their
      CONDITION_REMOVED ``repeat_save`` payload). record = {"holder", "by", "how" (physical / spiritual / teleportation /
      forced_movement / outside_assistance: the printed Prisoner's Bell kinds), "way" (repeat_save / save / check / object /
      movement), "object", "source", "at", "holds": [{"instance_id", "condition_id", "source", "owner"}]}. The helper records
      nothing; listeners record their own events. Holds that run out, end with Concentration or are released are not escapes.
      Listeners: combat/ext/chains_sphere.py (Prisoner's Bell), combat/ext/repeat_saves.py (on_repeat_success rows).
  on_repeat_success (condition row with repeat_save): typed rows run as the hold's user against the creature when its
      end-of-turn repeat save ends that hold (Chain Prison: "If the target succeeds, it remains Bound until the start of its next
      turn"; combat/ext/repeat_saves.py).
  condition_data {"tether_ft": n} on a condition row: the creature is tied to the creature that applied it; its Move squares
      farther than n feet are not offered (combat/ext/move_limits.py ``tether``; plug-ins with another saved shape use
      ``move_limits.register_tether(condition_id, reader)``: chain_tethers.py's Meridian/Prison Tethers). The Chains Bound
      tether breaks past its length (chains_sphere.py: TETHER_BROKEN; teleport/forced = an escape).
  typed condition "bound" (combat/rules/typed_conditions.json + combat/ext/chains_sphere.py): Speed -10, no Dash (no_dash.py),
      Disadvantage on its own escape checks against a hold (escape_mode).
  condition_data {"rule": {"no_dash": true, "requires_ground": true}} on a condition row: the general printed form "if the
      target is standing on a solid surface, it also cannot take the Dash action" (Alchemy's Binding Dregs Field Formula).
      The clause is qualified where the printed sentence puts it, as the effect resolves, through the condition_state
      seam above: combat/ext/alchemy_riders.py solid_surface_qualification skips the application for a subject that was
      above the board (position.z, the same altitude test altitude_abilities.py uses) and lets every other row through
      unchanged. Once applied it is an ordinary condition for its own printed duration, so the action menu (no_dash.py),
      a typed Dash (block_movement) and the printed condition text agree for as long as it lasts, whatever the creature
      does afterwards.
  bound_object rows: "ac"/"hp" formulas take "half_pb" (rounded down); "kind": "chain" makes a BOUND_CHAIN object (a Chains
      sphere Chain Object: AC 15 + half PB, HP 5 x CL, Resistance to B/P/S unless printed otherwise).
  escape_option rows: "skills": {"STR": "Athletics", "DEX": "Acrobatics"} -- one skill per ability.
  feature block "prisoners_bell" (combat/rules/feature_blocks.d/riders_c15.json): marks a Prisoner's Bell owner.
  reaction_spend(engine, reactor, row, commit) -> "free" | None. Whether ``reactor`` may take reaction ``row`` without spending
      its Reaction (typed_reactions.reaction_waived; consulted by _can_trigger / _can_react(engine, actor, row) for availability and
      by _open / spend_reaction when the reaction is taken -- _open's answer is kept for that use, so one use never takes two
      waivers). commit=False is a pure query; commit=True records the answering plug-in's use. No answer: the Reaction is spent
      exactly as before. Plug-ins that resolve their own reactions call typed_reactions.spend_reaction (jester_riders,
      flowing_river). Answered by combat/ext/reaction_economy.py from feature-block rows "reaction_economy": grant "free" (once
      a round without the Reaction: Lightning Sovereign's Static Guard, No Center Under Heaven's Flowing Response, a Court's
      Punchline, Chaos-Step's Swaying Guard), "extra" (one additional Reaction a round, after the ordinary one: Adamant Guardian,
      Scoundrel / Drunken Style sovereigns, only for their sphere's talents), "no_cost" (via generic_reaction_costs: Fate-Sovereign's
      Twist of Fate); "focus_instead" (the printed "you may expend Martial Focus to use this without spending your
      Reaction": Shield's Active Defense, Drunken Style's Swaying Guard -- pays nested "pay" {"resource_id", "amount",
      "until_owner_turn"} instead. Ask-me owners choose Reaction or Focus through reaction_consent and choice_options
      (spend_choice); decision_text describes both costs before consent. AI uses its ordinary Reaction first.
      pay.until_owner_turn blocks ALL covered uses after payment until the owner's next turn, including free grants
      and restored Reactions. Its integer flag uses the existing owner-turn reset. Old saved once_per_round rows
      retain their prior interpretation: exhausted paid grants are excluded by the same pure eligibility
      query for consent, cost text, preview and commit. Prompt deadlines are conditional on Focus payment.
      "covers" features / sphere / punchline / any; "while_state" a
      states.py state. Multi-grant rows carry
      reaction_grant_key (a stable fingerprint of grant/covers/while_state), keeping their per-round counters independent.
      Existing single-grant keys remain unchanged; a legacy feature-wide usage blocks every grant for that round only.
      Native Opportunity Attacks use the same strict, single-use payment query.
  attack_mode_removed(engine, attacker, target, ranged) -> iterable of "ADVANTAGE" | "DISADVANTAGE:invisible" |
      "DISADVANTAGE:blinded" | "DISADVANTAGE:obscured", or None. Pure query (combat/ext/attack_mode_removal.py ``removed``): the
      attack cannot benefit from Advantage, or ignores one source of Disadvantage. ``ranged`` True/False for a typed attack (the
      current attack_scope frame), and the native packet supplies its own ranged flag. combat.attack_modes applies removal
      before mode cancellation across conditions, modifiers and typed strike contributions. It does not mask sight or
      change stored conditions. Answered from feature
      blocks "attack_mode_removal" (Piercing Senses) and zone rows' "attack_mode_removal" key (Storm Without Direction).
  critical_range(ctx, target) -> int | None. The lowest natural d20 that is a critical hit for this typed attack; the lowest
      answer counts. The native critical-range adapter decides critical status before defense/cancellation and rolls one
      damage packet. combat/ext/critical_hits.py preserves its public compatibility query without adding another packet.
      Answered by feature blocks
      "critical_range" {"lowest", "pair_role", "while_state", "weapons"} and lane4_crit.py's Find Gap.
      Historical Critical Follow-Up rows and Sword Saint Incarnation are deferred. New auto94 Critical Follow-Up rows
      require an actual readied Qualifying Pair and the own-turn Answering Weapon strike, excluding reaction/OA copies;
      martial_dual_wielding.qualifying_pair supplies the public current-grip query, also used by Focusing Defense.
      Focusing Defense evaluates that query once per live Dodging instance, at that instance's
      trigger ("While Dodging WITH a readied Qualifying Pair"), and stores the answers as one
      ';'-separated '<instance_id>=<0 or 1>' string on the owner's turn_flags through the strict
      state_event lifecycle seam (one registration, never also at "event"); its "ac" hook then requires a
      live eligible instance AND the pair still readied, so drawing a weapon after a Dodge taken
      without one grants nothing, stowing it ends an increase that drawing it again restores, and ending
      one overlapping Dodge never cancels another; the last removal deletes the record. Instances
      in a save holding no record keep their inherited live-pair rule; an earlier bare integer
      preserves its recorded answer for existing instances. New instances are judged normally.
      Nothing is keyed on the Dodge's source, so
      a Dodge granted by another feature is judged the same. No new hook point.
      Sword Saint needs actual
      integrated-Blade eligibility, never merely the carried weapon's Blade category. Find Gap uses the native range seam.
      Helper signatures and hook contracts remain stable for C17. combat/ext/sword_sphere.py silent_killing_line answers
      this hook directly for Sword Intent Manifestation's Silent Killing Line ("Your Sword attacks and Sword-Qi attacks score
      a critical hit on 19-20 against creatures bearing your Sword Intent"): it reads the printed manifestation mode from
      the caster's own Sword state and the target's mark, so no feature-block row and no ability id is needed in core.
  healing_pending(engine, target, amount, healer, source, kind) -> int | None. Points to take off HP ("hp") or Temporary HP
      ("temp_hp") about to land, knowing who heals; answers add up, never past the amount. Asked by typed_executor._reduced_healing
      (every typed heal and the plug-ins healing through it; keyword healer/source) and native HP/Temporary HP application.
      A strict checkpoint validates whole nonnegative reductions and rolls back provider failures.
      Answered by combat/ext/healing_interception.py: effect "intercept_healing" records (Wound That Refuses
      Dawn), Diminish Recovery (Yin; spends the Waning Mark), Reversing Pulse (a Reaction: Constitution save, halve / -PB).
      Eligibility includes marked allies/self; optional choices use automatic=False and a decline fallback for those targets,
      preserving hostile AI preference without hiding player options. Yin's ally-benefit restriction is stated for the player
      to judge. Display-only choice_prompt.action_context identifies the healing action, healer and affected creature;
      existing healing helper signatures, choice IDs and stored-record contracts remain unchanged (including C17 consumers).
  save_choice(ctx, subject, effect, options) -> ability string | None. Called before save reactions/rolls; the first
      answer in options selects the saving-throw ability. No answer preserves the existing larger-base-modifier selector.
      save_choices opts in only with target_choice=True on the save row; asks the target through the ordinary transactional
      choice transport on player and AI turns. AI targets prefer the highest base modifier, without previewing/consuming
      conditional bonuses or reactions. Optional name identifies the effect separately from its delivery action;
      choice_text explains the outcome/deadline to the defender.
      No flag = inert, including unflagged old saved actions. No new persistent field or expiry token.
  choice_reactors(engine) -> iterable of actor IDs | None. Pure potential-choice query for the service's AI-step probe;
      only manual control modes are enrolled. Actual checkpoints still decide whether to prompt, and AI actors answer
      automatically. No answer = existing Ask-me/passive/condition ownership behavior. save_choices scans opt-in catalog
      rows; shi_pressure_points scans its authority-backed seals, which also covers existing saved bundles.
      qiweaving_bond enrolls potential Shared Reservoir givers carrying a bond from an owner whose saved catalog
      has that action; unrelated reaction plans are unnecessary. No Reservoir action or bond is default-inert.
  before_target_reactions(ctx)                   -> None, strict, before typed_reactions.on_technique_start receives the
                                                   roster. An opted-in transactional choice may replace ctx.targets with
                                                   a unique subset of its existing eligible ActorState objects. The final
                                                   roster goes to target reactions, saves and effects. Invalid replies,
                                                   widening and exceptions abort the transaction; player pauses preserve
                                                   the existing answer/replay transport. Default-inert without an owning
                                                   effect. See combat.recipient_choices; no transient roster is persisted.
  rider_choose_area_recipients(ctx, effect) -> None: typed area-save rows opt in when the printed rule says to choose creatures;
  manual and Ask-me actors can choose from the shape-aware area roster, while automatic actors use hostiles unless the row
  sets automatic_friendly. hostile_only applies a printed hostile-recipient restriction for every controller. The effect
  uses the existing choice checkpoint and replaces only this action's recipients. Missing effect rows preserve area behavior.
  rider_outcomes' compile_action provider seals size_ft_by_cl-only chosen areas
  at their owner's CL, with ordinary CELL/SELF aiming and cone/line reach.
  It requires an explicit selector; fixed-size and sealed saved actions are inert.
  sound_equipped_resonance(ctx, effect) -> None: the opt-in Body Resonance Strike
  hit row marks a target with represented worn armor, a carried shield or a held
  weapon. Inert without that paid modifier; uses existing carry state/mark expiry.
Sphere chassis (rider lane C16, 2026-09-30): Guardian, Brute, Verdant Growth. All default-inert: nothing answers for a creature
without the owning compiled rows, and bundles sealed before the lane (saved fights) keep their old paths.
Protection Ward edge (AUTO69, 2026-10-05). One crossing gate for every Protection rule that turns a voluntary step back,
in combat/ext/protection.py. All default-inert: every reader needs a live Ward zone of its own talent or a bearer of one of
its Aegises, so no other character and no older saved fight changes.
  zones.create spec key "profile": an optional JSON dict a plug-in records as its own configuration for the area it is
      creating (the creature families a Repel Spirit-Kin Ward turns away and the creatures standing inside it when it
      appeared). It is copied onto ``zone.trigger_profile["profile"]`` and recorded by the area's own ZONE_CREATED event
      like every other profile field, so a saved fight reloads with it; combat/zones.py ``prospective_zone`` is the seam
      (protection.make_ward builds the same spec through it to read those initial exemptions off the real sphere before
      anything is placed). Absent (every other area, and every area saved before this lane) = unchanged.
      Reader: protection._ward_profile(zone) returns {} for an area without one.
  movement_attempt(engine, mover, previous, next, intent) -> None or {"stop": True, "source_id", "label"}: the printed
      boundary saves (Protection's Impedance Wisdom save, Repel Spirit-Kin's Charisma save) are rolled here, before the step
      is paid for, so a refusal leaves the mover where it was and the rest of its path untouched. Same contract as
      combat/ext/gravity_boundary.py's Event Horizon Prison. It is also the seam movement granted by an ability reaches,
      so it re-checks a barrier a failed save already stored (see "ward_apron" below). Teleports and forced displacement use
      their own ``forced_movement_attempt`` / ``teleport_gate`` seams and are not "attempts" to walk.
  typed condition "ward_apron" (combat/ext/protection.py): data {"feet": n, "bar": "keep_out" | "no_closer", "ward": zone id,
      "anchor": bearer id, "label"}. Placed on the creature that failed the save, expiring at the start of that creature's own
      next turn (combat/ext/effect_durations.token "START_OF_TURN_AT:<id>:<n>"), so an intervening turn of the Ward's creator
      cannot take it away early. It is what the printed words mean for the rest of the turn, and it is enforced at every
      voluntary step: protection.apron_excludes_the_protected_space, a ``candidate_allowed`` filter, rejects the whole Move
      candidate -- every square of its canonical path, detours included, not just its destination -- and the
      ``movement_attempt`` gate refuses the same step for movement that never passed through the menu (MOVE candidates only,
      default-inert for a creature holding no apron).
  typed condition "shield_suppressed" (Shielded's "suppressed until the start of the next turn in which that hand is free"):
      data {"label"}. Put on the bearer when a hand is actually occupied -- at the transaction that fills it, from
      protection.shield_occupancy_changed on the CONDITION_APPLIED/CONDITION_REMOVED events every hand change is
      (combat/ext/hand_occupancy.free_hands) -- and taken off only at a turn boundary by protection._shield_boundary,
      never inside an ``ac`` query. Inert without the Shielded Aegis. Absent (every creature without it) = the live
      "is a hand free" reading. A Shielded mark saved before this lane picks the suppression up at its first turn whose
      hands are occupied, which is the same reading such a saved fight already had.
  Hooks offered by combat/ext/brute_shove.py (the Brutal Shove contest):
    shove_succeeded(ctx, target, result)       -> None, after a successful Brutal Shove's push/Prone, extra movement, damage and
                                                 Manhandle rows (result: success, margin, mine, theirs, skill, and "direction",
                                                 the printed direction of this shove's own movement: "away" for Brutal Shove,
                                                 "toward" for a Get Over Here tether pull, so an extra movement a rider adds
                                                 moves the creature the same way the shove did). ctx.typed.source
                                                 names the shove (Brutal Shove, Dominoes' free shove). Break Defenses, Focused Might
                                                 (gu_brute.py), Court/Sovereign extra pushes (brute_riders.py) answer it.
    shove_damage(ctx, target)                  -> DiceSpec | None, replacing the Strength-modifier shove damage (Sovereign Weight).
    contest_mode(engine, creature, role, purpose, other) -> "ADVANTAGE" | "DISADVANTAGE" | None for one side ("act"/"resist") of a
                                                 Brute contest (purpose "shove"/"overrun"); combined with check_modes; conflicting
                                                 modes cancel. Rooted Stance answers "resist"/"shove".
  Shared helpers (public, documented in their modules): brute_shove.contest / shove / size_ok (Dominoes' free shoves use shove);
    brute_shove.strength_modifier -- one "your Strength modifier" for every Brute damage path (the shove's own Bludgeoning
      damage, Sovereign Weight Incarnation's 2d8 + Strength replacement, Alternative Maneuvers' Overrun damage). The score-based
      reading is opened by a packet flag, and each path names the one it was compiled against: the shove's own damage keeps the
      original "auto51_strength_score", while the Sovereign replacement and Overrun damage use brute_shove.DAMAGE_SCORE
      ("auto107_strength_score_damage"), stamped into their compiled rows. A fight saved before a flag existed simply does not
      carry it, so that saved fight keeps the modifier it was sealed with and its replay is byte-identical. One cohort is
      explicitly unsupported for exact damage replay because no flag can identify it -- a packet sealed in the AUTO107r1f1
      window (47fdd95e inclusive..60c3d3d0 exclusive) read the score then and the saving throw now. Existing compatibility
      inspection offers explicit saved-state continuation when replay diverges; see docs/plans/AUTO107_SAVED_DAMAGE_BOUNDARY.md;
    reach_bonus.natural_reach_ft(engine, actor) -> int: how far a creature reaches with its own body, in feet (5 unless a
      printed body form lengthens it). "Natural reach" is a printed requirement several talents share, so the question is about
      the creature, not one action: the same "Unarmed reach +N feet" rows the attack menus use (Calamity Briar Incarnation, Oni
      Form, Crown of Black Thorns), read with their state, turn and resource requirements. A weapon's reach and the resolving
      action's range are never natural reach;
    brute_shove.manhandle_options / apply_manhandle -- the "apply one Manhandle talent you know" of a printed ability that does
      not compile its own Brutal Shove variant: it asks which talent is meant and runs that talent's own compiled rows, so one
      Manhandle talent has one implementation;
    granted_moves.destinations / commit -- a move an ability grants outside the mover's own movement, no opportunity attacks
    (Interpose, Patrol Response); guardian_chassis.cultivation_level (compiled Guardian scaling, shared with Patrol);
    guardian_chassis.regain_focus / stored / maximum / room (Guardian's Focus, Held Harm);
    verdant_chassis.sow / claims / touching / place / spend / marks (Living Claims, counted Growth Marks).
    attack_notifications.is_melee_hit(ctx) -> bool, for confirmed after_hit callers only: native/portable notice delivery
      or typed profile range metadata distinguishes melee (including reach) from adjacent ranged attacks. No distance guessing.
    temp_hp_grants.grant_at_hit(ctx, target) -> (source ID, integer grant sequence, remaining integer HP at hit) | None.
      Bark-Back and other hit-triggered guards may query recorded TEMP_HP_GRANTED/DAMAGE_COMMITTED receipts against the
      exact settled roll_id. Only increased grants replace identity; equal/lower offers are rejected by the engine. Prior
      depletion or a later accepted replacement returns None; this attack consuming the last HP still qualifies. Pure,
      no new saved state or events; missing proof returns None. Native and portable notices carry the actual roll ID;
      typed Context.attack_result carries it already. Bark-Back retains its used grant sequence and round as integer
      turn flags (sequence integer, round string), preventing another retaliation from the same grant even in another round. Legacy spent flags remain
      spent until an actual new Bark-Back grant. Verdant Incarnation and Bark-Back use settled after_hit, never provisional hits.
  Effect types: brutal_shove (typed row: success_branch true, on_success, mode push_or_prone|prone_only|aside, no_damage,
    no_manhandle, ignore_size, max_size_larger, disadvantage); brute_overrun; guardian_patrol; guardian_release_delay;
    living_claim; verdant_response (response root|bind|shelter|thorn); verdant_bind; verdant_snared; verdant_flag.
  Compiler seam (factory_compiler._attach): a typed row marked "success_branch": true is where a "hit" or "success" modifier's
    effects go (its on_success), as for a Scoundrel check -- a contest standing in for an attack. No marker = unchanged attachment.
  Feature blocks: "guardian" kinds guardian_core / patrol_practice / bodyguard / deep_reservoir / durable / cold_iron_call /
    punishment_returned / guardians_focus / complex_patrol / zone_<talent>; "brute_shove" kinds greater_brute / brutal_manhandle /
    alternative_maneuvers / mighty_hurl; "verdant" kinds core and one per talent (combat/rules/feature_blocks.d/riders_c16.json).
    AUTO60: newly sealed guardians_focus rows may carry maneuver_focus=true. guardian_chassis uses resolution_final
    for ordinary unarmed Grapple/Shove actions with actual applied Grappled/Prone or committed forced movement,
    while Patrol is active. The existing regain_focus helper enforces absent Focus/once per round. Immunity,
    blocked movement, unowned rows and legacy rows lacking the marker are inert. Other granted attempts still
    need their completed-outcome binding; no save query invents success.
  Choice ids (needle.ask, asked of the deciding creature): interpose, held_harm, guardian_delay, punishment_returned, patrol_zone,
    patrol_response, brute_contest_skill, brutal_shove_result, brutal_manhandle, shove_aside, overrun_manhandle, wither_claim,
    verdant_shelter, verdant_payment, feed_the_root, branching_answer, root_snare_step, forest_remembers, hungry_root,
    bramble_refusal, thorn_crown.
  Feed the Root extends the existing mark_apply / after_hit / event paths: place(engine, owner, subject, number, source,
    intent=None) -> added mark count; an owning Feed row and a touched owned claim gate its once-per-turn choice of any
    owned claim within 60 feet. needle.ask routes the choice to the owner, including during another actor's AI action;
    no intent/provider retains the existing deterministic fallback. AI prefers a touched claim, then oldest with room.
    verdant_response uses the pure legal-payment query for both candidate visibility and payment. Player owners choose
    marks, feed through one touched owned claim, or a mixture when more than one payment is legal. AI preserves free/marks-first
    preference. Selection happens before resource mutation; pauses roll back via the existing table transaction.
    Each new claim component feed_schedule is a JSON string mapping integer owner-turn deadlines to integer counts.
    feed / feed_until remain integer aggregates. Legacy claims lacking the schedule use their existing feed / feed_until;
    no schema migration, stored object or runtime patch. The existing turn_end(engine, actor) hook records OBJECT_UPDATED
    to expire only due feed for owning Feed rows; new grants never renew older feed, spending uses earliest deadlines first.
    Unowned rows, untouching targets and claims outside range trigger no choice or change; unrelated saved fights are inert.
  Forest Remembers extends event(engine, "MOVEMENT_COMMITTED", kwargs) -> None: kwargs.actor_id identifies the mover,
    kwargs.payload.path contains the actual committed anchors (including departure); teleport=True limits evidence to
    departure/arrival. No interpolation, planned remainder, altitude or unsupported movement is invented. Owning Forest
    rows plus the mover's marks gate the hook, including marks on the owner. At least one committed footprint space must
    be within 60 feet; the printed choice then permits a supportable space actually left or entered. Footprint differences
    exclude spaces continuously occupied. Supportable represented squares are in bounds and not blocked; claims do not
    block creatures, so occupied squares remain legal. Absent/no-change paths are inert. needle.ask routes cell choices to
    the owning player, including during an AI mover's turn. AI keeps its arrival-first preference and uses the ability with
    at least two marks, otherwise declines. Selection precedes spending; sow's existing claim-limit chooser is preserved.
    Mark removal and claim creation remain recorded events; no new stored field, schema or locked movement seam is added.
  Rooted Lineage Scripture uses effect_expiring(engine, holder, condition) to replace a due Growth Mark once with an
    END_OF_TURN_AT deadline one round later, only for owning compiled verdant/rooted_lineage rows in contact. The existing
    event hook ends the additional round on contact loss after movement or a claim update; spending preserves the deadline.
  A condition's own recorded data may carry the printed choice a later line of the same ability reads, so no second stored
    field is needed: Hunger stores the kind of Satiety a Digestive Mantle burned (``satiety``), where the creature that meal
    came from (``provenance``, a fact about the creature and not another kind, so a predator's demon-beast portion is both),
    its chosen benefits (``benefits``) and the one damage type Elemental Gut was chosen for (``element``) on the Mantle's own
    condition, with
    ``effect_expiring`` answering the printed "when that Mantle ends" and ``technique_start`` answering it for the printed
    "Activating a new Digestive Mantle ends the previous one" (combat/ext/hunger_riders.py). Only strings, integers and
    lists; nothing new is persisted, and a fight saved before a plug-in existed simply carries no such key and stays inert.
  A talent that spends a resource for an ability it hands over declares it in its own feature-block row rather than in
    code: Hunger reads ``satiety_per_benefit`` from the row (Maw of Ten Thousand Courses, "Choose one Mantle benefit for
    each Satiety spent"), ``reads`` for the meal kinds its printed line names and ``reads_provenance`` for where the creature
    came from, and each answer is stored in its own field so neither stands in for the other. A fight sealed before the
    creature question existed carries a row that declares ``reads: ["predator"]`` and a Mantle recording
    ``satiety: "predator"``; the same plug-in keeps reading that meal for such a row -- it stays on its owner's meal menu so
    a later activation can record it again, and it still opens the printed die -- and reads nothing from it for a row
    compiled today, so an old save is neither recompiled nor rewritten to reach the current reading. ``satiety_per_benefit`` prices
    only the benefits past the free entitlement (the Satiety the Mantle costs pays for the first, a printed "choose two" for
    the next), and the note that a talent ran out of Satiety to spend is written with that row's own ``name``, never its
    ability id. One row, one rule, no ability id in a
    plug-in body; the row lives in the feature_blocks.d file that already declared that mechanic, because
    combat/typed_reactions.py rules() merges those files in sorted filename order and a second declaration is discarded.
  Shelter uses ac(engine, target) for its existing cover condition and event(engine, "ATTACK_ROLLED", kwargs), nested=True,
  to consume it on the actual rolled target after target_ac is captured, hit or miss. Shelter-Grove stores the integer
  ``grove_dex_save`` flag on that same condition; save(ctx, subject, ability, named) grants +2 to one Dexterity save and
  consumes it. Without the condition both hooks are inert; Shelter's ordinary one-attack cover remains unchanged.
Typed area key added by the Smoke sphere automation lane AUTO43 (absent = unchanged behaviour):
  An area printed as a number of cubes rather than one ("At CL 5, the area becomes two connected 10-foot cubes") carries
  ``blocks`` (a positive integer, how many cube-shaped blocks of ``size_ft`` the area is) in its compiled zone spec, or the
  printed ``blocks_by_cl`` table (``[low_cl, high_cl, count]`` rows) that resolves into it at this Cultivation Level
  (combat/factory_compiler.py ``_area_blocks_for_cl``, read the way ``size_ft_by_cl`` is). The geometry is general and
  shared: combat/zones.py ``block_cells`` lays the blocks in one straight run whose blocks share a face, across the line
  from the area's user through its aim point; ``blocks`` 1 or absent is the plain cube, so no other area changes. That
  direction (combat/zones.py ``run_axis``) is written beside the count as ``blocks_along`` in the area's own
  ``trigger_profile``, so a moved or re-centred run keeps the shape it was made with. The
  resolved count is written into the area's own ``trigger_profile`` as an integer, so a table commit and reload and a later
  re-centring (combat/ext/zone_mover.py, combat/ext/tabik_dark.py ``_recenter``) keep the same squares. Used by
  combat/ext/smoke_veil.py for the Smoke sphere; any area with that printed wording may set it.
Cell placement contract (lock round 16): CELL actions opt in with
parameters.cell_placement={} (optional width_cells/height_cells integer 1..8).
The generic path accepts non-hostile squares, validating anchor sight/range and
unoccupied full 3D footprint. parameters.summon_group uses the single registered
creature's actual footprint instead of explicit dimensions. Preview and execution
share cell_placement.legal: preview=True uses directly known occupants only;
execution uses every actual occupant. Remembered/unknown hidden bodies never
remove menu squares. An accepted placement invalidated by hidden occupancy or
a reaction fails with a generic readable message, without refunding already
spent costs or revealing the blocker. PASSIVE_TRIGGERED records that failure or
the chosen integer position; SUMMON_APPEARED
records the actual summoned position. Context.destination/intent.destination are
available to owning object/terrain effects. The controller favors legal placement
near visible hostiles through generic metadata; no action IDs are inspected.
No cell_placement key means unchanged targeting, AI scores, events and old SELF
1-cell summon placement. Large SELF summons now check their whole body when
choosing an automatic anchor, with the same distance/toward/y/x tie-breaks.
Explicit summon size is retained in new bundles; old bundles
without size retain their existing footprint. No retained bundle is recompiled.
Read-only AI estimates (lock round 16): movement candidates set hazard_exposure
for static hazards or recipient-aware active damaging zones. Optional
zone_hazard_exposure tests every traversed position through zones.hazard_test;
no applicable zones means the exact previous metadata. This is an estimate,
not a new damage trigger or veto. Existing zone recipient/Clearsight rules apply.
gate4_context adds optional useful_recovery rows (target_id, healing_hp,
temporary_hp, all integer amounts) for immediate typed support effects through
support_estimates.recovery. The controller adds useful recovery to immediate
utility and omits offensive target/finish bonuses on friendly support targets.
No effect execution, RNG, spending, candidate identity, manual choices or saved
state changes occur. Old contexts without either metadata field score as before.
Deferred/conditional benefits are not predicted; mixed effects remain legal.
Lock 21 ally policy: LocalControllerPolicy.support_wounded_allies defaults False
and is omitted when False. Dao-derived policies opt in. The controller adds the
useful_recovery HP amounts for visible, active, wounded allies other than self
to ally_support, multiplied by the active posture's ally_support weight. It
uses actual recovery recipients, including areas, not merely candidate targets.
Full-health allies, self, enemies and actions without useful recovery gain no
new credit. It does not infer help from a friendly target or predict delayed
buffs. No extra damage/finish credit, effect execution, state or event mutation;
old contexts and non-opted-in policies retain their scores and serialized shape.

Lock 21 movement continuity: movement_history.endpoints(engine, actor_id) reads
committed MOVEMENT_COMMITTED start/destination positions since the last turn
boundary, non-move intent, reaction, HP/condition change or other creature/forced
movement. Gate4 contexts expose these as optional movement_endpoints (integer
Position tuples, including altitude), omitted when empty. The controller excludes
ordinary-turn MOVE destinations already used in that uninterrupted segment before ranking
movement representatives. Routes may cross old ground to reach a new destination;
non-move choices, movement-only domains and manual legal moves are unchanged. A meaningful intervening
event resets the segment, so an attack can be followed by a retreat.
DAMAGE_COMMITTED during a move precedes its final MOVEMENT_COMMITTED receipt:
that receipt contributes its destination, but its pre-damage start is discarded.
Starts enter history only after scanning back to the accepted MOVE without a
reset (or the beginning of a retained journal). No hidden
enemy path is exposed: only this actor's own committed endpoints enter context.
No saved-state field, new event, RNG or mutation; fresh reload derives the same
history from the journal. Old contexts lacking the field remain valid and inert.

Lock 21 rider utility: typed ActionDefinition.parameters.rider_utility is an
optional signed integer (bools/non-integers ignored). Gate2Engine._candidate
copies a nonzero value to candidate.metadata independently of expected_damage,
including precomputed area damage. The controller emits a separate rider_utility
component, weighted by policy.weights.rider_utility or, if absent, immediate_effect.
It never changes the damage estimate or the finishing threshold. Remembered,
currently unseen targets gain no rider credit. Absent/zero metadata adds no
component and leaves legacy candidate/decision bytes unchanged. The value is
per candidate, not multiplied by area size; publishers price the complete rider.
Candidate identity, payment, execution, state and events are unchanged. Ability
compilers/plug-ins own the metadata; the engine has no ability-ID exceptions.
stored_healing_reductions(..., consume=False) queries existing healing penalties
without spending one-use modifiers or emitting events; execution defaults True.
effect_eligibility.eligible(ctx, row, include_deferred=False) is shared by typed
execution and estimates: level bounds, selected menu options, deferred rows and
once-per-activation gates. Only execution consumes a gate; repeated effects of
the same activation share its local damage_cache.
The shared eligibility query preserves explicit per-turn and owner-turn-only
modifier gates; execution records the same key queried by recovery estimates.
typed_amounts shares formula, scaled dice and additive terms; temp_hp_terms.fold_temp_hp groups distinct terms
of one eligible grant, keeping independent flat grants separate. Ineligible
terms cannot leak into a combined grant. Temporary HP denial contributes zero.
Movement hazard cells and support action preparation cache only within ONE
query. No state, events, rolls, choices or engine-persistent cache is changed.
Native movement reaction previews likewise share observed reactors and reach
membership only within one actor's menu query. A later query rebuilds them from
current positions, reaction availability, allegiance and Disengage. The optional
_movement_reaction_exposure cache must never be retained across queries/actors.
Damaging enter/start zone membership is unioned after recipient/standing tests;
line crossing and movement-threshold terrain rules keep their separate checks.
Thread Sphere reactions (automation lane AUTO19, 2026-10-04): two printed moments the generic reaction
reader cannot see are answered from their own hooks, both inert without the talent's feature-block row
(feature row owned by the plug-in, so nothing else compiles for a character without it).
  * d20_bonus(engine, roll, intent) -> {source_id, bonus: int, user_id?} answers a printed bonus whose sign
    depends on the rolling creature, or that only applies to a roll that has already come out wrong.
    combat/ext/thread_correction.py uses it for Puppet-Line Correction ("If the creature is willing, it adds your
    Proficiency Bonus to the roll. If the creature is unwilling, it makes a Wisdom saving throw...") and Borrow
    the Ally's Arm ("... misses with a melee attack or fails a Strength or Dexterity ability check"), both of
    which the before-the-roll generic creature_d20 row could only sign one way. The reply is the roll's own
    modifier plus the existing D20_REWRITTEN receipt; a save the reply itself rolls uses _roll_save and is not
    answered a second time. The printed price and the Reaction are spent for the ATTEMPT: "On a success, the
    roll is unaffected" is about the roll, and there is no printed refund. "Willing" is the rolling creature's
    own answer, asked of it through willing_targets.asks_consent (the shared consent transport), so a player
    controlling it decides on its own turn and on somebody else's; the module says so. What refusing costs is
    each talent's own text: Puppet-Line Correction quotes its printed Wisdom saving throw, while Borrow the
    Ally's Arm prints none, so refusing that one leaves the roll alone and spends neither CP nor the Reaction.
    Each talent asks the creature separately, so refusing the cheaper printed offer is not taken as an answer to
    the other one: the willingness answer is remembered per line, creature and talent, for that roll only.
  * movement_attempt(engine, mover, previous, nxt, intent) resolves a printed reaction at the step that
    triggers it rather than after the move. combat/ext/thread_lines.py uses it for Snaring Crossing ("A
    creature you can see moves across a space containing one of your Thread Lines"): the step is judged
    against the cells a Thread Line runs through (thread_common.thread_line_cells, from Draw the Line's own
    "between yourself or an anchor you control and the target") before the step is charged, so a failed save
    (Speed becomes 0) stops the creature on the near edge of the line instead of after it walked its whole
    path. A line is compared in three dimensions through the exact 3D traversal grid.effect_ray_cells, so a
    creature that passes above or below a thread has not stepped on one. Two Thread users' lines can cover the
    same step, so every eligible owner is offered their own Reaction for it while the step can still be charged
    (the hook stops asking once a preceding answer has taken the creature's Speed, moved it, floored it or ended
    the fight). The speed it sets expires on END_OF_CURRENT_TURN, and the printed once-per-creature-per-round
    limit is a turn flag whose key starts with "once_per_round:" so a Thread user's own turn start cannot erase
    it. The printed alternative "moves out of a space adjacent to an anchor you control" needs an anchor the
    table does not track, and stays a GM reminder on the reviewed record.
  * combat/ext/thread_common.py's public thread_range_ft(engine, actor), thread_line_held_by(engine, holder,
    user), mark_held_by(holder, owner_id, mark), cell_of(position) and thread_line_cells(engine, user) are the
    one Thread range, Thread Line and Thread Line geometry query, shared by every Thread talent that hangs on
    the line (thread_correction and thread_lines import them; they reach no other plug-in's private state).
No engine class or function is patched, no saved-fight field is added, and the reply to a d20 is an existing
roll modification rather than a stored bonus.

Lock round 26 movement and Concentration seams (gate2_engine.py, 2026-10-08):
  engine.movement_scope(actor_id) -> {actor_id, source_id, mode, granted} or None.
  A pure query, true only while _resolve_movement walks that actor's steps:
  movement_attempt/step checkpoints, leave-reach opportunity attacks and the
  reactions they open. None before path validation and after
  MOVEMENT_COMMITTED; transient, never saved, unwinds on pauses/errors.
  Use it from an existing ac(engine, actor) hook for "during movement" rules.
  Shield Skate (auto/shield shield_mobility): return
  -armour.shield_bonus_earning(engine, actor) when skating(engine, actor) and
  engine.movement_scope(actor.entity_id) is not None; otherwise None.
  Painted map terrain now reaches _hostile_difficult_cells (and so movement
  cost) through zones.difficult_cells even with no typed zone active; the
  existing difficult_exempt / difficult_zone_exempt hooks still excuse it.
  concentration_save_failed(engine, actor, roll, dc, context) -> "MAINTAIN" or
  None. Strict; called only after a failed Concentration save while actor
  has current Concentration. context = {source_actor_id, damage_source_id,
  started_sequence, source_definition_id}. Exactly one "MAINTAIN" keeps the
  concentration and skips FAILED_DAMAGE_CHECK; the owner must log the rescue
  and schedule the later end itself (an expiring condition whose
  effect_expiring hook calls concentration.end_copy(engine, actor,
  started_sequence, reason)). The failed roll stays recorded. No subscriber
  keeps the historical ending. Shield Soul Never Falls (auto/shield
  shield_incarnation): when the concentration is on a Shield talent, offer
  "maintain" in use(); answer "MAINTAIN" only when chosen.

Lock round 26 native repeat-save resolution (gate2_engine.py _resolve_repeat_save):
  Each native condition repeat_save builds one transient resolution dict
  {holder_id, instance_id, condition_id, source_definition_id,
  source_actor_id (the original caster), ability, dc, named, checkpoint,
  roll, success, settled_by}; never saved.
  repeat_save_scope(engine, resolution) -> context manager or None. Strict;
  entered before the roll and exited after the native exact-instance
  removal, so deferred results (a granted move) run after it; it unwinds on
  player pauses and errors. Absent subscribers add nothing.
  repeat_save_failed(engine, resolution) -> None or {"result": "SUCCESS",
  "settled_by": source id}. Strict; asked once after a failed roll while
  the holder is active and the instance remains. One answer settles the
  save as a success: the failed die stays recorded and CONDITION_REMOVED
  adds settled_by. Any other answer raises; no answer keeps the failure.
  Lucid Escape (auto/dreams dreams_lucid): register repeat_save_failed; find
  the holder's new save_escape row, require _printed_save(resolution
  ["named"]) and can_use_reaction(engine, holder, caster, row) with caster =
  engine.state.actors[resolution["source_actor_id"]]; ask with
  engine._active_intent, then pay inside _reaction_activation as the
  after_save path does. "succeed" and "end_effect" (this instance) answer
  SUCCESS with settled_by LUCID; for "move" also answer SUCCESS only if
  printed, and store the distance on a repeat_save_scope-owned scope keyed
  by holder_id so move_after runs at scope exit, after removal.
"""

from __future__ import annotations

# SOL168 uses existing contracts only: charge_marks' compile_action adds the
# lightning_gather_second effect to owned Gather Charge options. It asks for
# one extra legal placement without another economy payment; creature, weapon
# and space Charges share the printed cap.
# mark_apply also preserves oldest-Charge replacement when a later Lightning
# effect encounters a cap occupied by weapon/space Charges; creature-only
# placement remains on the existing path. Map water may declare
# significant_water_source=true for River Passage's CL15 mile route.
# water_passage's compile_action,
# candidate_allowed and water_river_passage effect restrict the owned River
# Passage variant to recorded connected water and owner's Basin landings.
# Passenger variants target any creature and ask a non-self passenger's consent
# through the existing choice transport (manual owners may decline, AI decides).
# The CL15 route uses water-component membership in a significant source;
# Gather Charge's second picker applies and rechecks all candidate_allowed vetoes.
# rider_outcomes' unresolved_roll_mode_text uses printed evidence for incomplete generated
# roll-mode rows (no `on` descriptor), preserving their GM-only semantics.
# All three providers return early outside their opted-in rows.
# unresolved_roll_mode_text(ctx, effect, mode) -> plain str or None replaces only
# an unresolved Advantage/Disadvantage GM summary. It changes no roll, payment,
# expiry or once-per-turn bookkeeping. None/no provider retains the old summary;
# the provider is used by every incomplete generated roll-mode row, not one ability.

# AI placement query seam (combat/candidate_knowledge.py): query(engine) scopes
# observed actor estimates and perceived/last-observed area aims while Gate 2/4
# generate candidates. roster(engine) returns that tuple or None (real roster);
# aim_allowed(engine, actor, Position) returns a boolean, True outside the scope.
# No engine/state/class mutation or execution hook is involved. Area safety uses
# the executor's explicit actors= geometry query; execution never enters this
# scope. Teleport plug-ins retain candidate_allowed for owning restrictions and
# the shared teleport_steps.destinations/destination_allowed legality contract.
# zones.hazard_test(engine, actor, movement_mode="walking") returns an endpoint
# damage predicate or None. "teleport" and "forced" retain entry/start and line
# crossing estimates while excluding distance-based terrain triggers, matching
# forced execution. Default walking queries and fights without hazards are unchanged.
# prepared_binding(engine, generated_candidates) scopes immutable AI acceptance:
# binding_candidates(engine) returns that menu only for an identical full-state
# hash, otherwise None. It never changes engine functions or execution rosters.

# Search policy: ai_search_policy's existing match_start(engine)->None hook
# stamps integer ai_search_policy=1 in MATCH_CREATED. combat.ai_search derives
# a legal walking candidate from public terrain, projected knowledge and the
# mover's own journal. gate4_context supplies its optional id only for ordinary
# AI decisions; controller representatives retain it and record its integer
# search score. Missing stamps/fields are inert. Continuations preserve stamps.
# The documented target_observation_refresh hook renews perceived same-square
# sightings for stamped fights without new event numbers or fight-state fields.
# Neutral policy phases: combat.relations.ordinary_turn(candidates) is the
# shared pure guard for context filtering and controller scoring. Setup and
# accepted OPTIONAL_RIDER / TAKE_NO_OPTIONAL_ACTION windows retain their
# candidate sets; retreat/Dodge and neutral-target policy starts only on ordinary
# turns. No new saved field, event or hook; ordinary two-team behavior is unchanged.

# Spirit Companions sealing family (AUTO5 2026-10-04, corrected by AUTO5f1). All default-inert: nothing answers for a
# creature without the owning compiled rows, and a fight saved before the lane keeps its old paths.
#   Effect types: seal_strain (the owner's own Bond Strain counter, never the spirit's; combat/ext/spirit_seals.py),
#     seal_release (break a Binding Seal: every mark and matching condition the creature wears go together, older
#     mark-only saves included), seal_suppress (a spirit cannot be commanded, is not tethered and may attack its
#     binder for a printed window). Registered by combat/ext/spirit_seals.py. A spirit_guard row's own
#     "nature_bonus" key ({"temp_hp": "pb", "natures": [...], "evidence": ...}) is the printed rider that asks the
#     player for a spirit's Nature (Guardian Spirit Posture, combat/ext/spirit_bonds.py).
#   Feature blocks (combat/rules/feature_blocks.d/auto5_spirit.json): {"block": "spirit_seal", "kind": "violent" |
#     "painful" | "punish" | "name"} per seal talent. A "punish" row carries trigger_owner, so the compiler omits the
#     generic reaction row it could never deliver (the printed trigger is a summon disobeying, which no event reports)
#     and the plug-in's own prompt is the whole delivery. Absent a block a character owns none of them.
#   Typed record key target: {"any_side": true} widens ONE owned action to any creature through the existing
#     compile_action seam (spirit_seals.widen_any_side): the compiler reads a harmful saving throw or contest as
#     hostile-only, and "a Binding Seal restrains or compels a spirit" prints no side. The flag lives in the talent's
#     own typed record, so any ability can use it; range, costs and effects are untouched. A printed outcome that
#     depends on a check nests under that check's on_success, so a failed check changes nothing.
#   Shared core addition, typed_executor.resolve_opposed_check target_check {"kind": "dc", "of": "<name>"}: the
#     actor's check must meet a printed Difficulty Class and the defender rolls no die ("Make a Cultivation Check
#     against the binder's Cultivation Save DC"). The DC comes from the new dc_of() seam, which asks the check_dc
#     hook (ctx, target, spec) and otherwise reads the target's own Cultivation Save DC
#     (combat/ext/end_effect.cultivation_dc); an unnamed, unanswerable or legacy name all fall back to that same
#     target DC, never to a flat 10. A DC is met by matching it (outcome_override total >= dc), where an opposed
#     contest's tie still preserves the defended situation. OpposedCheckResult.target carries the DC as a no-die
#     RollRecord ("DC n"), so margin/tied/events keep their ordinary shape. CHECK_ROLLED retains the actor's
#     label/skill (or "Cultivation Check" for that kind); DC history names the affected creature and printed DC.
#     Any other kind is unchanged.

import importlib
import pkgutil
from collections import defaultdict
from typing import Any, Callable

_EFFECTS: dict[str, Callable[..., Any]] = {}
_EFFECT_HARM: dict[str, bool | None] = {}
_HOOKS: dict[str, list[Callable[..., Any]]] = defaultdict(list)
_HOOK_PRIORITIES: dict[tuple[str, Callable[..., Any]], int] = {}
_NESTED_HOOKS: dict[str, set[Callable[..., Any]]] = defaultdict(set)
_LOADED = False


class ControllerPause(BaseException):
    """Raised by a choice provider to stop a preview until the player has answered (an Ask-me reaction, see
    combat/gate5_service.py _ReactionRequired). It is control flow, not a bug: code that catches Exception to keep a
    broken row or hook from ending a fight must re-raise it, or the player is never asked (owner playtest 2026-09-29:
    Flowing Response was auto-declined by the policy controller because its pause was swallowed as "could not run"). A
    BaseException, so every ``except Exception`` guard lets it through; only throwaway probe engines raise it."""


def effect(name: str, *, harmful: bool | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if harmful is not None and type(harmful) is not bool:
        raise ValueError("effect harmful must be bool or None")
    def register(function: Callable[..., Any]) -> Callable[..., Any]:
        _EFFECTS[name] = function
        _EFFECT_HARM[name] = harmful
        return function
    return register


def hook(point: str, *, nested: bool = False, priority: int = 0) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a hook; lower priorities run first, ties retain registration order.

    Default 0 preserves existing ordering. Use negative priorities for transient
    scope bookkeeping that must precede ordinary observers (granted movement).
    """
    if type(priority) is not int:
        raise ValueError("hook priority must be an integer")
    if nested and point != "event":
        raise ValueError("nested subscriptions are supported only for event hooks")
    def register(function: Callable[..., Any]) -> Callable[..., Any]:
        _HOOK_PRIORITIES[(point, function)] = priority
        _HOOKS[point].append(function)
        _HOOKS[point].sort(key=lambda subscriber: _HOOK_PRIORITIES.get((point, subscriber), 0))
        if nested:
            _NESTED_HOOKS[point].add(function)
        return function
    return register


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda row: row.name):
        importlib.import_module(f"{__name__}.{module.name}")


def effects() -> dict[str, Callable[..., Any]]:
    _load()
    return _EFFECTS


def effect_harm(name: str) -> bool | None:
    """Pure registration metadata used by combat.effect_harm's shared contract."""
    _load()
    return _EFFECT_HARM.get(name)


def transform(point: str, value: Any, *args: Any, **kwargs: Any) -> Any:
    """Compose pure replacements sequentially; None retains the current value."""
    _load()
    for function in _HOOKS.get(point, []):
        replacement = function(value, *args, **kwargs)
        if replacement is not None:
            value = replacement
    return value

def iter_strict(point: str, *args: Any, **kwargs: Any):
    """Transactional lazy dispatch: callers may stop before another provider spends."""
    _load()
    for function in _HOOKS.get(point, []):
        result = function(*args, **kwargs)
        if result is not None:
            yield result

def iter_strict_all(point: str, *args: Any, **kwargs: Any):
    """Ordered lazy transactional dispatch, including None replies.

    The caller can validate state and stop between subscribers, before the next
    one runs. Exceptions propagate for normal transaction rollback. Snapshot the
    registered order so nested registration cannot change this dispatch.
    """
    _load()
    for function in tuple(_HOOKS.get(point, ())):
        yield function(*args, **kwargs)

def subscribers(point: str) -> tuple[Callable[..., Any], ...]:
    """Snapshot strict providers for lifecycle points with per-provider rechecks."""
    _load()
    return tuple(_HOOKS.get(point, ()))
class CheckpointError(ValueError):
    """A paid checkpoint failed; observational guards must let it roll back."""


def run_checkpoint(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Strict paid-effect hooks retain rollback through nested observational hooks."""
    try:
        return run_strict(point, *args, **kwargs)
    except CheckpointError:
        raise
    except Exception as exc:
        raise CheckpointError(f'{point}: {exc}') from exc


def run_strict(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Transactional hooks: errors (including a choice-provider pause) must unwind.

    Unlike observational hooks, swallowing an error could commit half an effect.
    Only call inside an engine transaction or its preview clone.
    """
    _load()
    return [result for function in _HOOKS.get(point, [])
            if (result := function(*args, **kwargs)) is not None]


def effect_permitted(ctx: Any, effect: dict[str, Any], subjects: Any, *, exclude=None) -> bool:
    """Strict permission query for effects folded into another effect's delivery.

    Calls effect_allowed(ctx, effect) and effect_subject_allowed(ctx, effect, subject)
    for every supplied recipient. False vetoes delivery; no subscribers permits it.
    ``exclude`` is the caller's suppression callback, omitted to avoid recursively
    suppressing the very effect being queried. Other providers and errors retain
    their normal contract. This query does not consume use clocks.
    """
    replies = [function(ctx, effect) for function in subscribers("effect_allowed")
               if function is not exclude]
    return not any(reply is False for reply in replies) and all(
        not any(reply is False for reply in run_strict("effect_subject_allowed", ctx, effect, subject))
        for subject in subjects)


def reduce_amount(point: str, engine: Any, subject: Any, amount: int) -> int:
    """Fold a transactional amount-reduction hook over the surviving integer amount.

    Shared by the healing restriction and assignment stages in typed_executor.
    A hook cannot increase the amount; zero prevents later hooks spending a denied
    offer. Errors and player-choice pauses unwind the owning transaction.
    """
    _load()
    amount = max(0, int(amount))
    for function in _HOOKS.get(point, []):
        if amount == 0:
            break
        result = function(engine, subject, amount)
        if result is not None:
            amount = min(amount, max(0, int(result)))
    return amount


def query(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Read-only presentation hooks: skip failures without writing fight events.

    Handlers must be pure. Used by status_description for condition, mark and
    terrain descriptions; transactional/gameplay hooks still use their own paths.
    """
    import logging

    _load()
    out = []
    for function in _HOOKS.get(point, []):
        try:
            result = function(*args, **kwargs)
            if result is not None:
                out.append(result)
        except Exception:
            logging.getLogger(__name__).exception("Presentation hook %s failed: %s", point, function.__name__)
    return out


def remember_recorded_event(engine: Any, event: Any) -> None:
    """Shared identity seam for prepared_actions.on_event and extension event dispatch.

    Gate 2 supplies the actual recorded Event to prepared_actions before Gate 4
    dispatches it. Remember it before Ready delivery and again in that delivery's
    finally block: children dispatch their own identity, then the parent resumes
    with its original identity even when Ready appended events or paused.
    Holds one transient reference on the engine; never serialized, never changes
    event bytes or delivery order, and performs no ability behavior.
    """
    engine._ext_recorded_event = event


def callbacks(point: str) -> tuple[Callable[..., Any], ...]:
    """Stable subscriber order for native checkpoints that recheck between replies.

    Callers invoke within a transaction and propagate errors/ControllerPause,
    just like run_strict. Taking the snapshot does not invoke any subscriber.
    """
    _load()
    return tuple(_HOOKS.get(point, ()))


def invoke(point: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """One registered observational callback; shared by run and hit defenses."""
    try:
        return function(*args, **kwargs)
    except (ControllerPause, CheckpointError):
        raise
    except Exception as exc:  # noqa: BLE001 -- preserve observational hook policy
        from ..gate5_service import _ReactionRequired
        if isinstance(exc, _ReactionRequired):
            raise
        _log(point, function, exc, args)
        return None


def run(point: str, *args: Any, _nested_only: bool = False, _transform_last: bool = False,
        _with_handlers: bool = False, **kwargs: Any) -> list[Any]:
    """Every registered hook's result for this point (None results dropped). A hook that raises is skipped."""
    if point == "event":
        from .retained_updates import is_retained_update
        from .setting_choices import setting_intent_event

        if is_retained_update(args[1], args[2].get("payload") or {}):
            return []
        if setting_intent_event(args[0], args[1]):
            return []
        # Ready may already have appended events before Gate 4 reaches us.
        # Snapshot the preserved recorded identity, never the mutable log tail.
        engine, event_type, event_kwargs = args
        event = getattr(engine, "_ext_recorded_event", None)
        args = (engine, event_type, {**event_kwargs, "originating_event": event})
    _load()
    out = []
    for function in _HOOKS.get(point, []):
        if _nested_only and function not in _NESTED_HOOKS.get(point, ()):
            continue
        result = invoke(point, function, *args, **kwargs)
        if result is not None:
            out.append((function, result) if _with_handlers else result)
            if point == "compile_action":
                args = (result, *args[1:])
            if _transform_last:
                args = (*args[:-1], result)
    return out


def transform_last(point: str, *args: Any) -> Any:
    """Sequential pure transforms of the last argument in registration order.

    Subscribers return a replacement or None to retain the current value.
    Use only for documented transformation contracts (currently wall_defenses).
    Failures use run's ordinary skip/log policy and retain the previous value.
    """
    results = run(point, *args, _transform_last=True)
    return results[-1] if results else args[-1]


def has(point: str) -> bool:
    """Whether any module registered this hook point (lets a hot path skip the call)."""
    _load()
    return bool(_HOOKS.get(point))


def any_false(point: str, *args: Any, **kwargs: Any) -> bool:
    if (point in ("event", "compile_action") or run is not _RUN
            or kwargs.keys() & {"_nested_only", "_transform_last", "_with_handlers"}):
        return any(result is False for result in run(point, *args, **kwargs))
    # Hot path (candidate_allowed runs every subscriber for every legal candidate): the same subscribers and order as
    # run(), with invoke()'s single error policy, but no result list per subscriber. Every subscriber still runs; there
    # is no short-circuit. run()'s dispatch-control keywords and special points always go through run() itself.
    _load()
    vetoed = False
    for function in _HOOKS.get(point, []):
        result = invoke(point, function, *args, **kwargs)  # the one shared error policy
        if result is False:
            vetoed = True
    return vetoed


_RUN = run


def vetoing_hooks(point: str, *args: Any) -> tuple[str, ...]:
    """Pure diagnostic query used by system_bookkeeping and Gate 5 recovery.

    Return sorted qualified handler names whose ordinary hook result is False;
    use the same exception/skip semantics as run. Never append a fight event.
    """
    return tuple(sorted({f'{function.__module__}.{function.__name__}'
                         for function, result in run(point, *args, _with_handlers=True)
                         if result is False}))


_LISTING = {"legal_candidates", "_action_candidates", "_candidates", "_move_candidates", "_pending_candidates",
            "vetoing_hooks"}


def _while_listing() -> bool:
    """Whether the engine is listing legal choices right now: a fight event written then changes every candidate id, so
    every button the table shows is refused as stale (round14 reconcile, 2026-09-30: one failing hook, 436 events)."""
    import sys

    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_name in _LISTING:
            return True
        frame = frame.f_back
    return False


def run_nested(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Ordered observational dispatch to explicitly opted-in nested subscribers."""
    return run(point, *args, _nested_only=True, **kwargs)


def floored(engine: Any, actor: Any, roll: Any, dc: int | None = None, *, ability: str | None = None,
            skill: str | None = None) -> Any:
    """``roll`` (a d20 check the actor just rolled) with its total raised to a d20 floor a plug-in sets, or ``roll``
    itself. The natural die stays as rolled (a natural 1 is still shown as a 1); only the total changes. ``dc`` is what
    the check must reach when the caller knows it (a plug-in may spend something only when the floor turns a failure into
    a success). Callers compare ``roll.total`` afterwards, as they always did.
    Grapple, Binding and granted escape options share ext.escape_checks.resolve_escape_check:
    (ctx, effect, dc, grips, against=(), *, check_name="", target_id=None,
    source_id=None, source_actor_id=None, check_ability=None, check_skill=None)
    -> bool, resolving modes/check_bonus,
    the evented roll, this floor/Release checkpoint and CHECK_ROLLED. Callers
    retain removal policy; absent owned check effects, legacy resolution is unchanged.
    check_ability/check_skill keywords select a specific check with hazard-scoped modes;
    omitted keywords keep legacy effect-based resolution. Optional metadata identifies
    the helped target and originating hold; defaults keep ctx.actor/ctx.source metadata.
    ctx.actor is always the roller. Existing hook signatures and persistent state
    remain unchanged.
    ``ability=``/``skill=`` name the check being floored for a caller that rolls outside a ``d20_scope``; they publish
    that on the roll's own frame, so ``check_floor`` plugs-in can narrow a floor to the printed "one *such* ability check"
    (combat/ext/d20_floor.py). Omitting them reads whatever the active scope already carries, which is what every caller
    inside ``d20_scope`` did before."""
    if not has("check_floor") or roll is None or roll.natural_result is None:
        return roll
    if ability or skill:
        with engine.d20_scope({"kind": "check", "actor_id": actor.entity_id, "source_id": str(roll.reason or ""),
                               "ability": ability, "skill": skill, "dc": dc}):
            return floored(engine, actor, roll, dc)
    floors = [int(value) for value in run("check_floor", engine, actor, roll, dc) if isinstance(value, int) and not isinstance(value, bool)]
    if not floors or roll.natural_result >= max(floors):
        return roll
    return roll.model_copy(update={"total": roll.total + max(floors) - roll.natural_result})


def ai_controlled(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` is run by a computer instead of a person at the table.

    Who controls a creature is a saved fact about the match, not a guess: the table records each
    participant's control mode when the match is created (``gate5_service``'s
    ``participant_control_modes``) and the engine keeps it on ``typed_control_modes``. A
    LOCAL_AUTO/API_AUTO participant has nobody to press a button, so a plug-in that must ask that
    creature a question decides for it; a MANUAL/SUGGESTED/MANUAL_AI_BRIDGE participant is the
    table's to answer, and the service asks them (see ``gate5_service.answer_pending_choice``).

    A creature is looked up by its controlling participant -- the table drives summons, companions
    and other dependents through the character that owns them -- and a match with no recorded mode
    for it is read as MANUAL, the same default gate2_engine and gate5_service use.

    For a Needle choice, pass this as ``ask(..., automatic=...)``: ``automatic=True`` lets the
    controller take the preferred option (``gate4_controller.choose_reaction`` reads
    ``automatic_use or not allow_decline``), ``automatic=False`` leaves the question to the person
    at the table. Team membership is not a control mode -- allies are not automatic, and an
    enemy is not the reason a creature's own choice is made for it. Used by d20_floor's replacement
    and keep-cost questions, life_state's soul-return and continuity prompts, and any other plug-in
    whose "may" or "choose" text has to be decided for a computer-run creature.
    """
    modes = getattr(engine, "typed_control_modes", None)
    if modes is None:
        modes = (getattr(engine, "_roster_setup", {}) or {}).get("participant_control_modes", {}) or {}
    if actor is None or not modes:
        return False
    for key in (getattr(actor, "owner_id", None), getattr(actor, "entity_id", None)):
        if key and modes.get(key) in {"LOCAL_AUTO", "API_AUTO"}:
            return True
    return False


def note(engine: Any, source: str, actor: Any, text: str, targets: Any = (), **payload: Any) -> None:
    """One plain log line for the table's history (sys-resources-states 2026-09-29): a PASSIVE_TRIGGERED event whose
    payload carries the sentence, which combat/history_feed.py shows as it is. The reducer treats the event as
    non-mutating, so it is safe in a saved fight."""
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=getattr(actor, "entity_id", actor),
                         target_ids=tuple(getattr(target, "entity_id", target) for target in targets), payload={"log": text, **payload})


def _log(point: str, function: Callable[..., Any], exc: Exception, args: tuple[Any, ...]) -> None:
    import logging

    logging.getLogger("combat.ext").warning("%s.%s (%s) failed: %s: %s", function.__module__, function.__name__, point, type(exc).__name__, exc)
    engine = next((getattr(arg, "engine", None) or (arg if hasattr(arg, "_append_event") else None) for arg in args
                   if hasattr(arg, "engine") or hasattr(arg, "_append_event")), None)
    if engine is None or _while_listing():
        return  # logged above; never a fight event while choices are being listed
    seen = engine.__dict__.setdefault("_ext_failures_logged", set())
    key = (function.__module__, function.__name__, point, type(exc).__name__)
    if key in seen:
        return  # once per fight for each failing hook, not once per call
    seen.add(key)
    if not getattr(engine, "_ext_logging", False):
        engine._ext_logging = True
        try:
            engine._append_event("GM_RIDER", f"ext:{function.__module__}", actor_id=engine.state.current_actor_id,
                                 payload={"rider": f"{function.__module__}.{function.__name__} ({point}) failed: {type(exc).__name__}: {exc}"[:400]})
        finally:
            engine._ext_logging = False

# AUTO41: figment.py reuses compile_actions, match_start, additional_actions,
# candidate_allowed and save; no new hook point. figment_study spends the normal
# Action on one perceived placement. Recognition/study/immunity are per-zone
# creature IDs recorded through placed.update. figment_create's minor flag
# gives the owned 5-foot, 100-round image without Concentration or paid setup;
# figment_minor_detail and the minor figment_move retain Bonus Action economy.
# illusion_sting_premise in illusion_riders.py is Phantom Sting's optional hit
# follow-up. All choices use Needle; unrelated actors/zones leave hooks inert.
# Ordinary Study checks set escape_checks.resolve_escape_check(escape_hooks=False)
# to keep hold-only Advantage separate while sharing check bonuses, scopes and
# floors. ability_checks.ordinary_check_bonus returns None for missing ordinary
# statistics: optional check actions must not substitute saving-throw totals.
# Phantom Sting queries senses.perceives_cell at its hit stimulus, not its caster.


# AUTO42: stars.py uses the existing flight hook for active Star-Sovereign
# conditions and source-owned Star Shadow summons. stars_starbolt_mark resolves
# the optional once-per-turn on-hit mark through Needle. stars_spark_pick chooses
# one actual marked area recipient before the existing save hook penalizes it.
# stars_impact_terrain
# creates persistent, evented difficult ground from the actual impact aim;
# Falling Star requires known caster alignment, Heaven-Falling Star uses the
# impact point. Meteor's enlarged variant uses ordinary compilation/candidate
# gates and the caster's known Domain alignment. No core or lock seam changed.

# CW1r1: karma_causes.harmful_condition/inflicted_harm are public shared
# classification helpers for Karma imprint and consequence event consumers.
# They use actual typed negative mechanics/explicit harmful kinds, excluding
# presentation-only colour, beneficial/defense/structural rules and self-costs.
# No new hook, runtime patch or lock integration is introduced.

# AUTO44: poison.py reuses flight, damage_defenses, escape_mode, compile_block,
# compile_actions, save_final, after_hit_choice and event. No new core seam.
# poison_delivery_save gates the actual delivery save once per turn;
# poison_next_check consumes its evented condition on that holder's next check.
# poison_dose_followup resolves saved, reviewed failure/success branches via
# optional Needle choices after the final save, including actual-paid CP pricing.
# All hooks require an owned Poison row/active source; native flight uses the
# existing altitude and concentration lifecycle. Unknown physical provenance
# never gains the nonmagical resistance.



# AUTO45: riders_metal.py reuses compile_action, effect, save_final, zone_recipient_allowed,
# turn_start and turn_end. metal_needle_seal resolves reviewed per-recipient
# post-hit/failure choices and one optional Nascent second seal per activation.
# metal_filings_cloud gathers actual final saves before one placement; its
# terrain policy uses the existing zone recipient veto, so a successful save
# exempts only that cloud during the casting turn. Owner-start/end clocks are
# stored in evented placement data. Other zones and old sealed rows are inert.
# metal_needle_interference requires the actual recipient's active Concentration.
# metal_needle_targets reuses the bounded roster chooser, including explicit
# self recipients. Automatic harmful selections stop at the hostile count.



# AUTO46: magma_crust.py reuses before_target_reactions, attack_damage, effect, candidate_allowed,
# zone_recipient_allowed and turn_start. Only reviewed Magma Glob rows choose
# an actual post-hit expression and spend the integer global-turn allowance.
# Active Volcano-Sovereign marks replace Glob dice; ownership alone is inert.
# Shape the Crust's saved ally/patch receipt vetoes only that patch's terrain
# and hazards, and expires on the source's next start. Other zones are inert.
# Shape's reviewed editing_existing marker removes inferred new terrain from
# the fresh action-local context. Its sealed catalogue retains aim eligibility;
# existing patches are edited without creating both named terrains at the aim.

# AUTO47: iron_forms.py reuses attack_result and after_hit_choice. The reviewed
# hundred_forms ownership marker counts actual Unarmed Strikes in one Attack
# action, including misses and nonterminal defeating strikes. Two distinct supported Forms are stored in an
# evented owner-end condition. Uses share the existing per-strike Form ledger,
# so ordinary/Court/Sovereign choices cannot repeat a Form on the same strike.
# Old bundles without the marker retain the prior helper behavior.

# AUTO61: river_riders uses save_final for newly sealed rider_response_fail
# declarations with final_save=true. It matches the actual selected Response
# talent and failed final save within physical melee reach, independent of a
# spent Reaction. Soft Body, Hard Floor reuses the shared rider menu and native
# cannot_stand/Speed/no_dash effects with target-next-start expiry. Legacy
# declarations without the marker keep their after_save path; ordinary saves
# and unowned rows are inert. No new core seam or runtime patch.
# Low River Stance additionally supplies stand_cost=5 only for its newly owned
# flowing_river/low_river_stance row, through the existing native posture path.
# It does not bypass standing vetoes, budget or Speed; old/unowned rows are inert.

# AUTO62: destruction_blast/destruction_shapes reuse compile_action, existing
# effect dispatch and candidate_allowed; no core or lock-file changes.
# New reviewed destruction_shape_save pays/freezes Deepen before saving throws,
# uses final CP (including existing Engine/Incarnation discounts) for success
# damage, and asks an optional self exclusion without excluding other creatures.
# compile_action preserves CELL/single-creature delivery and AI damage estimates.
# prepare_release is the public helper shared by finite saves, distinct rays and
# newly bound tethers. The reviewed distinct_rays/bind_target markers opt in new
# sealed actions; markerless saves/rays/tethers retain their old behavior.
# damage_required checks actual committed HP/temp-HP damage before type/reward
# riders. Returning Calamity's cost/range correction is typed-data only.
# Tether candidate_allowed is a pure target/active-condition query. New tether
# condition data freezes target id, type id, dice count, save DC and final CP;
# Concentration-end owns its lifetime. No engine mutation or private cross-plugin
# calls. New self-exclusion ownership rows are absent from historical bundles.
# Caster exclusion uses before_target_reactions to narrow the live area roster
# before reaction admission. Shared rider_targets accepts an optional prompt;
# absent text preserves its existing prompt. New single_collision_die ownership
# rows give Hammer exactly one d8; old compiled Hammer rows keep their old pool.

# AUTO109/AUTO109r1f1: destruction_break_guard_option (destruction_blast.py) resolves
# "Break the Guard: a creature can suffer only one option at a time". Arguments:
# ctx (the failed Fracturing/Scouring save, already narrowed to the one subject)
# and eff {"option": "ac"|"advantage"|"cover", "type_id": the Blast Type that
# resolved this release}. It first removes exactly what the creature's recorded
# earlier option left -- the exact condition/modifier instance ids named by its
# destruction_break_guard_active marker, which also records the caster that put
# them there -- then applies the ordinary typed effect for the new option
# (ac_bonus / advantage / destruction_no_half_cover) and re-records the marker
# with the option, those instance ids, the caster, the activation and the Blast
# Type in force. Same-option instance lifecycle is unchanged.
# Two owners of the talent are handled: the rule is about the creature, so a
# second caster replacing an option removes the first caster's instance, located
# by the marker the first wrote rather than by the caster now acting. Because the
# marker names exact instances, Fracturing Break's own Advantage survives an
# option change even though it rides the same release and source as the guard's
# (AUTO109r1f1; an earlier version matched by field and had to leave it alone).
# "type_id" is the Type that actually resolved, never the live sticky choice:
# Ruin-Binding Tether and Calamity Mantle freeze their Type, so a Pulse records
# the Type it froze. Marker data is strings only (option/caster/origin/type_id/
# mods/conds/label) so it survives a commit and reload. A marker from before the
# instance ids were recorded falls back to matching the marker's source actor
# and recorded activation. Inert unless the actor owns Break the Guard and has an option
# chosen. No new hook point, no core or lock file change; reached through the
# existing effect dispatch.

# AUTO113: River Breaks the Charge is GM-resolved; charge_approach and its event
# subscription were withdrawn. MOVEMENT_COMMITTED reports completed movement, not
# the reach-entry step at which this Response must resolve. Any future automation
# must resolve at reach entry after the qualifying voluntary approach, before the
# mover continues, and preserve the printed Reaction, save and choice requirements.
# LOW_RIVER_STANCE (stand_cost) and river_riders' final-save rider_response_fail declarations
# came from cloud worker AUTO61; they are documented in their own modules.


# AUTO47: iron_forms.py reuses attack_result and after_hit_choice. The reviewed
# hundred_forms ownership marker counts actual Unarmed Strikes in one Attack
# action, including misses and nonterminal defeating strikes. Two distinct
# supported Forms are stored in an
# evented owner-end condition. Uses share the existing per-strike Form ledger,
# so ordinary/Court/Sovereign choices cannot repeat a Form on the same strike.
# Old bundles without the marker retain the prior helper behavior.


# AUTO102: magma_crust.py adds magma_furnace_step for Furnace Step's own printed
# exemptions, reusing candidate_allowed, difficult_exempt and zone_recipient_allowed.
# It pays no new hook point: the effect asks which one creature gets no opportunity
# attack (rider_choices.pick, Needle) and denies that creature an opportunity attack
# against the mover through the existing reaction_denied path, so every other creature
# keeps its own. The turn's receipt is one evented condition, and the two ground hooks
# read only that condition, so the plug-in is inert for anyone who does not own Furnace
# Step and for old saved fights. The printed clause waives movement cost, so
# difficult_exempt returns squares of your own Molten Terrain and of ordinary ground
# painted on the battlefield (combat/rules/terrain.json's map terrains) -- never ground
# an ability conjured, and Fire Terrain never at all. The engine subtracts those squares
# from the whole board, so the exemption is computed per source: a square is returned only
# when every area on it is one the clause names and no other area still charges that
# creature for it, which keeps another caster's lava or Obsidian Terrain difficult where it
# overlaps yours. "Still charges that creature" is asked of the engine's own per-area answer,
# zones.zone_is_difficult (the public seam difficult_cells itself uses), rather than reading the
# area's difficulty policy again: ground whose policy does not reach this creature -- aimed at
# other creatures, needing a mark this creature does not bear, or ignored as nonmagical --
# leaves the printed waiver standing. zone_recipient_allowed is narrower still: only your own
# Molten Terrain stops dealing you its hazards, so hostile Fire Terrain and Ash Terrain still
# save, burn and obscure. No core, gate2/gate3 MatchLock or saved-fight lock file is touched.

#
# AUTO122: riders_metal.py adds one consumer of the existing target_eligibility
# hook (no new hook point, no core change, no saved-state field).
# metal_damaged_this_turn(engine, owner, target) is a public shared helper that
# reports whether the owner dealt this target real damage from a Metal-catalogued
# attack or technique during the owner's own turn, read from committed
# DAMAGE_COMMITTED events (actor, target, non-zero committed damage, Metal source).
# glance_target_eligibility uses it to enforce White Tiger Glance's printed
# prerequisite "one creature you can see that you damaged this turn with a Metal
# attack or technique": it returns False (a pure strict target veto) for a
# creature the owner has not Metal-damaged this turn, and None for one it has,
# so the printed "you can see" is left to the ordinary knowledge, range and
# line-of-sight checks. It must not answer True, which is the documented owned
# visibility exception and would reach Glance through cover or blocked sight.
# The helper is the reusable piece; other "damaged by you this turn"
# prerequisites may adopt it. Delivery through a weapon carrying Metal Qi is a
# later provenance contract (M1/M2) and is deliberately not inferred here. The
# gate is inert for actors who do not own Glance and for every other action.

# AUTO123: poison.py adds one owned effect and reuses five existing seams for Coated Weapon, Venom in the Wound and the
# save-success Temporary HP riders; no new hook point and no core change.
#   poison_coating is the new effect: it places the owner's own coating condition, carrying the printed Proficiency Bonus
#     charge count and the printed 1-minute deadline, bound to one chosen held item's identity.
#     after_hit(ctx, target, kind) reads it and runs the printed once-per-turn damage and Constitution save; only an
#     applied Dose Mark spends a charge. Default inert -- with no coating condition the handler returns at once.
#   after_hit_choice(ctx, target, kind) is not used by these riders; see damage_dealt below.
#   damage_dealt(ctx, subject, amount) is Venom in the Wound's optional 2 CP rider. The engine reports this hook only for
#     damage it actually committed (hit points lost plus Temporary HP absorbed), on the attack path and on the
#     save-resolved path alike, so the printed "when you damage a creature" excludes a hit a Resistance or immunity kept
#     at 0 while a save-based poison effect still offers it.
#   save_mode(engine, target, ability, dc, source_id, mode_context) is Venom in the Wound's Blood-sphere Disadvantage for a
#     bleeding target. Disadvantage is a d20 mode, not an integer modifier: this is the seam that rolls two d20s and keeps
#     the lower, while save_bonus returns are summed into the single roll's modifier. It fires only on a Constitution save and
#     only while that creature really carries a Bleeding condition, and only for the saving throw the printed rider itself
#     makes -- its own source id, not any other toxin save -- with the "If you have the Blood sphere" half read from this
#     fight's own catalog (the owner-bound Blood Thread action granted only to Blood sphere owners). A Poison-only
#     character imposes no Disadvantage. Forged Poison + Blood provenance remains explicitly deferred.
#   after_save_resolved(ctx, subject, ability, named, failed) is Venom Body Method's and Thousand-Poison Immunity's
#     Temporary HP. The reward belongs to the creature that saved, so ownership is read on `subject`, the amount uses that
#     creature's own Proficiency Bonus (ext/spirit_traditions.numbers), a save whose own condition names no toxin pays
#     nothing, and each rider keeps its own limit in the engine's turn-flag "once_per_round:" clock (which the owner's turn
#     start retains). Thousand's optional "you may" is a Needle choice on either side's turn, and declining spends nothing.
#   compile_actions adds Coated Weapon's Bonus Action, because the typed row's action is marked automated in
#     combat/rules/feature_blocks.d/auto44_poison.json and would otherwise not be built.

# AUTO93 Retribution: existing retribution_dug_in accepts opt-in choose_instance.
# It stores integer choose_instance=1 with the original target id on its native
# owner-next-start condition. The existing incoming_damage hook asks that owner
# on each positive B/P/S packet from that target; decline preserves protection,
# accept consumes it once. Player ownership is unchanged on an enemy AI turn;
# automatic owners choose automatically. Missing flag keeps the old automatic
# first-packet reduction. This uses public needle.ask/checkpoint_id only, with
# no new core seam. Native non-stacking Resistance integration remains a written
# blocker; the existing reduction is not certified as a complete Resistance rule.
# Terrifying Hook and Violent Pressure newly compiled Frightened rows use native
# recipient-next-end expiry. Older sealed special durations are not rewritten.
# AUTO126 (corrected by AUTO126r1f1): retribution_haymaker asks combat/physiology.trait
# whether the target has a voice_and_breath_channel before it damages it, so a printed
# "a creature without a meaningful mouth, throat, breath channel, or equivalent anatomy
# is immune" resolves from a fact the creature's own printed record states. That trait
# has no default and no creature-type default: an unstated record reads as unknown and
# the hit lands as it always did, and not needing to breathe (breath_dependent) is a
# different fact, so an undead or construct with a working mouth can still be silenced.
# physiology.trait is the shared documented query; it changes nothing unless an ability
# asks for it, and only a character owning Haymaker reaches this check.

# AUTO92 Sabers: existing after_hit(ctx, target, kind) consumes only the newly
# sealed sabers_rider/battleline_shove_cut_v2 hit_effects row and a Sabers action.
# Native if_moved, paid_option and save/menu effects own movement, payment and
# final outcomes. No marker means no new behavior. if_size_at_most now accepts
# optional absolute max_size (Tiny..Gargantuan); missing max_size preserves the
# old relative-footprint behavior. Consumers: Battleline Shove-Cut, Horse Arc.
# Existing cone_passage accepts opt-in choose_allies; it records chosen live ally
# ids once per activation and native line cells/owner-start expiry. Its existing
# opportunity_allowed hook narrows to recorded allies; markerless Army passage
# keeps its team-wide behavior. Native Infantry no_opportunity_attacks is target
# next-end only; no core hook/seam or serialized lock format changes.
# The same AUTO92 paid_saber_hit hook now reads explicit sealed source_mechanics
# lists (including generic reactions, whose Context lacks a sphere tag). Ten-Step
# Pursuit is its second data consumer: Red Trail hit, optional2CP, native next-end
# slow. No hit_effects/source list means no new behavior in old passive rows.
# The aggregate Secret Saber Manuals heading is passive text for newly compiled
# fighters; four independently gated manuals require separate acquisition rows.
# compile_actions seals resource_id=primary in these two new paid hit rows to
# the owner's declared CP pool before bundle hashing; old rows are untouched.
# AUTO127r1f1: Forward Cut's printed "you may also move 5 feet after the hit without
# provoking Opportunity Attacks from that target" is now the existing rider_step row with
# no_oa_from_target, not ignore_oa_from_target. The step is asked for, moves at most the
# printed 5 feet through native granted movement, and its exemption covers that step and
# that one creature only: the old turn_flags spark_step_ignore_oa_from outlived the five
# feet for the rest of the turn, and the older no_opportunity_attacks flag waived every
# creature's Opportunity Attack. Typed data only; no new hook and no core change.
# if_size_at_most's optional max_size reads dynamic_size.current_category, so recorded
# growth and a wide sealed footprint are the creature's current size; a markerless row
# keeps the relative-footprint reading. Saber Scare's critical receipt is one key written
# on every settled result (a miss or an ordinary hit clears it), so the printed trigger
# applies to the attack that just resolved and only for an owner of the row.

# AUTO90: shadow.py adds only declared effects, no core seams.
# shadow_fang_mark offers the hit's optional owner choice through Needle, then
# delegates the actual source-owned mark and owner-next-start expiry to native
# effects. Historical sealed plain mark effects remain automatic.
# shadow_grasping and shadow_lingering_trace(choose_older=true) reuse the public
# mark_applied_in_use helper: a committed CONDITION_APPLIED receipt for this
# source/target after this intent began is required, including actual refreshes.
# A retained mark cannot turn a later miss into a new Imprint. The new Lingering
# flag chooses older marked creatures before removing their instance IDs and
# uses the native eight-hour round-clock deadline. Flagless saved effects keep
# their oldest-first/UNTIL_REMOVED behavior. All stored data is JSON primitives.
# Reviewed Court/World zone.inside rows own ally Stealth Advantage and native
# movement/Concentration removal. Court uses rider_menu after each final failed
# save; World declares enter/start triggers sharing native per-turn usage.
# No inferred unconditional difficult ground is granted by Court. Sovereign
# flight is declared native condition data (60-ft Fly Speed/Hover, one minute).
# Seize/Sever target.requires_mark uses the existing compiler admission rule;
# old compiled catalogs keep their own targeting and area/flight declarations.

# stars_impact_terrain creates persistent, evented difficult ground from the
# actual impact aim; Falling Star requires known caster alignment,
# Heaven-Falling Star uses the impact point. Meteor's enlarged variant uses
# ordinary compilation/candidate gates and the caster's known Domain alignment.
# No core or lock seam changed.

# AUTO130 / SOLFAUTO130r2: stars.py implements the reviewed Star-Drawn Projectile
# benefits and Starlight Ward's known-alignment bonus on existing seams. No new
# hook point or core/lock file change. The printed
# "Choose one benefit" is the compiler's own one-action-per-option menu, so the row
# arrives at the new effect "stars_drawn_state" already chosen; it leaves one of three
# standing states (stars_drawn_cover / stars_drawn_range / stars_drawn_push) for the next
# line attack this turn. compile_actions adds a 60-foot-longer variant of the owner's own
# ranged/thrown attacks (typed range, never melee reach), including ordinary variants
# but excluding its own clones. Normal and long ranges each gain 60 feet. The variant
# says it affects the next attack only and costs no extra points. It is admitted by
# requires_condition while that one state stands; the existing
# candidate_allowed revalidates it. attack_sequence_start spends whichever state the
# attack reaches and records it in transient resolution scratch; the attack_mode
# subscriber binds Half Cover and the marked-target push to the creature the attack
# actually strikes -- that hook is the earliest general seam that already carries the
# redirected recipient and runs before the roll and the defence it is measured against,
# so a benefit follows a retargeted attack rather than the originally aimed target.
# It returns None, so the roll and every other subscriber are untouched. attack_roll_finished
# releases Half Cover at the end of the roll and effect_resolution_scope's finally
# releases it again on the way out of the attack block, so an attack negated by an
# attacked reaction, or whose defender moved out of reach or sight before the roll,
# cannot leave cover suppressed for later attacks or other attackers. A later strike's
# attack_mode also drops a cancelled first strike's pending benefit. Release removes
# only this attack's own instance (ext/owned_effects.remove_conditions), so a cover
# exception another caster applied, or one already standing, is preserved. The
# marked-target push runs on after_hit; after_miss and the scope's finally drop it on
# misses, cancellations, pauses and errors. Nested attack scopes shadow and restore
# their parent's record. No pending benefit is saved to the fight.
# later_reach_ft preserves ordinary reach for subsequent strikes; attack_resolved
# restores ordinary normal/long range metadata and effect_resolution_scope restores
# it for subsequent attack effects. Unannotated saved actions remain unchanged.
# compile_actions also composes the two printed range bonuses on Starbolt itself: a
# character owning both Star-Drawn Projectile and Starbolt gets a sibling at +30 +60
# feet, admitted for a marked (Aligned) target beyond the range the ordinary siblings
# already cover. Composition lives in the Stars plug-in because every compile_actions
# subscriber receives the same snapshot of the fighter's own actions and never another
# subscriber's output.
# The fourth printed benefit, the reroll of a
# miss, is not re-implemented: it stays the one shared d20 rewrite in d20_rewrite_attacks.py.
# Starlight Ward uses the documented damage_reduction_bonus query (the seam Ash Ward uses)
# to add the printed Proficiency Bonus when the protected creature is Aligned. Every hook
# is inert without the owning character, the chosen state, or Starlight Ward's own row.
# Meteor Shower's Aligned 20-foot option names its own availability on the button (inside
# your own Stars Domain) instead of the word "Aligned" alone.

# AUTO91 Void: the existing pure flight(engine, actor) hook reads only a newly
# sealed void_sovereign_flight condition carrying void_sovereign_flight=1. It
# returns integer fly_speed_ft equal to current effective walking Speed and
# flight_hover=1; missing/legacy conditions return None. Native condition expiry,
# movement, hover and saves remain engine-owned. Void Field uses explicit native
# enter/start zone triggers sharing the native per-actual-turn allowance; old
# sealed cast-save rows are not rewritten on load. No new hook or core seam.
#
# AUTO133 Void: No-Purchase Body's two standing clauses ride the existing hooks rather
# than a new seam. "Opportunity Attacks against you have Disadvantage" is answered by
# attack_mode(ctx, target), which is already called before each typed attack roll and
# already reports "ADVANTAGE"/"DISADVANTAGE" (see Fragrant Mirage and Shadow's
# Silhouette Veil); the hook returns "DISADVANTAGE" only for an actual Opportunity Attack
# (ctx.typed['opportunity_of'] or an opportunity source) aimed at a creature that both
# compiled the printed row and holds a live Void Shell. "forced movement against you is
# reduced by 10 feet" is answered by forced_movement_reduction(ctx, subject), whose
# nonnegative return is already added before typed push/pull (see Berserker's Unyielding
# and Brute's Sovereign Weight); the hook returns the printed 10 feet only for the same
# owner. Both default to None, so a creature without No-Purchase Body, or whose Shell has
# ended, is untouched, and every ordinary attack and voluntary movement is unaffected.

# Weather sphere (Sphere of Weather), automation lane AUTO13 r25 -- combat/ext/weather_signs.py, weather_mantle.py, weather_shroud.py:
#   The six printed Weather Sign talents (Wind, Rain, Cold, Heat, Dry, Thunder) have no canonical-catalog record, so their
#   printed Mantle and Shroud rows live in combat/ext/weather_signs.py (one table, read by both Weather modules). Every hook
#   returns early unless the creature owns the row or carries one of its own Sky Mantles / Cloud Shrouds, so a character
#   with no Weather feature and an old saved fight (a sign_supply with no data["sign"]) behave exactly as before.
#   Effect types: weather_sky_mantle (spec refresh/quick/free/lingering/shared_favor; asks the sign and active-or-forced,
#   defers Concentration until consent, stores sign, forced, realm, speed_ft, rule, save_advantage, temp_hp as integers and
#   strings); weather_cloud_shroud (spec persistent/cracking; asks the sign, stores sign, dc, save, fail, success,
#   successes, persistent); weather_thunder_shroud_move (no action, once per round, within 30 feet of the original target).
#   Condition data read back: sign, forced, sign_supply, realm, speed_ft, rule {"damage_resistances", "death_save_mode"},
#   save_advantage, death_save_advantage, escape_advantage, temp_hp, opportunity_disadvantage_ft on a Sky Mantle; sign, dc,
#   save, fail, success, successes, persistent, speed_halved_below_ft, expiry_round, expiry_slot,
#   concentration_started_sequence on a Cloud Shroud. Both are integers and strings (the fail/success rows are
#   ordinary typed effect rows), so a table commit and reload keeps them.
#   Feature blocks: "weather" kinds weatherproof_mantle / weather_backlash / shared_weather_favor / persistent_shroud /
#   pressure_cracking_shroud / lightning_chooses_the_rod / quick_mantle / lingering_mantle
#   (combat/rules/feature_blocks.d/auto13_weather.json). Only weather_shroud.py answers the block, so one talent is one row;
#   weather_signs.rows_of / owns is the shared reader.
#   Hooks: compile_action (give Cloud Shroud its saving throw), compile_actions (any-creature target, Persistent and
#   Pressure-Cracking casts, Move Thunder Shroud, the Shared Weather Favor recipients), compile_resources (one free
#   Quick-Mantle cast a short rest), candidate_allowed, turn_start (the Mantle's and the Shroud's own minute, Heat's
#   temporary Hit Points), turn_end (the repeated Shroud throw), attack_mode (Wind Shroud's ranged Disadvantage on the
#   attacker carrying its marker, and the Mantle's Opportunity-Attack Disadvantage), save (Defensive Weather, each sign's
#   own printed hazards, Rain's and Dry's next-save Disadvantage), damage_defenses (Weatherproof Mantle's Wind, "Resistance
#   to nonmagical ranged weapon damage"), condition_attempt (Dry's poison immunity), escape_mode (Rain's escape checks),
#   event (MOVEMENT_COMMITTED, the feet moved this turn Wind reads), button_description. Each is default-inert.
#   One cast is one sign: the Sky Mantle sign, the point that forces it and its Concentration are settled on the first
#   recipient of a cast, so Shared Weather Favor's extra recipients share one question, one payment and one Concentration
#   ("All targets must receive the same Weather Sign").
#   Weatherproof Mantle is for one sign per purchase ("Choose one Weather Sign talent you know ... choosing a different
#   Weather Sign each time"). The chosen sign is asked once and written on the owner as a modifier on the plug-in's own
#   field "weatherproof_sign" (integers/strings, survives commit and reload; nothing else reads it), so a later cast of a
#   different sign gains nothing from that purchase. Its named Resistances are condition rule data read by the shared
#   damage_defenses path (combat/ext/standard_conditions.py), so suppression and penetration behave as for every other
#   Resistance; the one benefit that is about the attack rather than the damage type (Wind) is answered through the
#   damage_defenses hook itself, and Dry's "necrotic damage from desiccation" is stated for the table because the engine's
#   Resistances cannot tell desiccation from any other necrotic damage.
#   Defensive Weather reads the pending save's sign from the conditions and damage types typed_executor already names for
#   it ("damage:cold", "deafened", ...), through weather_signs.SIGNS_OF, plus the sign a Cloud Shroud throw writes on its
#   own context (typed["weather_sign"]); a sign's own printed save advantage applies only to the hazard it names, through
#   weather_signs.HAZARDS. A save whose sign cannot be read is left alone.
#   A hazard whose printed line is limited to one cause ("by thunder, lightning or storm effects", "against cold weather
#   hazards") additionally requires that cause, read by weather_signs.source_kinds from the effect that caused the save:
#   the save's own source id, plus the action's display name only when the save is that action's own (a named rider's
#   Context.effect_source replaces it, so a parent action's weather name is never borrowed for an unrelated rider), plus
#   the hazard name the engine gave the save and the Weather Sign it names. Cold weather is claimed only from an
#   unambiguous hazard phrase ("cold weather", "blizzard", "ice storm", "cold front", "freezing wind") or a printed
#   Weather Sign effect of the cold category, never from a bare "frost"/"freezing"/"glacial" in an ordinary technique's
#   name. Anything the engine cannot place is left to the table's own rider, which says to establish the cause first.
#   The printed "up to 1 minute" of a Mantle and a Shroud is each swept on turn_start by expiry_round/expiry_slot, and a
#   Concentration-backed one releases exactly the Concentration it took (concentration_started_sequence), leaving any other
#   held state alone. A Shroud row that waits for "the start of your next turn" is anchored on the Shroud owner's own turn
#   clock (weather_signs.owner_start), worked out again at every throw.
#   Pressure-Cracking Shroud uses the engine's own "resistance_suppressed" modifier (typed_reactions.defend), so the target's
#   Resistance returns by itself when the printed duration ends.
#   The Shroud's repeated throw is rolled by this plug-in, not by the engine's repeat_save: a printed Shroud's successful save
#   prevents that round's effect without ending the Shroud. The Persistent Shroud's success counter is recorded with
#   retained_updates.record_instance_update so a replay reproduces it.

from . import save_recipient_choices, sword_second_pass  # noqa: F401
