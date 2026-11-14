"""Hook points (arguments; what the hook returns):
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
    Darkness checks both ends through motion.obscured/obscured_at: since FD-19 an unlit square is Heavily Obscured
    (combat/lighting.py) and Dim Light is tracked for sight Perception checks, while the approved
    darkness/smoke/fog/obscurement answers below are unchanged.
  source_learning_options(sheet, talents) -> dict | None. Read-only menu for a source-owned
    learning choice attached to a Sphere (combat/source_learning.py). The dict names the source,
    Sphere, prompt, proficiencies, bonus talents and notes; the Grow UI renders it. Absent providers
    offer nothing.
  prepare_source_learning(sheet, sphere_id, choice, talents, gm) -> dict | None. Validates a
    learning choice before its Sphere row is saved; None means no source handles it. A provider
    refuses invalid or unknown input with TabletopError and never saves partial state. Two replies
    for one choice are refused with a 409.
  project_source_learning(sheet, row) -> sheet | None. Projects a saved learning row onto the owner
    sheet during table application. Projection is pure and must not reread live state. It runs
    observationally (ext.run), never transactionally, because table application is also a read path.
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
  payments; attack_modifier_variant binds exact variants to their parent controls.
  capture seals attack_modifier_selected (modifier ID -> option and payment).
  settings(actions) removes those captured rows and costs from declaration and
  copies the final parent loadout onto delivery variants. Other embedded modifiers
  retain their own delivery. An explicitly selected variant owns its declared
  option/payment, even when saved parent preferences differ. Parent attacks use
  those preferences, including Ask me for effect/payment/damage, only after the hit.
  Unspecified damage choices still use the saved preference. All affordable
  printed payments are offered; no affordable payment skips the add-on with a
  plain log line, never a free effect or an illegal ordinary attack.
  attack_modifier_family names the parent preference identity, shared by
  attack_modifiers and paid_hit to keep their routes mutually exclusive.
  No parent loadout or matching owner leaves variants unchanged. Optional Ask-me
  activations retain accept/decline even with one affordable option; mandatory
  single failed-save outcomes may resolve directly. Exact AI variants retain
  their chosen option/payment, charged only on a qualifying hit.
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
  Captured variants with an owned parent toggle use the existing candidate_allowed
  hook to respect that toggle for recorded MANUAL/SUGGESTED/MANUAL_AI_BRIDGE seats:
  every embedded controlled modifier must be on. Free settings remain reachable;
  turning a modifier on restores every exact variant (targets, paths and options),
  not a truncated selection. LOCAL_AUTO/API_AUTO and engines without a recorded
  human mode keep legacy candidates. Absent parents/settings remain inert.
  Shared attack_modifiers.variant_modifiers(action, actions) supplies the owned
  groups to admission and variant_replaced(), the sheet replacement check; neither
  migrates stored actions. Legacy-paid unconfigured groups retain their on default.
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
  Purchased Treasure Consumables (owner 2026-10-11, combat/ext/treasure_consumables.py): the ``consumables``
  half of ``resolved_treasure_purchases``. ``compile_actions`` reads that list the sheet already carries and
  publishes one action per bought batch, so a consumable bought at creation fights instead of printing as text;
  the ``wondrous`` half was already carried (factory_compiler). Per-batch uses are an integer turn flag
  ``_consumable_round_spent.<consumable_id>`` (persistent across native turn resets), gated by ``candidate_allowed`` and
  charged by the ``treasure_consumable_spend`` effect. Duplicate purchases pool their batch quantities and
  publish one action. The documented object_targets/object_action hooks carry printed consumable attacks
  against map objects; misses also spend stock. Native object ignition and objects.deal carry burst clauses.
  Recovery Pills offer a self Bonus Action and a separate Action to administer to another creature at 0 HP. A printed Difficulty Class rides on the action's own
  ``typed.numbers.save_dc`` (typed_executor.block_save reads it there), so one consumable's DC never moves
  another's. A consumable with no typed row compiles no action: no behaviour is invented. These ids are absent
  from authority/typed_mechanics/rules_text.json, so the authority builder drops any reviewed_final row naming
  one (tools/build_typed_mechanics_authority.py), which is why this is a documented hook route and not data.
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
                                                 Queried while the current actor can act, even after spending an
                                                 Action: each definition's own Action/Bonus Action/NONE economy
                                                 gates apply. Ready declarations still require an available Action.
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
  requires_perception typed metadata          -> True opts a compiled creature selector into current sight OR
                                                 pinpointing perception via target_knowledge.perceives_target.
                                                 Default/absent retains sight for non-attacks. Explicit
                                                 requires_seen_target takes priority. Memories and team knowledge
                                                 alone never suffice. Range, effect-path, relation and ownership
                                                 gates remain unchanged; does not grant sight or observations.
                                                 Used by source-owned One-Breath Duel; reusable for any printed
                                                 perceived-creature selection.
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
                                                 admission: non-attacks still require actual line of sight (or the explicit
                                                 requires_perception contract) and effect; attacks still require effect; optional positive concealment checks use actual senses.
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
  activation.requires_any_state metadata     -> alternative condition names or "falling", copied by compile_reaction
                                                 into the generic row. row_allowed admits it only when one condition
                                                 is present (plain names match core/typed IDs) or native falling.required
                                                 holds. Checked before consent, rolls and payment; absent is inert.
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
                                                 The payer's ordinary temporary cost reductions are
                                                 composed into the proposal, supplied or not, before this.
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
                                                 A non-typed native save may set
                                                 include_stored_save_bonuses=True in roll_context to explicitly
                                                 reuse the typed stored-status reader; typed saves must omit it,
                                                 because block_save already reads those statuses.
                                                 Native condition repeat saves opt in at their one _roll_save
                                                 call, with the holder, source and named condition bounded to
                                                 that repeat. Matching one-use modes are consumed once by the
                                                 save_against reader; all independent mode contributions reach
                                                 the engine together for final cancellation. The existing
                                                 repeat scope and explicit flag share one flat-bonus read.
                                                 Existing typed
                                                 `save` DC adjustments stay separate: register a contribution
                                                 at one hook only. No subscriber/None = exact old bytes/draws.
                                                 Invalid returns reject the surrounding transaction.
  save_rescue_bonus(engine, target, row, ability, dc, roll, source_id) -> None or signed int.
                                                 Pure strict query after rescue ownership/ability/affordability
                                                 checks, before outcome feasibility and consent. Adjustments
                                                 sum with the compiled bonus; the same value governs feasibility,
                                                 the applied roll and REACTION_RESOLVED.bonus. Never spends or
                                                 claims a limit during preview. No subscriber = unchanged rescue.
                                                 Supports conditional evolutions and exhausted numeric riders;
                                                 heavenly_integrity_vessel shares its conversion round limit here.
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
  stand_cost_offer(engine, actor, normal_cost) -> None or nonnegative integer. Pure strict
                     preview of a conditional standing benefit that asks its owner at use.
                     Its lowest quote is shown with the ordinary standing candidate but
                     never applies by itself. stand_cost_decision(engine, actor, normal_base_cost)
                     runs only inside the accepted standing transaction; providers may ask
                     through the ordinary choice transport and return an accepted base cost.
                     The lowest accepted base cost applies before additive stand_extra_cost
                     burdens and is checked against the movement budget. Decline/no answer
                     applies no offer.
                     Missing providers preserve existing stand_cost behavior. Use these paired
                     hooks when a cost benefit is a choice made each time another creature stands.
  stand_cost_fallback_decision(engine, actor, discounted_cost, ordinary_cost) -> None or bool.
                     Runs inside the accepted stand transaction only when an offered discount
                     was declined and ordinary_cost is affordable from the actor's remaining
                     movement. True from any provider approves charging ordinary_cost; False
                     or no True reply leaves the actor Prone. Providers can ask the acting
                     creature through the ordinary choice transport. It is not called when
                     ordinary standing is unaffordable; no payment choice is presented then.
  stand_extra_cost(engine, actor) -> None or nonnegative integer feet. Pure strict
                     query; add replies after ordinary stand_cost reductions, before
                     the movement-budget check. Explicit fixed-cost standing abilities
                     bypass cost providers. Default inert. For temporary burdens or
                     terrain penalties that increase ordinary standing expenditure.
  Jump queries (combat/flight.py jump_score and jump_base_height, read by jump_steps and
                     jumps): the only places that decide how high a creature may jump.
    jump_ability(engine, actor)    -> None or "STR"/"DEX", the ability score that measures this
                     creature's jump height and distance instead of its Strength ("You may use
                     Dexterity instead of Strength when determining jump distance or height").
                     The last answer wins; a score the actor does not carry reads as Strength.
    jump_height_multiplier(engine, actor) -> integer multiplier (minimum 1) applied to score-derived
                     jump height after jump_ability resolution. Strict pure query; greatest integer
                     answer wins. Default 1. This lets general jump-height features scale the ability
                     actually used without reading Strength directly. No ability registers it today
                     (Feather scales distance instead); it stays for a height-only increase and scales
                     jump_base_height, which only the high jump reads.
    jump_distance_multiplier(engine, actor) -> positive integer multiplier applied in
                     flight.jump_distance before the standing-start halving and before additive feet.
                     Strict pure query; greatest integer answer wins, default 1. Never scales a flat
                     extension or a next-jump receipt, and a standing jump stays half a running one.
                     It also opts the creature into straight long jumps, because the distance it
                     multiplies is the printed long-jump distance.
    jump_bonus_ft(engine, actor)   -> nonnegative integer feet added to the jump's distance after the
                     running/standing rule and the distance multiplier, so it is never halved for a
                     standing start or scaled by a multiplier. Non-integer answers are ignored and
                     the highest integer counts. These hooks also answer the minimum 14-score ascent
                     gate in flight.jumps: that gate is measured with the substituted score when
                     jump_ability answers one, and a positive jump_bonus_ft answers it on its own,
                     because such a printed increase is granted independently of the score ("does not
                     depend on Strength, Dexterity, or remaining movement").
    jump_height_only_ft(engine, actor) -> nonnegative integer feet (greatest answer wins, default 0). The part of
                     the jump_bonus_ft feet that is vertical only: Polearm Vaulter's "jump height by 5 feet".
                     It is already inside the jump_bonus_ft total for the height gate and whole-step height,
                     and flight.horizontal_jump_feet removes it, so it never lengthens a long jump.
                     All four are pure strict queries called once per jump quote and once per executed
                     jump path: no reply, a fighter with neither, and every saved fight compiled
                     before the rows existed jump, move and replay exactly as before. These hooks
                     store no ability id, grant no move and change no Speed, movement budget or terrain.
  Source-owned next-jump seam (ext/next_jump.py): prepare_next_jump typed effect
                     {feet: int, consent: bool, label: str} grants a persisted receipt to
                     ctx.target only after recipient-owned willingness transport. AI prefers
                     an allied source; manual/Ask-me recipients answer on either actor's turn.
                     START_OF_SOURCE_NEXT_TURN is its native source-owned expiry clock.
                     bonus(engine, actor) -> int is a pure additive flat-feet query,
                     separate from jump_bonus_ft's passive maximum; same-source copies do
                     not stack. jump_score includes this quote for minimum-score admission;
                     jump_distance adds its feet after the standing/running rule and the
                     distance multiplier, before rounding to whole 5-foot grid steps.
                     Receipts therefore grant their full increase to both standing and
                     running jumps and to long jumps as well as high jumps; a distance
                     multiplier never scales them.
                     prepare(engine, actor, mode, path) -> tuple of instance ids
                     snapshots only accepted native jump/jump_down routes, without spending.
                     commit(engine, actor, mode, prepared, traversed) -> None settles those
                     exact receipts after real ascent or a committed jump-down edge step.
                     Failed validation, cancellation, zero travel and interrupted run-ups
                     do not spend. A jump that takes off then stops still spends once.
                     With no opted-in receipt all calls are inert; routes, choices, costs,
                     LOS/LOE and movement budgets remain native. No ability dispatch in core.
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
  When the effect context omits an intent, rider_step uses the active transaction's
  intent for choices and movement; without either it remains inert.
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
                                                 including terminal outcomes. Fire uses it for White-Hot Focus
                                                 settlement after the bound talent, retaining Focus's own damage
                                                 identity and native defenses even after a finishing blow.
                                                 Activation accounting stays in ctx.damage_cache.
  damage_roll_bonus(ctx, effect, kinds)        -> int or None; adds to a real typed damage die roll before its shared
                                                 area cache is filled. Fixed amounts are unchanged. An owned subscriber
                                                 accounts for its own once-per-activation limit in the transient cache.
                                                 effect is None for a primary attack packet. Its base dice are shared,
                                                 but contributions are queried afresh for each confirmed strike at
                                                 prepare_damage_roll, after attack/critical choices and hit snapshots,
                                                 immediately before the damage draw. Misses and fixed packets bypass
                                                 this hook. Per-target attack contributions use attack_damage_bonus.
                                                 For a row that offers a CHOICE of damage type ("6d8 Radiant or Necrotic
                                                 damage, your choice") kinds lists every option, while
                                                 engine._typed_pending_damage_type holds the one the dice will carry: read
                                                 it instead of kinds when the printed rule is about the damage actually
                                                 dealt. Both hooks see that value, and it is restored at once.
  damage_type_override(ctx, kinds, targets) -> str or None; strict query before the single-type early return.
                                                 Exactly one owned provider may replace the packet's type;
                                                 conflicting replies reject the transaction. The provider may
                                                 offer an optional type choice through the normal checkpoint.
                                                 No provider/None preserves ordinary damage-type selection,
                                                 dice, target, defenses and saved state. Circulation uses this
                                                 and damage_roll_resolved to reward only the selected type
                                                 on an actual failed save, including shared-roll retrievals.
  damage_roll_resolved(ctx, effect, cache_key) -> None; notification on EVERY typed damage-roll retrieval,
                                                 including cached area rolls delivered directly for half on a save.
                                                 ctx.damage_cache[cache_key] is the unchanged (total, damage_type).
                                                 Row identity is effect; cache_key also accounts for grouped rows.
                                                 Roll-dependent riders can bind their delivery bookkeeping here
                                                 rather than assuming normal effect dispatch or a fresh die roll.
                                                 Shared-roll bonuses and marked-recipient damage riders can use this
                                                 seam; Comet Adept restores its eligible push marker per recipient.
                                                 Subscribers must gate on owned rows/conditions and keep bookkeeping
                                                 transient. No subscriber means no state, event or damage change.
  Damage replacements use the actual recorded dice count, including critical dice;
  replacement dice are not doubled again. This is shared by every reroll consumer.
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
                                                 with the confirmed recipient after redirects and hit reactions, before damage. Runs once per
                                                 confirmed strike and recipient. A miss never reserves a bonus; after_hit
                                                 may consume a reservation once the packet actually deals damage.
                                                 No subscriber means identical dice and damage;
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
                  Committed traversal supplies the original move_through rule before
                  trigger accounting or rolls; vetoing traversal keeps independent
                  enter/start effects and physical distance accounting unchanged.
                  Absent replies retain the existing team rules. A difficult-terrain mapping
                  uses the same who/eligibility schema as triggers. No mutation or new events
                  occur for default rules. Condition rules healing_denied/temp_hp_denied are
                  enforced at native recorded healing and Temporary HP grants, respectively.
                  A healing_denied value of true refuses every ordinary recovery; a list of
                  healing-source tags (sleep, rest, regeneration -- the provenance keys a healing
                  row carries, typed_executor.healing_source_tags) refuses only recoveries that
                  name one of them, so "cannot regain Hit Points from sleep or rest" leaves an
                  ability's or potion's healing working.
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
  save_context.damage_save(engine, target_id, source_id, source_actor_id) -> immutable
                                                 DamageSave or None. Pure exact-packet query inside typed damage
                                                 delivery: source/user/recipient, actual selecting save ability,
                                                 settled failed flag, actual action name, and area scope from an
                                                 explicit save recipient or matching standing-area delivery frame. Never
                                                 infer a save from the enclosing action or an event search.
                                                 Nested typed delivery replaces/restores the frame; unknown native
                                                 packets return None on identity mismatch. Error/pause restores
                                                 the parent, and nothing is persisted or evented. General seam for
                                                 save-limited guards, absorption and other damage responses;
                                                 Equipment's failed-area Dexterity guard uses it. Old bundles
                                                 have no new Equipment guard row and retain their behavior.
                                                 damage_response_state(engine, proposal, owning_source_id) returns
                                                 the consumer's local dict for this recipient/save outcome only.
                                                 Split damage rows share the budget/decline; another recipient,
                                                 save, nested attack or later unsaved damage gets a fresh dict.
                                                 It is resolution-local, never a condition or fight state.
  damage_response_reduction(engine, target, amount, damage_type, source_id, source_actor_id)
                                             -> None or integer reduction (0..amount, not bool). Strict
                                                 transactional typed-defense checkpoint after resistance,
                                                 vulnerability and passive flat reductions, before damage
                                                 reactions and final_damage. All subscribers see the same
                                                 remaining amount; flat replies add, clamped at zero. None
                                                 is inert. May ask/pay/roll through the active intent; pauses
                                                 unwind the transaction. Providers gate on owned rows and
                                                 explicit packet provenance. Iron Rain's failed-area-save
                                                 response uses this so other reductions still compose.
                                                 No subscribers leaves the defended packet unchanged;
                                                 no response state is persisted by this hook.
  final_damage(engine, target, amount, damage_type, source_id, source_actor_id, intent)
                                             -> None or {amount?: int, hp_floor?: int, reduction?: int, settle?: callable}.
                                                 Strict transactional hook
                                                 after all defenses/reactions, before temporary HP and HP commit.
                                                 Every native damage packet reaches it, including runtime/legacy,
                                                 zero damage and intent=None. Each subscriber sees the same defended
                                                 amount; minimum returned amount and maximum floor combine.
                                                 LOCK27: each reduction must be an integer in 0..defended (no bool).
                                                 Sum reductions once, subtract from the minimum amount with a zero
                                                 floor, then apply the maximum HP floor. All providers see the same
                                                 defended input, including zero. Omitted reduction is zero; existing
                                                 amount/floor results retain their exact ordering and semantics.
                                                 An owner returning reduction must not also subtract it in amount.
                                                 LOCK27d: a reduction reply may opt into settle(applied: int) -> None.
                                                 Capture packet/owner context in that transient callback; never save it.
                                                 After ALL replies validate and the final_damage total/floor compose,
                                                 callbacks run once per reply in registration order, including applied=0.
                                                 Attribute reductions sequentially against the minimum amount; each
                                                 applied value is the decrease in the HP-floor-capped total caused by
                                                 that reduction (before later falling/floor/deferral/survival hooks and
                                                 Temporary HP absorption). An already prevented packet reports zero;
                                                 earlier additive replies have priority when the packet runs out.
                                                 A reply without settle still occupies its place in that allocation.
                                                 With an HP floor, a reduction masked by that floor reports zero.
                                                 Consume only if applied > 0 when the owning rule requires actual use.
                                                 settle requires an explicit reduction and a callable, must return None,
                                                 and must not change this packet's damage; errors/pauses roll back the
                                                 owning transaction. Omitted settle is inert: no callback, event, saved
                                                 field or numerical change. No defense provider is called twice.
                                                 No new saved fields or ability-specific dispatch. Amount
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
                                                 lethal unarmed hit packets; a chosen floor or decline is
                                                 retained for the hit (see s188_hit_settlement). Its four choices and absent
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
  confirmed_attack_roll_bonus(engine, attacker, target, spec, intent, source_id) -> int or None.
    Strict post-hit numerical attack adjustment, before critical/damage resolution.
    The effective attack total and AttackDamage context include the bonus; a
    PASSIVE_TRIGGERED receipt links it to the original draw. Not a damage bonus.
  settled_save_roll_bonus(engine, target, ability, dc, roll, source_id, intent, failed, source_actor) -> int or None.
    Strict numerical save adjustment after outcome settlement, offered exactly
    once per save roll and from one dispatcher only: a native save in
    gate2_engine._roll_save before SAVE_ROLLED, a typed save in
    typed_executor.settle_typed_save (the typed caller passes
    defer_save_settlement=True) once its later reaction overrides settle,
    before save_final. PASSIVE_TRIGGERED links any change to the original
    roll_id; typed save_final and downstream typed-save consequences receive
    the adjusted roll. source_actor may be None.
    An independent forced outcome stays authoritative; otherwise the effective
    success/failure follows the adjusted total, so the two can never disagree.
    Both seams default to no adjustment and emit no receipt without a bonus.
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
  attack_state_rows(engine, actor, action_dict) -> list of {label?: str, note?: str} or None; read-only presentation
                                                 of a standing state that modifies the actor's Unarmed Strikes or natural
                                                 weapons (a stance, a manifested body weapon, a transformation). Called
                                                 once per fight-menu action row for the acting creature, before the row's
                                                 text is shown. ``label`` is appended to the row's label in parentheses
                                                 ("Iron Fist attack (Black Claw)"); ``note`` is added as a card line.
                                                 Providers decide from their own state/ownership and return None for
                                                 every other row, so a character without the state is unchanged. No
                                                 handler means no presentation change; nothing is persisted, priced or
                                                 gated here. Used by combat/ext/daemonic_riders.py (Black-Claw).
  Typed effect ``spend_projectiles``: an ability whose printed cost is a quantity of pieces rather than one piece per
  attack -- "Spend five pieces of ammunition or five thrown weapons", "Spend one ammunition unit or thrown weapon per
  10 feet of line, minimum 10 projectiles", "Spend at least 20 ordinary projectiles". Row:
      {"type": "spend_projectiles", "pieces": 5,
       "per_ft": 10, "length_ft": 120, "minimum": 10,   # optional: a count per that many feet of the printed shape
       "targets": true, "shape": "cone", "area_ft": 30,  # optional: one piece per creature the printed area reaches
       "allow_thrown": false, "ammunition_ids": ["<item id>"], # optional typed stock eligibility, shared by gating/payment
       "stock_label": "arrows or bolts suitable for embedding", # optional plain button wording
       "evidence": "<the printed sentence>"}
  The charge comes from what the fighter actually carries, in whole pieces: every ammunition kind they hold (the kind
  the ability is delivered by first) and then held thrown weapons, because the printed cost reads "ammunition or thrown
  weapons". A fighter whose sheet records no ammunition at all and carries no thrown weapon keeps this repository's
  existing unlimited-ammunition reading, so no existing character loses an ability; the printed quantity is then quoted
  on the ability's own button instead. Owner: combat/ext/ammunition.py, whose public ``projectile_requirement`` and
  ``projectiles_available`` let a plug-in read or gate the same row. Ceaseless Ammunition ("fire as many pieces of that
  ammunition as required without reducing the tracked amount during combat") leaves the stock untouched.
  carried_item_remaining(engine, actor, item_dict) -> int or None. Pure query of remaining inventory units;
  carry.remaining_quantity caps the original quantity by subscriber results. None is inert. Possession, physical
  weapon modes and consumable-cost pools share this contract; ammunition owns spent-thrown-piece accounting.
  extra_targets range_ft: explicit 0 disables the actor-distance gate (area_only uses its resolved area);
  absent range_ft retains action range. sight defaults true, false removes the recipient-perception requirement.
  Typed effect ``barrage_sky_net``: one row {"type": "barrage_sky_net", "evidence": <printed>} on a zone trigger whose
  printed text makes the creature that meets the area choose between two different outcomes ("A hostile creature that
  enters the area ... chooses: Slow Down ... Push Through ..."). The question goes to that creature's controller, not to
  the area's creator, because the zone trigger runs inside the creature's own intent. The two branches use the general
  seams above plus ``movement_step_surcharge`` and ``attack_bonus``. Native attacks use the existing ``d20_bonus``
  checkpoint; a matching transient d20 scope with block_attack's typed spec and before_attack_d20 callback keeps that
  exact strike's penalty exclusively in ``attack_bonus``. Catalogue kind alone cannot identify native rolls from typed
  trap/ray effects. The guard only reads the resolver scope; it adds no state and applies the penalty once.
  Owner: combat/ext/barrage_sky_net.py. Inert for every creature without the Slow Down condition.
  Push Through filters base weapon rows through shared possession, hands, ammunition_choice and attack_reaches
  queries before choosing. Multiple usable weapons use needle.ask with the attacker's controller as chooser;
  the affected creature retains its separate Slow Down / Push Through choice. Single usable weapons need no menu.
                                                 action_text scopes setting_only selectors through option_text using
                                                 shape_talents, augment_key, attack_modifier_setting.modifier and typed
                                                 source/option_of/forged_from IDs, then exact printed option names.
                                                 One record_display card replaces raw rules/selector boilerplate; other rows are inert.
                                                 Ambiguous printed names use effect-type source metadata in
                                                 combat/rules/option_text_sources.json; the builder exports exact scoped
                                                 owner text without adding executable mechanics or changing grants.
  status_description(engine, holder, row, data) -> {text?: str, reading?: str, rules?: str, duration?: str, paying_pool?: str, handling?: str,
                                                 source_ability?: str, applied_by?: str, display_name?: str,
                                                 conceal_source?: bool, player_card?: dict} or None;
                                                 conceal_source clears projected source_actor_id/source_definition_id
                                                 for private records, without altering saved provenance. Default False;
                                                 the plug-in also supplies anonymous applied_by/source_ability text.
                                                 Setting selectors reuse option_text.setting_display for buttons and pills.
                                                 player_card is record_display output (text/html); default absent/inert.
                                                 One rules-owning provider wins, otherwise the first applicable provider;
                                                 parent-feature fallbacks never stack. Queries are pure.
                                                 reading is a live state reading (a health band), not rules:
                                                 every provider's reading is kept beside the owner's text.
                                                 It is a separate channel from conceal_source: a provider that
                                                 hides its source must not also return a reading.
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
                                                 selected_mode (label suppressing the automatic preset explanation),
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
  d20_finalized(engine, roll, intent)         -> None. Strict transactional observation after every d20_bonus
                                                 contribution and before the caller consumes the final roll.
                                                 Settle result-dependent rewrite riders and outcome text here;
                                                 D20_REWRITTEN events describe intermediate records. This hook
                                                 cannot replace the roll or reopen rewrite selection. Payments
                                                 and unconditional on_use work remain at original acceptance.
                                                 May open player choices; pauses/errors roll back the action.
                                                 Nested rolls finalize independently; providers must correlate
                                                 pending work by roll_id. Missing subscribers are inert.
  journey_roll_offers(session, window)        -> list of {id, label, sides, cost: [[resource_id, amount]], group}. The journey form of the
                                                 d20_bonus window (combat/ext/journey_rolls.py): asked after a journey check's d20 is
                                                 drawn and before its result is declared, again after every addition, with the running
                                                 total (window: actor_id, roll, total, natural, dc, dc_known, context {ability, tags},
                                                 added). One offer per ``group`` per roll. A manual owner answers with the roll_decide
                                                 command (its other journey commands wait); a LOCAL_AUTO owner adds the cheapest offer
                                                 that can still fix a failure it can see (dc_known), else declines. Players see the roll
                                                 and the DC only when dc_known, and a check whose DC its owner does not know stays
                                                 that owner's business: journey_view redacts its DC, its roll and its outcome for
                                                 every other seat. Consumers: thread_handling (Threadwork's difficult check)
                                                 and journey_rolls.roll_check; rows come from combat/rules/journey_rolls.json.
  journey_roll_finish(session, actor_id, window) -> True when it settled a window whose ``consumer`` it owns; runs once, with the
                                                 final ``total``, when the window closes (decline, nothing left, or an automatic seat).
  d20_bonus(engine, roll, intent)             -> None, {source_id: str, bonus: int, user_id?: str}, or a lazy iterator
                                                 of those contributions. After rewrites,
                                                 before outcome; composes bonuses without changing natural d20 or mode.
                                                 Strict subscribers run in priority order, each receiving the effective
                                                 roll after earlier bonuses, so consent/eligibility recheck that total.
                                                 A lazy provider must advance its effective roll by each yielded bonus
                                                 before testing the next option; the checkpoint records each yield
                                                 before resuming it. Never prepay later choices. Pauses and errors
                                                 unwind the action transaction before commit.
                                                 D20_REWRITTEN (operation bonus) records original/effective rolls.
                                                 Optional user_id names the creature that used the ability, which is not
                                                 always the creature whose roll the bonus lands on; it is validated
                                                 exactly as on d20_result and is recorded only when supplied, so a
                                                 producer that omits it writes the unchanged event shape. Missing is
                                                 inert and the log falls back to the roll's own creature.
                                                 Every d20 passes this seam, so it also reaches saves forced by native
                                                 (non-typed) catalog actions, which the typed-only save hooks cannot
                                                 see. A producer reads engine.d20_context(roll) to learn the kind and
                                                 source. Producers own source eligibility and must avoid applying the
                                                 same printed bonus through both typed hooks and this checkpoint.
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
                                                 effect: a second non-None answer raises OptionalFollowupTargetConflict
                                                 (a ValueError). Consumers use
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
  choice_map_pick(engine, choice, context) -> {"instruction"?: str, "cancel_label"?: str} or None
                                                 Read-only presentation vote that a space choice is picked by
                                                 clicking a square on the MAIN map (owner 2026-10-03, round 24:
                                                 "you can just click on an available square on the grid rather
                                                 than a tooltip"). Consulted once by
                                                 combat/choice_presentation.py map_pick, which attaches the answer
                                                 to the choice as map_pick together with the legal squares
                                                 (choice.options[].cell and map_pick.cells). Arguments: the
                                                 engine, the choice as built (spatial options carrying their
                                                 cell, mixed text options without one) and the same context as
                                                 choice_prompt; return a
                                                 dict to enrich it, None for the default map presentation. It is a
                                                 presentation vote only: option ids, labels, the stay-put option
                                                 and the answer binding are unchanged, so legality and the
                                                 resolution cannot be affected. Spatial options carry cell and
                                                 optional target_id; maximum > 1 uses map toggles and confirmation.
                                                 A prompt string may supply a concise placement instruction;
                                                 areas maps option ids to native hover footprints. A choice is
                                                 spatial only when an option carries a square: creature-only and
                                                 text choices keep their lists, and non-space choices do not reach
                                                 this hook. Default-inert: with no answer every choice looks
                                                 exactly as it did, so an older client and a saved fight are
                                                 unchanged. No subscriber changes legality.
                                                 combat/ext/teleport_steps.py map_pick uses it for
                                                 every teleport destination.
  Typed effect contexts preserve explicitly selected ALLY_OR_SELF recipients,
  including the user, for conditions, modifiers and extension effects alike.
  SELF actions retain implicit-user semantics; areas retain their area subjects.

  before_attack(engine, attacker, defender, intent, context) -> {"mode": mode} or {} when used; None on decline/no ability.
                                                 context["ranged"] is the strike's resolved range flag (spec range_ft is not None).
                                                 Roll-reason attribution (2026-10-16): a mode reply may carry
                                                 "effect" and "why" strings (plus an optional "owner" display
                                                 name) so the displayed roll reasons name the ability and its
                                                 later contribution; a bare {"mode": ...} keeps the plain
                                                 "Choice before the roll" label, and both stay visible when
                                                 they cancel an earlier source.
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
  object_target_cells(engine, obj)           -> None or nonempty iterable of distinct in-bounds Positions. Pure,
                                                 strict query, with one geometry owner per object; conflicting replies
                                                 and malformed geometry raise. combat.object_geometry.target_cells
                                                 defaults to (obj.position,) when nobody answers, without writing
                                                 fields/events or changing old serialization/candidate identities.
                                                 Core offers ONE object candidate only if the SAME occupied cell
                                                 passes range and sight (including intervening solid obstacles).
                                                 objects.blocking_zones, blocker_at and area intersections share this
                                                 helper; an area damages an object once if any clear occupied cell
                                                 intersects, ignoring only that object's own intervening cells.
                                                 Existing objects plugin owns explicit component.width_cells and
                                                 length_cells (positive integers), rotation 0/90 (integer, default 0).
                                                 Anchor is northwest; width east, length south; 90 swaps extents at
                                                 that same anchor/z. No catalog/size inference or map defaults.
                                                 Consumers freeze dimensions in evented object records; omit BOTH
                                                 for legacy single cells. Existing rotations remain inert without
                                                 dimensions. One HP/AC record and zone covers every occupied cell;
                                                 destruction frees them together. Dimensioned objects' explicit component.cover='half'
                                                 or 'three_quarters' uses existing wall cover/height on every cell;
                                                 absence preserves old walls. This does not enable placement/art or
                                                 loose-object movement: those consumers must validate full extents.
  forced_movement_collision(ctx, target, blocked_at, untraveled_ft) -> None:
                                                 after an opted-in forced route hits an actual obstruction; providers
                                                 resolve their own collisions. A pull's own caster is not an obstruction
                                                 (the route ends there), so it is not reported. Default-inert without
                                                 opt-in or provider.
  movement_source_requested(engine, mover, source_id) -> bool | None:
                                                 request the forced movement source in its receipt; None is inert.
  object_damage_modifiers(engine, actor, obj, packets, source) -> None or dict:
                                                 per-instance offensive permissions: ignore_threshold (bool),
                                                 multiplier (int; highest applies), ignore_resistance_types (type list;
                                                 union). Default inert. Never alters saved object defenses.
                                                 Used by integrated Refined/Heavenly Fist weapon providers;
                                                 suitable for other weapon/technique object-damage permissions.
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
                                                 door_interaction uses this with object_targets/additional_actions for
                                                 explicit simple doors only; no door means no offered candidate.
                                                 door_state.change_door is shared with Thread the Object and syncs
                                                 blockers after OBJECT_UPDATED. Ordinary free interaction claims
                                                 ONCE_PER_TURN_CLAIMED scope system:object_interaction (integer turn counter),
                                                 shared with weapon grabs via combat.object_interaction, then offers
                                                 Utilize. player_only leaves built-in AI unchanged.
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
  attack_sequence_strike(ctx, effect, target, index, count) -> [selection]|None, once per actual strike
                                                 boundary in a typed attack sequence, before that strike's
                                                 roll. Context.attack_sequence_id is the activation-local
                                                 sequence number; it is never persisted and never supplied by
                                                 an intent. One answer of {target_id, additional_attack,
                                                 additional_strikes} replaces this strike's recipient; the owner
                                                 must resolve the choice at that boundary and may add strikes only
                                                 to a non-granted, unlocked sequence. None keeps the declared
                                                 target and no answer means no extra prompt, state or roll.
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
  owner_damage_type_choice(ctx, effect, kinds, targets) -> one of ``kinds`` or None; called for a passive on-hit damage
                                                 row that prints "chosen for that hit" (``owner_chooses_type``, more than one
                                                 type, no resolved or inherited type yet). Default-inert: None keeps the
                                                 executor's automatic best-landing pick. Implemented once in
                                                 combat/ext/owner_damage_type.py, which asks the owning player on their turn
                                                 through the shared needle choice. A value outside ``kinds`` raises.
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
                                                 CHECK_ROLLED.check_metadata.opponent_display_name optionally
                                                 supplies an anonymous opponent label for history text. Mechanical
                                                 actor/target IDs and raw provenance remain unchanged. Absent = inert.
                                                 Table dice include recorded CHECK_ROLLED actor/target roll IDs;
                                                 the same opponent label applies to the defending die. No roll is
                                                 generated by presentation and unannotated dice retain actor names.
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
  after_hit_choice(ctx, target, kind)         -> None, transactional typed-hit damage producers. Their typed saves
                                                 and after-damage tails share s188_hit_settlement's continuation;
                                                 after_hit follows the last save-independent packet. run_strict
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
  # Typed modifier rows may opt into source_owned=True: _modifier passes the
  # Context actor as _add_modifier's explicit source_actor_id. Named off-turn
  # speed/AC/defense effects then attribute their event and source-turn expiry
  # to their actual user. Omitted/False retains current-turn ownership; no new
  # saved field or hook is added. This general seam is available to every
  # modifier effect, independent of ability identity.
  # refresh_across_owners=True independently opts into refreshing prior ADD
  # modifiers of the same ability/field from any applier. source_owned still
  # retains the latest actual user and source-turn expiry. Used by Eroding
  # Dust's printed nonstacking penalty; available to any nonstacking modifier.
  # Omission preserves independent source-owned modifiers and current expiry.
  # Modifier refresh keys also include Context.source: distinct named effects
  # sharing one activation/cache each refresh only their own prior modifiers.
  damage_packet_selection(ctx, target, packet_kinds) -> None, strict transactional callback on a confirmed typed
                                                 hit BEFORE its first damage packet rolls/commits. packet_kinds is
                                                 a tuple of available delivery names ("weapon", "technique");
                                                 ctx.damage_packet_kind identifies the primary delivery. Attached
                                                 on-hit damage reports "technique" through damage_dealt. ctx retains
                                                 hit provenance and attack_defense_spec for delivery defenses. A confirmed-hit
                                                 damage-roll bonus may replace attack_defense_spec["damage"] with
                                                 a copied DiceSpec whose modifier contains that bonus; it must not
                                                 change targeting, attack count, or fixed_damage. Construction or
                                                 a miss does not enter this callback.
                                                 Subscribers may ask the owning player which packet receives a named
                                                 rider and keep that choice in the resolution-local damage_cache.
                                                 No handlers means no choices, events, rolls or behavior changes.
                                                 Pauses propagate for session rollback/re-execution; nested strikes
                                                 own their contexts. General resolver spec callback
                                                 before_attack_damage(engine, actor, target, spec, AttackDamage)
                                                 bridges this hook across the native primary damage commit boundary.
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
  effect_execution_allowed(ctx, effect)       -> False to skip this typed effect while it executes, after effect_allowed
                                                 and before its once-use gate. Execution-only: may roll and write events;
                                                 offer construction never calls it. None means no veto.
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
  self_gated_effect(ctx, effect)             -> True when this typed row closes its own turn or round use clock
                                                 (modifier_once) when its effect lands, so typed_executor._run_effects_in_chain must
                                                 not charge that clock when the row runs; None (or no provider) keeps the ordinary
                                                 up-front charge. For a row whose effect can land later or not at all: Daemonic
                                                 Augment's Mark Creature places its mark on the creature the trigger damages and
                                                 places nothing when the trigger deals no damage, so it spends the same
                                                 effect_eligibility.modifier_gate itself in that moment, which keeps every other
                                                 option of the same modifier closed for the rest of the turn. Pure strict query;
                                                 errors propagate; default inert, so a row without a provider is charged as before.
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
  hit_settled(ctx, target, kind)             -> None, strict confirmed-hit checkpoint after all attached hit packets
                                                 and attack_damage_final callbacks, before completion reactions/new attacks.
                                                 Like hit_final, ctx.hit_snapshots carries copied pure hit-time receipts;
                                                 ctx.attack_damage_context carries confirmed attack provenance, both restored
                                                 in finally. Unlike legacy hit_final, this phase follows late typed on_hit
                                                 effects and bonuses. It also runs for terminal hits inside the guarded
                                                 final-rider scope. Generate Pack Echo uses it so late attached packets
                                                 cannot spend the Echo they are still generating; other post-packet
                                                 generators/effects can reuse it. No subscribers means no behavior change.
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
  save_roll_tags(ctx, subject, ability, pending_named) -> list/tuple/set/frozenset of strings or None.
                                                 Pure opt-in metadata for the native d20 context of typed block saves
                                                 and defending contests. Each returned tag must already exist in
                                                 pending_named (a frozenset of established pending consequences).
                                                 Strict inside typed_save_modifiers; invalid tags fail the transaction.
                                                 Adds no rolls, modifiers or outcomes. No reply keeps historical
                                                 condition-only metadata. Metal Hard-Meridian Breathing carries
                                                 forced_movement for its newly compiled STR/CON owner only.
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
  healing_roll_bonus(ctx, effect)             -> int or None, a flat addition to this typed healing roll, before
                                                 reductions, caps and recorded healing. Runs once per actual roll,
                                                 not per recipient. Providers may use ctx.damage_cache for printed
                                                 once-per-activation limits; nested outcomes share that cache.
                                                 No providers means zero, preserving legacy rolls and saved fights.
                                                 For any owned benefit that adds a flat amount to a healing roll.
  temp_hp_grant_bonus(ctx, effect, subject, amount) -> int or None, a flat addition to this original typed
                                                 Temporary HP grant, before the single healing_pending interception
                                                 in _grant_temp_hp. Runs once per eligible recipient, after the amount
                                                 is rolled and before the grant is recorded. Providers own their
                                                 eligibility, choice, and payment; no provider means the original
                                                 amount is unchanged. Do not re-submit the committed grant.
  attack_bonus(ctx, actor)                    -> int or None, a flat modifier added to the attacker's own attack roll
                                                 before it is rolled (forged-worker 2026-09-29: Exhaustion's -1 per
                                                 level -- attack_mode only offers Advantage/Disadvantage, no flat number)
                                                 During typed strikes, trigger_occurrence.current_strike(engine)
                                                 exposes actor, actual target and namespaced transient scratch through
                                                 the roll and all follow-ups. Nested strikes restore the parent;
                                                 exceptions/pauses clear the frame. No events or saved state changes.
                                                 Default inert unless a provider reads/writes this scratch frame.
  scene_check_relevant(engine, actor, purpose) -> True | None.
                                                 Opt a compiled scene check into the live action menu for this
                                                 actor/purpose through owned ability, active zone/condition or
                                                 authoritative scene context. No matching provider means hidden
                                                 for every seat. scoped_checks consults this on each candidate
                                                 enumeration, so nonowners can gain access when a zone starts.
                                                 This grants no check bonus or scene facts. Sound opts quiet_movement
                                                 in for Dampen owners or a live dampened scene; its normal geometry
                                                 still decides the rolled mode. Constraints and DC are external
                                                 GM adjudications, journaled before any dice even on AI turns.
  ability_check_mode(engine, actor, ability, skill, against) -> "ADVANTAGE" | "DISADVANTAGE" | None.
                                                 check_context.current(engine, actor) exposes explicitly supplied
                                                 source_actor_id/source_position, observer_id, senses, purpose,
                                                 issues and ordinary. scoped_checks.scene_movement_check is a
                                                 compiled free scene-check caller: journaled sound-only/mixed
                                                 constraints plus an explicitly entered GM DC. It grants no Hide,
                                                 movement or invented difficulty. check_modes(metadata=...) scopes these only
                                                 while querying the hook; absent metadata is inert. No facts are
                                                 inferred. Opposed check specs and skill_check rows accept metadata;
                                                 needle.ask(..., gm_adjudication=True) marks an external GM fact
                                                 that neither local nor model AI may invent. The owning action
                                                 opts into preview with typed.gm_adjudication=True. Table previews
                                                 pause at this choice even on automatic turns, before dice/costs;
                                                 supplied validated answers resume and commit through the journal.
                                                 Other AI choices stay automatic; absent markers are inert.
                                                 their CHECK_ROLLED receipt preserves it, and skill_check_mode sees
                                                 ctx.check_metadata. The skill_check row may supply an explicit dc.
                                                 Called by check_modes/check_mode with engine and against_creature;
                                                 modes combine with native conditions and cancel normally. Default-inert.
                                                 Single-target Analyze, opposed Sleight of Hand and source-owned skill_check
                                                 provide provenance; missing/multi-target provenance never guesses a target.
  skill_check_mode(ctx, subject, ability, skill) -> "ADVANTAGE" | "DISADVANTAGE" | None.
                                                 Uses the same explicit check metadata and normal mode cancellation.
                                                 Default inert when no provider matches the subject and context.
  check_success_allowed(ctx, subject, spec, roll) -> False | None.
                                                 After a completed ability/skill check, forbid its success only
                                                 for an explicit source/observer/check context. An opposed defender
                                                 forbidden from benefiting supplies no successful resistance; an
                                                 actor forbidden from benefiting cannot win. Dice and receipts stay
                                                 real. Default inert. No automatic creature reveal or sight grants.
                                                 Sound's unseen-source contests use anonymous journal tokens only
                                                 after that listener heard the source. Voice evidence lasts through
                                                 the listener's next turn and requires a living, unsilenced source
                                                 still in range on an audible path. Clues describe recent evidence,
                                                 never assert that a past voice is continuously sounding.
                                                 Sound movement clues use journaled ROUND_STARTED provenance:
                                                 current/previous round only; unknown age is not recent evidence.
                                                 save_context.damage_geometry(engine,target_id,source_id,source_actor_id)
                                                 separately exposes source, recipient and full 3D delivery cells
                                                 to final_damage consumers. Exact scoped packets/confirmed attacks
                                                 only; unknown or unrelated nested deliveries return None. No saved
                                                 geometry or global damage changes. Source-zone defenses are inert
                                                 unless every required cell lies inside their live owned zone.
                                                 AREA/TRAP delivery frames instead carry source_zone_id for the
                                                 exact live emitter/mechanism, never the creator's body. Shared
                                                 spatial_areas.zone_volume_inside streams that region's native
                                                 columns/height/clipping; unbounded/unknown regions cannot prove
                                                 complete containment. This query does not persist a zone object.
                                                 zone_contains_cells delegates to positions_inside_zone so actor,
                                                 attack-path and whole-delivery queries share suppressed columns
                                                 and full suppression, without expanding saved footprints.
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
  activation_prepare(action, engine, actor, candidate, intent) -> ActionDefinition | None
                                                 strict sequential transform before pre-payment interceptions.
                                                 Choice providers may pause; the returned action must be an
                                                 activation-local copy. Never mutate sealed catalogs.
                                                 Foreground, generic and source-native reaction callers all
                                                 share this declaration seam. Without an owned consumer the
                                                 original action is used unchanged.
  technique_resolution_enabled(ctx)          -> True | None, opt an owned context into completion notifications.
                                                 Default inert; no True answer queues no context or changes timing.
  technique_resolved(ctx, receipt)            -> None, strict successful-completion notification at the accepted
                                                 activation boundary, after all its effects, attached riders, final
                                                 callbacks and late falls, before a later independent activation.
                                                 Multi-phase native_reaction(..., settle_on_exit=False) contexts
                                                 retain capture() beside their deferred effect and finish under
                                                 paid_relocation.completion_scope after the final event phase;
                                                 successful transaction settlement remains their fallback.
                                                 Unframed contexts use transaction settlement. typed_executor,
                                                 objects and generic reactions call
                                                 paid_relocation.technique_completed only on their normal
                                                 completion path. Canceled/countered/start-vetoed or exceptional
                                                 contexts never enqueue. receipt is the actual immutable
                                                 ActivationView: actor_id/source_id, payments, refunds and
                                                 net_payments. Refunds are attributed by cost source, never
                                                 inferred from an unrelated resource gain. Consumers opt into
                                                 activation_accounting and check their own ownership/eligibility.
                                                 No consumer means no event/state change. Contexts and receipts
                                                 are transient; durable consequences use ordinary evented state.
  activation_end(engine, actor, action, candidate, intent) -> None, at the end of an accepted foreground typed Action or
                                                 Bonus Action, including declaration cancellation, a technique countered after
                                                 declaration, a start veto, and an exception. This runs in a finally scope
                                                 before the next intent can reuse the engine. Subscribers may discard
                                                 transient activation-local state; durable consequences still belong in
                                                 ordinary evented state. Nested follow-ups and typed reactions are
                                                 outside this hook; they must own their transient lifecycle separately.
  technique_used(ctx)                         -> None, after a typed action's effects ran
                                                 A subscriber whose printed trigger names what the effect
                                                 did to every creature it touched reads the journal window
                                                 that begins at ctx.technique_event_start (the index
                                                 where this use's own effects begin, nested hit and save
                                                 rows included) and set on the resolution Context before
                                                 the effects ran. The index is Context-local, absent from
                                                 the engine, and discarded when resolution returns. One use
                                                 that damaged several creatures publishes one
                                                 DAMAGE_COMMITTED packet per creature, so a subscriber must
                                                 read that whole window rather than treat the first packet as
                                                 the effect's only recipient. The index is
                                                 resolution-local, is absent outside its Context, and changes
                                                 nothing when nobody subscribes.
                                                 Builders may set parameters['setting_only'] = True only for free
                                                 self actions storing a future selection or showing rules, with no
                                                 immediate gameplay activity.
                                                 Unflagged saved actions keep ordinary hooks and reaction windows.
                                                 Setting-only selectors (setting_choices.is_setting_action) never
                                                 call technique_start, technique_used or action_completed. Their
                                                 INTENT_ACCEPTED bookkeeping also skips event hooks; setting
                                                 condition events still run normally. Other actions are unchanged.
  technique_object_modifiers(ctx, obj, row)   -> "bypass", "double", or None, once per struck object.
                                                 combat/ext/objects.py calls it for each object a technique damage row
                                                 strikes: ctx is the technique Context, obj the struck object, row its
                                                 damage row. Answers come from run() in its returned order; the first
                                                 truthy answer is applied. "bypass" ignores ordinary Resistance to that
                                                 row's Bludgeoning damage; "double" doubles that object's damage once.
                                                 Default inert: no answer, or None, changes nothing. A provider that
                                                 needs the GM asks through needle.ask with gm_adjudication=True,
                                                 allow_decline=True and default='decline', so an unanswered or AI seat
                                                 declines. A hook that raises is skipped by run(). Water's Scouring
                                                 Erosion (combat/ext/water_erosion.py) is the reference provider.
  attack_damage_bonus(ctx, target, effect)    -> int or None, added to each typed attack's damage modifier immediately
                                                 before damage against the confirmed recipient (also to fixed damage); dice are not multiplied.
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
  retained_instance_updated(engine, holder, kind, key, item) -> None, after a retained condition or modifier
                                                 snapshot is recorded; default inert. kind identifies the instance type,
                                                 key its identity, and item the updated instance. Dust reconciles its
                                                 owned Primordial Dust form without treating the update as a new activation.
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
                                                 Initial gear uses starting_loadout's sealed legal selection; spare
                                                 inventory is stowed. equipment_grip Draw/Stow effects update
                                                 ActorState.equipment_readiness (weapon id -> 0 stowed, 1 drawn,
                                                 or an explicit hand name) through EQUIPMENT_READINESS_SET:
                                                 actor_id identifies the owner; payload.readiness is the complete
                                                 replacement map, payload.log the single readable history line.
                                                 No per-item readiness conditions are created. Drawing/stowing has
                                                 no Action cost. Dropping never auto-draws a spare.
                                                 Managed weapon grips opt in with Draw/Stow actions or
                                                 equipment_hands_model=1 on the compiled acquisition
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
  carry_capacity_multiplier(engine, actor)   -> positive int | None, read by carry.capacity_lb when the load is weighed
                                                 (Speed and Items panel). Largest answer wins; no answer or None keeps
                                                 the sealed capacity. Pure query: it reads a persisted state condition and
                                                 the bundle, so save, reload and replay see the same capacity.
  turn_start(engine, actor), turn_end(engine, actor) -> None, observational turn events. Start-turn choices and zone
                                                 effects have not yet resolved at turn_start; companion following
                                                 belongs in uncommanded_summon_turn, after those effects.
  turn_end_settled(engine, actor) -> None, observational, once per ending actor after the turn_end dispatch and
                                                 native end-of-turn upkeep (stances.on_turn_ended, which may harm and
                                                 stamp reveals). Use it for effects that must settle after native aftermath.
                                                 Vanishing Technique restores Invisible here.
  action_completed(engine, actor, economy, source_definition_id) -> None, after an Action/Bonus Action resolves;
                                                 covers legacy attacks negated after their attack roll. No registered
                                                 hook or no owned stored condition leaves behavior unchanged.
  reaction_completed(engine, actor, source_definition_id) -> None. Strict completion checkpoint delivered once,
                                                 after a Reaction's numeric result and its outcome riders have
                                                 resolved, never at its payment. Native receipts come from the
                                                 REACTION_RESOLVED state event (combat/state_events.py dispatch, for
                                                 generic, typed and native reactions); d20 reaction rerolls dispatch it
                                                 from combat/ext/d20_rewrite.py after their finalized reroll and riders.
                                                 source_definition_id may be a bare printed record id with no
                                                 action-catalog entry, so a consumer classifies it from typed
                                                 authority instead of action data. Return values are ignored;
                                                 run_checkpoint makes a provider's choice pause or exception roll back
                                                 the enclosing transaction, and with no subscribers the resolution and
                                                 fight state are unchanged. Default-inert.
  turn_start_choice(engine, actor)            -> None, transactional turn-boundary decisions, before zone/start-turn
                                                 reactions (typed_reactions.on_turn_start). Unlike observational
                                                 turn_start hooks, choice-provider pauses/errors propagate through
                                                 the transaction and preview. Use for expiry costs or start-turn
                                                 benefit choices; absent registrations are inert. No implicit
                                                 choice or Reaction cost. Hooks own eligibility and saved state.
  option_composition(action)                  -> {key: list, mode: select|toggle|clear, family: source id,
                                                 optional costs/cost_label, attacks: any|melee|unarmed} or None.
                                                 attacks nests hit preferences under compatible attack Options
                                                 (option_composition.nest_attack_choices); family may be absent
                                                 for preferences shared by multiple attacks. Explicit approval of a
                                                 sealed storage-only setting for local table drafts. Default
                                                 inert; no costs, combat effects or reaction prompts. Independent
                                                 keys compose; selects replace their key, toggles use parity.
                                                 OPTION_COMPOSITION_V1 records the exact ordered sources once
                                                 under an immutable state version; retries never repeat toggles.
                                                 Gate4.action_candidates_for_sources(sources) projects only
                                                 the chosen abilities using the normal native legality/vetoes,
                                                 with no moves, ranking or state/fog projection.
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
                                                 answers only a Charged or Conductive one). Sky-Treading's
                                                 Pursuit Without Horizon uses this to require a visible hostile
                                                 before its native completed-movement/teleport reaction can fire.
  ally_row_allowed(engine, reactor, subject, row) -> False to keep one generic ally reaction row (ally_hit, ally_damaged, ...)
                                                 from answering this ally of the reactor (combat/typed_reactions._ally_row_ok;
                                                 placed-effects 2026-09-29: Flower of False Death answers an ally that carries
                                                 the reactor's Blossom -- reaction_subject_allowed only sees the attacker there)
  native_reaction_roll_mode(engine, context) -> "ADVANTAGE" | "DISADVANTAGE" | None, before a native accepted
                                                 reaction attack's own d20. Context names actor_id, target_id,
                                                 source_id/reaction_source_id, economy="REACTION", kind="attack".
                                                 No answer leaves the existing mode unchanged; opposing modes cancel.
                                                 Roll-reason attribution (2026-10-16): a reply may be an attributed
                                                 dict {"mode": ..., "effect": name, "why": plain reason,
                                                 optional "owner"} so the displayed reasons name the ability; a
                                                 bare string keeps the shared generic "Triggered reaction" label,
                                                 so a native-reaction-only cancellation still explains itself.
                                                 Runs only inside native_reactions.attack_scope, after payment and
                                                 publish_reaction_used, for the matching attacker/source. Parent
                                                 scopes and penalty frames restore on completion or Ask-me pause.
                                                 d20_context exposes the same Reaction identity to rewrite hooks.
  reaction_roll_mode(ctx)                     -> "ADVANTAGE" | "DISADVANTAGE" | None, before the reactor's own d20 in a
                                                 reaction that is not an attack -- a contest or a chance roll
                                                 (typed_executor._reaction_roll_mode); attack_mode covers its attacks
  collision(ctx, target, blocked_at, remaining_ft) -> None, after a push or a pull stops short of the distance
                                                 asked for (typed_executor._push; a pull that stops against its own
                                                 caster's footprint is not reported); blocked_at is the Position it
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
                                                 Chains prisons and script seals use this same resolution-only gate for
                                                 their recorded Charisma saves. New owned chains_spatial_lock conditions
                                                 carry DC, round usage and expiry; no such condition means no change.
  teleport_steps.destination_allowed(..., check_candidate=True) retains the action-specific landing
              policy in picker and candidate gates; the candidate hook passes check_candidate=False
              to avoid re-entering itself, not to discard the action. Default behavior is unchanged.
  teleport_landing_allowed(engine, actor, cell, feet, action) -> True | False | None
                                                 is a pure destination query inside combat/ext/teleport_steps.
                                                 landing_allowed (also used by destination_allowed), and Gate4's
                                                 historical candidate enumeration, call it after reach and occupancy
                                                 (which a provider cannot override). AI and picker queries retain action.
                                                 True admits a cell the shared line-of-sight rule would reject
                                                 (an ability's printed "visible or precisely known" rule owns the
                                                 perception question); False refuses one the shared rule would accept
                                                 (a printed crossing prohibition). None preserves shared sight,
                                                 blindness, hidden and area rules unchanged. Providers gate ownership
                                                 themselves; the question never mutates state or asks a choice.
  teleport_landing_recovery(ctx, actor, start, destination) -> Position | None
                                                 answers only when a chosen teleport destination is now occupied or
                                                 illegal after payment (typed_executor.teleport_subject). A provider
                                                 may return the printed replacement landing (Void Step: the nearest
                                                 legal unoccupied space on the destination side). The core revalidates
                                                 the answer's placement and otherwise keeps the historical stay-put
                                                 result. Default-inert; providers gate their own ability's ownership.
  hit_response(engine, attacker, target, spec, total, natural, effective_ac) -> (new_effective_ac, False) to turn a hit into a
                                                 miss, or None; called for a typed target once the roll is a hit
                                                 (typed_reactions.on_attack_hit; sys-resources-states 2026-09-29: Brace
                                                 the Line's "would miss after adding +2 to the ally's AC"), first hook to
                                                 answer wins
                                                 spec.source_definition_id identifies this resolving attack, including
                                                 nested reactions; it is independent of the foreground ActionIntent.
                                                 technique_interception.frame(engine, attacker.entity_id, source).action
                                                 retains its declared ActionDefinition, including triggered actions absent
                                                 from the catalog. Without that frame, query the catalog by the spec source.
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
  defense_description(engine, target)         -> None, or a list of plain rows for the Defences card (typed_reactions.defense_display);
                                                 pure, default-inert. Each row is {"damage_types": [...]} (Resistance) or {"conditions": [...]}
                                                 (condition immunity), with "source" (display name), "expires_on" (the engine lifetime
                                                 token, or None for one that lasts until removed; the card words it) and "note" (printed
                                                 qualifier such as "only against nonmagical attacks"). Describes a benefit that needs
                                                 no attack to exist (a conditional Resistance, a standing condition immunity) without
                                                 calling condition_immune or damage_defenses, which can spend a response or need a packet.
                                                 Never changes resolution; the card only reads it.
  generic_reaction_costs(engine, reactor, other, row, costs) -> replacement list of {resource_id, amount}, or None.
                                                 Pure pricing of owned generic reactions before affordability, consent
                                                 and payment; the same fresh row carries the price through all three.
                                                 Preserve paying pools and leave compiled rows untouched. ``other`` is
                                                 the attacker for missed/natural_1/ally_missed, None at other checkpoints
                                                 until a caller supplies its triggering creature. No hook/None = original
                                                 cost; return early for unrelated rows or missing trigger context.
  generic_reaction_payment(engine, reactor, row, costs) -> replacement costs or None.
                                                 Called only after an optional generic reaction is accepted and
                                                 immediately before payment. Use for a player-owned payment choice;
                                                 keep automatic actors deterministic and never mutate compiled rows.
  compile_block(block, spec, row, numbers)    -> list of rows for the bundle's typed_passives, or None (not this block)
                                                 numbers carries the compilation's own resolved numbers: pb, key_mod, cl,
                                                 armor, shield, and ``record`` -- this feature's typed record from the
                                                 same authority the compiler was given (compile_character's
                                                 typed_authority). A plug-in that prints its own numbers in reviewed
                                                 data reads them from ``record``, so an injected or revised authority
                                                 compiles its own numbers rather than rereading the file on disk.
                                                 Default-inert: ignoring the key compiles exactly as before.
  compile_weapon_traits(info)                 -> dict of typed weapon traits to merge, or None; info contains owned_ids,
                                                 weapon profile and current typed action, actor_id and action_id. The latter
                                                 is the current variant ID; weapon.held_from binds borrowed copies
                                                 to their original source. Ability owners qualify their
                                                 own weapon family. Default inert; no registrations means no changes.
                                                 Optional inventory_key binds a physical item to the base action and
                                                 its variants, including refined/given copies. Absent retains legacy mapping.
                                                 Thrown equipment uses existing dropped_at/disables_action/held_by
                                                 conditions; Returning Inscription checks active zone rule.no_teleport
                                                 or rule.no_extradimensional_movement at the landed item's cell.
                                                 Printed returning actions may retain one launched copy across targets
                                                 and recover it at technique_used, subject to clear-path/possession gates.
  empty_action_implemented(action, info)        -> True only if the owning plug-in implements this otherwise empty
                                                 TYPED action, else None. Pure publication query, after compile_action
                                                 transforms; info: owner_sheet, owned_ids, mechanics, actor_id. Default inert:
                                                 without a claim, effects, a zone, or reviewed GM rules, no menu action
                                                 is published. Providers must check ownership and the exact action;
                                                 implementing a separate replacement action does not claim a placeholder.
  compile_shield_bonus(bonus, info)           -> nonnegative int. Transform the bonus of one carried Shield before
                                                 AC and shield_ac receipts are sealed. info: owner_sheet, owned_ids,
                                                 kit, owner_items. Default: the existing equipment bonus. The sheet
                                                 and compiler both call it; readers do not infer training from gear.
  compile_actions(info)                       -> list of ActionDefinition to add (info: owner_sheet, spheres, owned_ids,
                                                 mechanics, passives, numbers, short, actor_id, pb, mods, save_proficiencies, primary,
                                                 pools (available Path pool names), actions (original catalog), weapon_kinds).

                                                 mechanics, passives, numbers, short, actor_id, pb, mods, primary,
                                                 pools (available Path pool names), actions (original catalog), weapon_kinds,
                                                 kit and owner_items (canonical equipped gear after loadout/attunement).
                                                 Publishing a custom row here claims its implementation, including
                                                 object hooks and automatic ownership markers with empty typed effects.
                                                 The compiler retains these rows separately from unsupported generic
                                                 placeholders. Only publish owned actions that this plug-in resolves.
                                                 compile_basic_actions and maneuvers use the same publication contract.
                                                 An explicit NONE economy from these owned action builders declares
                                                 a printed free activation; the compiler seals free_primary=True.
                                                 Use setting_only=True for storage-only parent/sheet choices.
                                                 A voluntary Reaction declaration may also use NONE: its
                                                 plug-in must validate Reaction availability, spend_reaction
                                                 after consent, and publish_reaction_used before its effect
                                                 (Field Repair and Flexible Cover use this declaration route).
                                                 Generic economy-NONE option/effect rows are not primary intents.
                                                 Gate2 validates free_primary or setting_only independently of costs;
                                                 riders still resolve only through their parent/trigger handlers.

                                                 save_proficiencies is an explicit canonical ability-ID list from
                                                 owner_sheet.ability_scores_and_statistics.saving_throw_proficiencies.
                                                 Missing/None declares no proficiency (owner Path baseline). Never infer
                                                 proficiency from final numeric saving_throws; other bonuses/penalties
                                                 remain in those totals. Plug-ins may seal this list in passive data.
                                                 This contract describes recorded sheet proficiency, not transient grants.
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
                                                 owned_ids (exact learned/base mechanic IDs), spheres (owned sphere IDs),
                                                 attack_count (shared Attack action count), attack_profiles (weapon and
                                                 unarmed: on_hit passive effects and expected_extra_damage per Action).
                                                 Reusable for missing basic attack options; copy supplied effects before
                                                 editing. Return [] unless this creature needs the option. No registrations
                                                 or no additions leaves the catalog unchanged; saved catalogs are untouched.
                                                 basic_unarmed.strike_payload builds one shared damaging Unarmed Strike
                                                 packet; callers supply the count and compiled on-hit riders. Athletics
                                                 uses it for Capoeira's one Bonus Action strike. It grants no economy.
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
  compiled_rider_utility(action) -> int | None. Pure strict compiler hint for an executable extension rider.
                                                 Asked after action transforms and generic estimation. Hints must be
                                                 integers in 0..rider_value.MAX_RIDER_UTILITY (16); greatest generic or
                                                 extension value wins. Disabled/manual/setting-only actions never ask.
                                                 Does not change damage estimates, target legality or execution. No
                                                 providers preserves existing compilation. Providers gate on their
                                                 sealed executable schema and value one recipient/opportunity, never
                                                 duration, damage, or merely a rule name. Dark Meld's reviewed runtime
                                                 rows use this for sight/ward grants and Blindfold's failed-save band.
  compile_action(action, info)                -> replacement ActionDefinition or None. Runs after basic actions exist;
                                                 replacements compose in registration order, each sees its predecessor.
                                                 info: owner_sheet, owned_ids, numbers, mods, pb, carrying, mechanics, passives
                                                 (the supplied typed-authority records). Native per-feature owning-Path
                                                 authority is sealed as typed.numbers.source_cl before these transforms
                                                 derive zones/profiles; numbers.cl remains total character level. Without
                                                 source_cl_by_feature the compiler and hooks are unchanged. The passives
                                                 rows (resolved native passive rows, including natural-weapon ownership)
                                                 let source seals distinguish owned natural weapons from display names;
                                                 other source-aware plug-ins may reuse the same provenance. Never mutate
                                                 inputs. Default inert: no replacement preserves the original action.
                                                 Shared by weapon-stat and armor-check plug-ins; ability choices remain
                                                 owned by their plug-in or typed data, never compiler id branches.
  Ownership-only compile_passives receipts may set ownership_only=true. The
  sheet hides those internal markers from its automated-abilities list; ordinary
  passive rows keep their historical display. No combat behavior is suppressed.
  A routing row a seat still needs (choice_owner, so its printed menu is asked) is
  bookkeeping data and sets ownership_only too, or the internal id reaches the sheet.
  Plug-in-owned ground a rider can name as a condition ("sand", "current") is answered
  through the zone-kind registry (ext.zone_kinds): the owning plug-in registers a pure
  (engine, owner, zone) -> bool predicate, and no plug-in imports another's rules.
  compile_bundle may opt into actor_numbers (an integer-valued copy of info.numbers).
  Shared actor-number/DC readers prefer this actor-wide provenance over legacy
  first-action inference; per-talent numbers never replace global casting stats.
  Absent actor_numbers preserves historical inference, including old bundles.
  named_save_dc(engine, actor, sphere_id)     -> int | None. Pure named-sphere DC query in
                                                 combat/save_dcs.py; only an owned feature may answer.
                                                 None preserves the ordinary DC; never changes global
                                                 Save DCs or Cultivation DCs. Used by Body Refining
                                                 versions and available to any sphere-specific key rule.
  compile_reaction(row, info)                 -> replacement typed_reactions row (a plain dict) or None. Runs after a
                                                 generic Reaction row is compiled (a Reaction whose economy the
                                                 sealed engine runs itself, combat/factory_compiler.py
                                                 _generic_reaction), before the reaction plan claims it.
                                                 info: owner_sheet, owned_ids, numbers (the character's compiled
                                                 numbers), mechanic_id (the row's feature_id) and mechanic (the
                                                 typed-authority record). The row is the compiled dict itself;
                                                 returning a new dict (or a copy with its own ``numbers``) reseals
                                                 it -- a re-key that gives the row its own numbers copy never
                                                 reaches the character's other talents. Default inert: no
                                                 replacement preserves the row exactly as it compiled. A plug-in
                                                 that keys a whole talent family differently (Battle Musician's
                                                 Cadence talents read Constitution, combat/ext/battle_musician.py)
                                                 answers here; it never reaches into another plug-in's rows.
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
  armament_movement_allowed(engine, owner) -> False to forbid any Domain Armament relocation for that owner; None/True leaves it available. The shared qi_path movement adapter and its destination builder both honor this default-inert permission.
  candidate_allowed(engine, actor, candidate, action) -> False to leave that choice out of what the fighter is offered now
    Both generation passes honor it: an engine class whose applies_plugin_candidate_vetoes flag is True applies it in
    its base candidate pass (gate2_engine), and a subclass that applies it in its own pass with availability journaling
    sets the flag False so the base pass does not veto twice (gate4_engine). The flag decides only WHERE the shared
    contract runs, never a different behaviour for one engine.
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
  attack_target_interception(engine, attacker, target, source_id, intent, index) -> dict | None.
                                                 Strict, default-inert checkpoint before the d20; None leaves the original attack intact.
                                                 Receipt keys: source_id, recipient_object_id, condition_instance_id.
                                                 Providers enforce ownership and perception; see the detailed contract below.
  shared_space(engine, left, right) -> True | None. Pure default-inert query; None retains pair collision.
  pass_through_stop(engine, mover, occupant) -> True | None. Pure default-inert query; None forbids occupied stops.
  cover_miss_recipient(engine, attacker, target, spec, roll, intent, total, cover) -> actor id | None.
                                                 Pure default-inert query: None retains a cover-caused miss and never
                                                 redirects twice; the provider owns the recipient's eligibility.
  stealth_search_mode(engine, searcher, hidden_foe) -> "ADVANTAGE" | "DISADVANTAGE" | None, before a Search action's
                                                 Perception check against one hidden creature (combat/stealth.py
                                                 search(); eye 2026-09-28: Stealth Surge)
                                                 stealth.search_modes collects native, Search and target contributions
                                                 unresolved. Sweep reuses one dice pair: NORMAL takes the first die,
                                                 Advantage the higher, Disadvantage the lower; no target rerolls.
  hide_check_override(engine, actor)          -> int check total to use instead of rolling for a Hide action, or None
                                                 (combat/stealth.py hide(); eye 2026-09-28: Cooperative Stealth)
  sense_rows(engine, actor, rows) -> list[dict] | None. Pure, strict transform of live sense grants before merging.
  Return a fresh list; never mutate incoming rows. Providers run in registration order; None retains rows.
  sense_range_divisor(engine, actor, sense) -> positive int | None. Pure, strict reduction after additive ranges;
  greatest divisor wins (same range-halving source does not stack). No providers retains the ordinary range.
  Dark Meld grants use these seams for recipient Darkvision and Blindfold's sense reduction.
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
  source_damage_reduction(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int or None,
                                                 points removed from the original source packet before transfers and
                                                 recipient defenses. Results sum and clamp at zero. Default-inert;
                                                 nonrecursive transferred shares skip this hook because their source
                                                 already ran. next_attack_damage binds it to the original attack roll.
  pre_defense_transfer(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int, points of
                                                 this packet a rule has moved onto another creature (and committed there
                                                 itself) before ANY of the target's own defenses, Immunity included
                                                 (typed_reactions.defend, after source_damage_reduction, before
                                                 incoming_damage). Default-inert. damage_transfer_scope.nonrecursive_transfer(engine,
                                                 recipient) binds suppression to defense evaluation of that recipient
                                                 in its parent packet; commitment uses the existing pending-damage
                                                 source_flags yielded by the helper (nonrecursive_transfer and a
                                                 depth-specific already-defended marker). Both are transient.
                                                 already_defended_packet(engine, recipient) binds the core defense
                                                 bypass to that share; unscoped legacy callers retain their behavior.
                                                 Fresh nested packets remain eligible. damage_sharing and protection
                                                 use that public helper and flag for their nonrecursive shares.
                                                 Owned by combat/ext/damage_sharing.py rows with timing "before_defenses".
                                                 Generic ally reaction admission supports allow_self_source=True for
                                                 triggers that include the reactor's own damage; absent means excluded.
  incoming_damage(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int, points of damage
                                                 to take off this packet before Resistance and flat reductions, called
                                                 when a Factory fighter takes damage (typed_reactions.defend);
                                                 the results are summed. A native mixed-type hit asks once per damage
                                                 component with that component's amount, so a rule stated for one damage
                                                 type covers that component and no other. A rule that instead states one
                                                 amount for the triggering attack registers incoming_attack_damage.
                                                 Critical cancellation uses critical_cancel.
  incoming_damage_instance(engine, target, components, source_definition_id, source_actor_id) -> mapping of
                                                 DAMAGE_TYPE to nonnegative integer reduction, or None. Runs once
                                                 with the complete eligible native mixed packet before component
                                                 defenses; reductions are applied before Resistance and flat reductions,
                                                 capped per type. Use for a stateful response whose allowance, payment,
                                                 or success test concerns one whole damage instance. Type-local rules
                                                 remain on incoming_damage. Default-inert.
  incoming_attack_damage(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> int, points of
                                                 the triggering attack to take off before Resistance and flat
                                                 reductions (typed_reactions.defend, after incoming_damage): the hook for
                                                 a rule that reduces "damage from the triggering attack" once, whatever
                                                 types the attack deals (Sovereign Shield-Soul Incarnation's Proficiency
                                                 Bonus). typed_reactions.defend_components asks it once per damage
                                                 component with that component's amount and keeps one ledger for the
                                                 whole hit, shared with the compiled "reduction_before_resistance" rows
                                                 (Berserk) because both state one amount for the triggering attack: each
                                                 spends its amount once across the components it reduces and only on
                                                 damage a component still holds, so an amount an already-emptied
                                                 component cannot use carries to the components that still take damage
                                                 instead of being lost. It is therefore neither repeated per damage type
                                                 nor capped to the first one, and stacking it with a before-Resistance
                                                 row never charges the same damage twice. A single-component packet
                                                 charges every answer in full. Default-inert.
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
                                                 ignores it, and default-inert (no handler -> every target keeps its Resistance).
                                                 keyword ordinary (default False) is True when the target has ordinary Resistance to kind in this packet
                                                 and is not Immune to kind: the decision typed_reactions._defenses makes before it asks the bypass (an Immune
                                                 target is never asked, so a bypass never pierces Immunity). Every handler accepts it; nothing is
                                                 published on the engine for it
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
  movement_opening_width(engine, actor)      -> positive integer milliinches | None
                                                 opts this actor into opening geometry. No provider returns the original grid.
                                                 The projection is local to movement, never sight, targeting or other actors.
                                                 An opening crosses the named object's full thickness in its anchor voxel;
                                                 it does not remove an overlapping wall, object, roof or cultivated field.
                                                 Default-inert; pure opt-in query that must gate actual live state.
                                                 Implemented in combat/opening_passage.py.
  transit_stop_allowed(engine, actor)        -> bool | None
                                                 defers overlap recovery to the owning provider's turn-boundary settlement.
                                                 Default movement still requires an unoccupied endpoint.
                                                 Needs at least one True and no False answer. Default-inert; pure opt-in
                                                 query that must gate actual live state. Implemented in combat/opening_passage.py.
  attack_target_interception(engine, attacker, target, source_id, intent, index)
                                             -> {source_id, recipient_object_id, condition_instance_id} | None.
                                                 Strict checkpoint before creature defender hooks and the d20; the
                                                 provider resolves successful targeting of a noncreature decoy and its
                                                 evented lifecycle. No answer leaves the attack intact. Economy is
                                                 already paid and never refunded; an intercepted strike deals no creature
                                                 roll, damage or on-hit effects. Check ownership and perception of the
                                                 actual recipient. Default-inert: no provider means no interception.
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
  escape_check_mode(engine, escaper, grips, ability, skill)
                                             -> "ADVANTAGE" | "DISADVANTAGE" | None; pure ability/skill-scoped
                                                 escape check query. escape_checks.escape_hook_modes combines it with
                                                 the unchanged unscoped escape_mode contract. Resolvers and automatic
                                                 ability/hold rankings use the same query. Explicit keyword metadata
                                                 takes precedence over effect check_ability/check_skill fields.
                                                 Unknown legacy mixed-skill checks pass None, None; scoped providers
                                                 must decline when their printed roll scope is unknown. No handlers:
                                                 no new mode. Opposing modes cancel. Never called for ordinary checks
                                                 (escape_hooks=False) or saving throws. No new saved state or choice.
  escape_save_mode(engine, escaper, grips)    -> "ADVANTAGE" | "DISADVANTAGE" | None, before a grip's printed escape save.
                                                 Conflicting hook modes cancel. None retains the original save mode;
                                                 separate from escape_mode so check-only benefits never affect saves.
  close_ranged_ok(ctx)                        -> True when a hostile creature within 5 feet does not give this typed ranged
                                                 attack Disadvantage (typed_executor._enemy_adjacent_to_ranged; rider lane C7
                                                 2026-09-30, Bow Body). No handler: the 2024 rule unchanged.
  teleport_check(engine, actor, start, destination) -> False when a self-teleport fails (typed_executor._teleport; the caller
                                                 has already paid; Formations, Sealing Gate: a Charisma save to teleport through)
  teleport_context_check(engine, actor, start, destination, movement_context) -> False to refuse that teleport in its
                                                 explicit context (WILLING or FORCED); typed_executor.teleport_subject
                                                 supplies WILLING for self use and subject_repositioning supplies FORCED.
                                                 Use this for rules keyed to the mover's intent; existing teleport_check
                                                 remains context-free for general teleport gates.
  A save branch row with before_save_damage=true runs before its outcome's damage delivery, including
                                                 successful-save half damage. The marker is stripped before ordinary
                                                 branch resolution; unmarked rows retain existing order.
  masked_conditions(engine, attacker, target) -> {entity_id: {condition instance ids}} whose Advantage/Disadvantage does not count for this
                                                 attack, merged into senses.masked_conditions (Formations: Sensing Eye, Radiance)
                                                 target_knowledge.can_see also uses these target-specific masks for
                                                 Hidden/Invisible concealment. Full concealment masking permits sight
                                                 only through the ordinary geometry query; independent obscuring
                                                 areas, cover and unmasked Hidden remain effective. No masks: unchanged.
                                                 Shared perception reads plug-in masks through plugin_condition_masks;
                                                 innate sense masks are derived afterward and may query perception.
                                                 Legacy mappings are visual by default. A mask granted by a nonvisual sense
                                                 may return {"conditions": {entity_id: {condition instance ids}}, "visual": False};
                                                 that mask still applies to combat, but sight-only presentation skips it.
                                                 Keeping these queries separate prevents recursive Hidden checks.
  presentation_hidden_conditions(engine, target) -> condition instance ids omitted from the public condition projection while
                                                 their rules state remains active (display only; no answer leaves rows visible).
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
  # AUTO138 opt-in effect contracts:
  # Reviewed target.kind="any_creature" compiles to the existing ANY_CREATURE
  # domain (allies, enemies, self). It applies to any creature-targeted ability;
  # absent metadata preserves compiler inference. Shared recipient checks still
  # enforce sight, range, Charm and ownership restrictions.
  # restraint_riders: a restrained condition row may carry action_escape:
  # {ability: "STR", name: "Scripture Prison"}. condition_state stores the
  # source's save DC and plain name, preserving defenses/repeat saves. Its
  # existing escape Action selects and removes only that source's restraint.
  # Absent metadata leaves ordinary conditions unchanged; Impaling Garden's
  # action_restraint and Scripture Prison share the escape mechanism.
  # ink_riders: ink_press_mark handles creature consent, Dexterity saves and
  # optional 1-Path-point concealment; ink_cloud quotes/pays the optional extra
  # point and creates a heavy/light zone. Both are explicit typed opt-ins.
  summon_check(engine, owner, creature, spot, was_active, source_id) -> False when summoning ``creature`` to ``spot`` fails
                                                 (summons.summon restores it and logs SUMMON_BLOCKED; Formations: Spirit-Lock, Mountain-Sealing)
  command_reachable(engine, owner, group, creature) -> False to keep ``creature`` out of one command
                                                 (summons.commandable, the list an order actually reaches; the same list
                                                 feeds summons.command, so the creature neither acts nor receives the order).
                                                 ``group`` is the command group key and ``owner`` the summoner, for a rule
                                                 that is about the order rather than the creature. Pure query, default-inert:
                                                 with no subscriber the group's own command_range_ft decides, exactly as
                                                 before.
  control_limit_extra(pool, owned_ids) -> (extra slots, groups) or None, per control pool at compile
                                                 time (summons._within_control_limits). A printed rule that raises a
                                                 control pool's limit for particular groups only answers with the extra
                                                 slots and the group keys they fit -- ``None`` as the second item means
                                                 every group. The printed limit stays what any group may use; the extra
                                                 eligible restricted slots are spent first, preserving general slots
                                                 for groups they exclude. Excluded groups never use restricted slots.
                                                 Default-inert: with no subscriber every pool gives exactly the counts it
                                                 gave before.
  command_resolved(engine, owner, group, commanded_ids, intent, economy) -> None, after a ``command_summons``
                                                  effect marks the group commanded (typed_executor.block_command_summons;
                                                  ``commanded_ids`` is the list the order reached). A printed rule that
                                                  spends one command on more than the order itself -- one commanded
                                                  creature may move before it acts -- answers here. The intent rides
                                                  along so a player-owned choice is asked, never assumed. economy is
                                                  the command action's EconomyKind (e.g. BONUS_ACTION). Default-inert:
                                                  with no subscriber a command is only the order, exactly as before.
  forced_movement_resolved(ctx, target, distance_ft, movement_kind, unwilling) -> None, after actual typed push/pull movement.
                                                  Strict dispatch permits recipient-owned choices to pause and replay; ctx carries
                                                  the action and intent. No subscribers leaves movement unchanged.
  forced_movement_committed(engine, actor, target, distance_ft, movement_kind) -> None, after a push or pull
                                                  fully resolves (typed_executor._push; ``distance_ft`` is the
                                                  distance the creature actually moved, not what was asked;
                                                  movement_kind is the string "push" or "pull").
                                                  A printed rule that answers "when you push a creature at
                                                  least N feet" reads it here. Pure receipt: listeners record
                                                  their own events; the engine changes nothing here.
                                                  Default-inert: with no subscriber the push is only the move,
                                                  exactly as before.
  zones.nonmagical_difficult_cells(engine, actor) -> map-owned difficult squares without applicable ability-created
                                                 overlap, before square exemptions. Pure shared source query;
                                                 Earth Packed Road Step may call it from difficult_exempt.
  summon_appeared(engine, owner, creature, source_id) -> None. Strict callback
      after successful placement/reset and SUMMON_APPEARED, inside the owning
      transaction. May ask owner choices and apply printed summon benefits.
      No subscribers or no explicit ownership row: no changes. Old saved
      bundles gain no ownership from live authority. Used by Living Illustration
      and Living Illustration Adept; failed placement never calls it.
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
  difficult_zone_at_exempt(engine, actor, zone, destination) -> True to excuse that zone at this proposed
                                                 destination, False or None to keep its normal terrain cost.
                                                 Pure and default-inert; Thread Heaven-Net uses the proposed
                                                 cell's support state so airborne movement skips ground-only
                                                 difficult terrain without changing the zone or saved state.
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
                                                 Context.effect_resolution is "ordinary" for an initiated action and
                                                 "stored_consequence" only while a previously installed delayed effect
                                                 resolves. run_effects publishes that value transiently on the engine
                                                 as _effect_resolution_mode so final_damage can preserve original
                                                 attribution without mistaking the consequence for a new action by
                                                 an absent source. Both values default to ordinary; this is never saved.
  amount_roll(engine, actor, source, spec, roll) -> RollRecord or None. Strict effective-roll
    transform for non-d20 typed effect amounts, generic reaction amounts and plug-in
    response rolls (combat.effect_rolls.roll_amount). Called after the deterministic
    draw, before recording/delivery. Providers must gate by owned source/condition;
    preserve roll identity and modify dice/total consistently. No reply is inert.
    Shared by damage, healing and roll-based reaction bonuses; callers own caching.
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
  mark_pre_apply(ctx, effect, subject, expires, data) -> False vetoes before any mark placement handler; None abstains.
                                                 Default-inert; use for a recipient-specific rule that cancels an ordinary
                                                 mark application without changing its shared typed effect row.
  character_damage_amount(amount, engine, actor, target, source, intent, context) -> int or None, a strict transform
                                                 before portable character damage commits. None retains amount. context is transient,
                                                 shared by the targets of one activation: attack and qi_powered booleans plus provider-owned
                                                 receipts. Consumers: cinder_ember (selected once-per-activation bonus), portable_fire
                                                 (Burning Weapon / Combustive Step attack bonuses). No owner/state means no change.
  character_damage_committed(engine, target, actor, damage_type, hp_damage, source_id, context) -> None, after that
                                                 portable packet commits (hp_damage excludes Temporary HP), including area targets.
                                                 context.damage_dealt is finalized damage including Temporary HP, after reductions;
                                                 the caller-owned _commit_damage receipt keeps it correct under nested packets.
                                                 Transactional run_checkpoint: errors unwind the entire activation, events and dice.
                                                 Default-inert. cinder_ember reads its preparation receipt to mark only the creature
                                                 damaged by Cinder Touch and sheds its printed Dim Light through printed_light.shed.
  mark_apply(ctx, effect, subject, expires, data) -> True if a plug-in performed placement/refresh; None uses ordinary marks.
    mark_choices opts in only effects with cap_replacement='owner'. It offers all existing own named marks
    when adding a new subject beyond mark_capacity, asks the owner which instances to end, and preserves
    executor-supplied expiry/data and mark_applied notification. Refresh adds no capacity. Unannotated
    effects keep the ordinary oldest-instance policy. Choices use native off-turn/manual/AI transport.
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
  before_damage_defenses(engine, target, amount, damage_type, source_definition_id, source_actor_id)
                                                 -> None or list of defense rows (resistance, immunity, reduction).
                                                 Transactional: called only for a positive, nonimmune committed packet,
                                                 after source reductions/transfers, before recipient defenses. May ask
                                                 and pay for a response or create a persistent defense. Returned rows
                                                 apply only to this packet; defenses are recomputed after responses.
                                                 Pure damage estimates never call it. No subscribers is inert.
                                                 A2GBODSUB6 uses it for adaptation before Resistance and flat reduction.
  damage_reduction(engine, target, damage_type, typed, source_actor_id, applied=False) -> int, or {amount, scope}, a flat amount
                                                 taken off a packet of damage after Resistance (combat/typed_reactions._defenses;
                                                 Ironclad Line, sys-resources-states 2026-09-29). Called with applied=False while
                                                 damage is only being weighed (keep that call pure) and once more with
                                                 applied=True from defend() when the reduction really took damage off, for a side
                                                 effect. A plain int states one amount for the triggering attack: on a mixed-damage
                                                 packet it is one whole-hit amount, and the largest answer the covered components
                                                 state is spent across them, so it is neither repeated per damage type nor capped
                                                 to the first one (typed_reactions.defend_components). A printed allowance that is
                                                 per damage type ("the first packet of that type each round", Damage Adaptation)
                                                 answers {"amount": n, "scope": "type"} instead: each covered type spends its own
                                                 allowance and each allowance actually spent gets its own applied=True call
                                                 (typed_reactions._reduction_answer).
  damage_reduction_sources(engine, target, damage_type, typed, source_actor_id) -> list of
                                                 {feature_id, amount} rows or None. Names passive reductions at the
                                                 shared committed-damage point; queries are pure and only the amount
                                                 actually subtracted is journaled and shown in the combat log. Default inert.
  reaction_ally_allowed(engine, reactor, subject, row) -> False to keep one generic ally row from answering this harmed ally
                                                 (combat/typed_reactions._ally_row_ok; Warleader Command Responses)
  ally_subjects(ctx, effect) -> list of actors, whom an "ally" effect of this ability reaches instead of the nearest-allies
                                                 default (combat/typed_executor._allies_near; Warleader Shouts, whose audience includes
                                                 the leader and is limited to those who perceive it). None leaves the default alone.
  reaction_reach(engine, reactor, other, row) -> True when a generic reaction row reaches ``other`` although it is beyond the row's
                                                 range from the reactor (typed_reactions._generic_in_range; rider lane 10 2026-09-29:
                                                 Counterpressure measured from one of the reactor's Pressure Anchors, combat/ext/force.py)
  light_level(engine, position, current_level) -> int | None: position is a Position or (x, y[, z]); a pure
                                                 per-viewer-independent adjustment to the base level before area
                                                 darkness and Darkvision are resolved. Valid
                                                 levels are 0 (Dark), 1 (Dim), and 2 (Bright); multiple answers
                                                 combine by minimum. None adds no adjustment. Default-inert; providers
                                                 must gate their change on owned, spatially active effects.
  light_sources(engine) -> light_source.LightSource | tuple/list of them | None: further light on the fight map beyond the
                                                 four stores combat/lighting.py reads itself (the map's tabletop.lights and
                                                 tabletop.ambient/ambient_regions, a carried condition:typed.light, and an
                                                 area's trigger_profile.visual.light). The model takes the maximum per
                                                 square, marks a source's disc through the same sight-clear rays fog uses,
                                                 and never lets ordinary light lift an area of darkness
                                                 (docs/specs/LIGHTING_SPEC.md §2.4, §4.1). Pure read: return rows, change
                                                 nothing. None (the default) adds no source and no level change, so a map
                                                 with no light data plays exactly as it did; a reply that is not a
                                                 LightSource is ignored. combat/ext/printed_light.py is the S3 provider:
                                                 it emits the printed ability lights of combat/rules/light_sources.json
                                                 whose light rides a lasting condition or modifier the ability files on
                                                 a creature, and only while that creature holds it
                                                 (docs/specs/LIGHTING_SPEC.md §8.2). Radiance forms and Halo of the
                                                 Merciful Sovereign provide their active printed light through
                                                 combat/ext/radiance.py.
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
      forbids_physiology: {"any": [trait names]} is the printed-immunity form on an
      effect row: the row is refused only when the trait is explicitly absent
      (False), so an unstated record stays vulnerable. physiology_note on the same
      row is one plain log sentence shown to the table when a recipient is refused;
      {name} is replaced by that creature's display name.
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
      allow_neutral_target additionally opts this nonally variant into neutral recipients through ANY_CREATURE,
      filtering out allies using the public relation query; absent keeps the existing enemy-only variant.
      No other consumer or original ally/self menu changes. All original
      choose_willing rows (Muffle Footfall, Press Seal, Harmonic Healing Tone, Sky Mantle, Second Silhouette)
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
Typed keys and seams added by the Monkey Style sphere, second pass (A2MONKEYST 2026-10-11; absent = unchanged behaviour).
  These are generic rows, not per-ability branches: each is inert unless a reviewed typed row names it, and each reads
  only what the fight itself already recorded.
  ``monkey_transform`` (combat/ext/monkey.py: a typed row's own effect) records a printed "transform into a
      studied beast form" for its 1-hour duration. It does not track which beast was studied. Out-of-fight study
      remains the Game Master's; the table admits the talent only when the character owns it
      (combat/ext/activation_requirements.py). Tiny size and template movement speeds remain explicit Game Master
      reminders because the engine has no general replacement-size or alternate movement-speed grants.
  ``pass_through_entered`` (same module) offers a Monkey Link after a transformed fighter moves through a hostile
      creature's space. This is the only transformation movement trigger currently automated. Elevation changes,
      climbing, flying, swimming, burrowing and beast agility remain explicit Game Master reminders.
  Hundred-Handed Trickster's free Borrowed Treasure use remains a Game Master reminder; no event hook or cost bypass
      is registered for it.
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
  A diagnosis that prints what it can learn about another source's condition
  also asks the general ``diagnosis_reveal(ctx, subject)`` query (Hook catalogue
  above) while it writes its notice; each provider answers for its own condition
  on the examined creature, including any printed contest. Soul Gaze's
  ``soul_gaze_reveal`` is the first caller; adding the same one-line query to a
  later Read the Spirit or dream-diagnosis reveal producer extends it without
  naming any ability. Inert with no provider.
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
      marker -- so a fighter compiled before still carries no such action and saved fights replay unchanged."""
