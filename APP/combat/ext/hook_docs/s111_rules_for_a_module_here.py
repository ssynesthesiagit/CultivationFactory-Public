"""Rules for a module here:
- Strict turn_boundary_start(engine, actor) -> None runs after establishing the
  current round/slot and incrementing turns_started, before per-turn resets,
  flight/economy initialization, expiry events, TURN_STARTED, hooks, reactions,
  choices or zone triggers. Lower priorities run first. Subscribers record all
  changes using normal events; errors/pauses roll back the enclosing transaction.
  Legacy Defeated, Dying and Stable slots retain these boundaries and normal turn-start
  gameplay (including death saves/recovery), then end automatically if still
  unable to act. combat.turn_decisions.passes_without_decision is the shared
  read-only engine/service query: setup and pending resolutions are excluded;
  recovered or Conscious-at-zero creatures keep their decisions, and a Dying or
  Stable creature keeps its decision only when its legal candidates include an
  option besides End Turn (no plug-in hook; the candidate list is the rule). A forced End
  Turn left in an old save or after an own-turn defeat is committed by Local
  Auto without changing stored control preferences. No new saved field.
  If a turn_boundary_start subscriber sets terminal_result, the engine stops
  turn startup after this checkpoint, before resets, expiry, TURN_STARTED or
  native-zone effects. No subscriber changing state means no new event.
- turn_boundary_start consumers: ext.summon_lifetime (-100)
  consumes only active present summons with a persisted expires_on deadline,
  using the shared effect_durations.due clock and summons.dismiss. Old records
  without deadlines remain inert. Dismissal does not roll dice or ask a choice.
  ext.athletics preserves a Capoeira owner's starting Prone posture across the
  automatic stand using a transient round flag and stand_allowed; TURN_STARTED
  removes that veto before turn_start_choice snapshots eligibility. Ordinary
  later standing is unchanged. Nonowners never set or consult that marker.
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
  Consumable providers may namespace contribution names with a condition instance ID:
  event consumers then retire only the instance that supplied this roll, even when
  result-time choices create a replacement. Proposals remain pure; retirement uses
  the delivered SAVE_ROLLED receipt rather than mutable current bonus lookup.
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
  turn_movement_allowance(engine, actor, speed) -> None or nonnegative integer.
  One provider may replace the ordinary initial pool after start-turn expiry,
  including base-engine genesis. No answer preserves the native Speed pool.
  Immobilized starts use the same provider on a shallow actor view with only
  immobilizing conditions removed; turn_flags remains shared with the actor.
  This snapshots withheld feet and lets the movement owner seed its integer
  Speed baseline without granting movement before the immobilization ends.
  ordinary_movement_limit(engine, actor) -> None or nonnegative integer.
  Pure movement-owner ceiling, combined by minimum with the native remaining
  allowance for ordinary candidates, step validation and withheld restoration.
  Separate explicit movement grants keep their own validation. No answer changes
  no allowance. mounts uses both seams only for a bonded controlled pair.
  speed_contributions.effective_speed(engine, actor) shares Gate4's composition
  with mounted base-engine genesis: base adjustments/immobilization, motion and
  speed-hook contributions, then final halving. Each contribution runs once.
  mounts records that initial Speed as integer mount_movement_speed_ft:<mount>
  and reconciles a rider's technique Speed change through technique_used;
  allowance_replaced marks that delta so the ceiling does not count it twice.
  movement_budget tracks an integer movement_withheld_ft only when a turn begins
  immobilized, after turn-start Speed expirations. Removing the last immobilizing
  condition restores that unspent initial allowance (capped by current Speed),
  with MOVEMENT_ALLOWANCE_RESTORED; it never refunds spent movement or creates
  extra Dash/grant allowance. CONSCIOUS actors at zero HP share the same contract.
  movement_budget.speed_changed(engine, actor, effective_delta_ft, source,
  reason='speed') journals signed unspent-pool changes for the current actor
  only, clamped at zero. Condition removal supplies its detached ending snapshot
  to compare composed Speed before/after; zero-Speed immobilization retains the
  withheld contract. Exhaustion and load changes share this helper. Movement
  owners refresh their turn_movement_allowance baseline without granting feet.
  Replacing the walking allowance also updates flight's existing integer
  movement_allowance_adjustment_ft basis, so mode conversion preserves the
  same spent feet. carrying's state_event subscriber reconciles a directly
  applied Encumbered condition; inventory refresh supplies its explicit prior
  load instead, without a hidden query override or double reconciliation.
  Condition removals reconcile lost bonuses; acquisition/replacement and
  penalty recovery remain the producer's contract, using speed_changed for
  evented net deltas (load and Exhaustion). This avoids double-crediting
  producers that already grant the movement for their Speed increase.
  current_turn_only=False also reconciles a removed bonus on an inactive-turn
  holder's retained pool; its next turn still refreshes the allowance normally.
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
  blockers and test complete footprints. A transit grant alone never permits an
  occupied stop; only the explicit pass_through_stop/shared_space contract below
  admits one. No creature grant crosses a wall. A stopped transit returns along its committed path
  to the last free space, retaining spent movement, in the recorded transaction.
  Flight and finite-height maps use the same permissions against actual creature
  volumes; endpoint_volumes applies the same explicit stop permissions to flight,
  roof walking, climbing and jumping. Recovery checks placement
  at its actual altitude, so clear air above a low wall remains a legal stop.
  Recovery runs normal leave-zone cleanup and emits a readable PASSIVE_TRIGGERED
  notice; the final movement record binds the corrected position and path.
  None preserves existing movement. Forced movement and teleports do not use it.
  MOVEPASS1 built-in rule (combat/movement_passage.py): during a voluntary move a
  mover may pass through an ally's space, an Incapacitated creature's space, a Tiny
  creature's space, or a creature two or more sizes larger or smaller. Each such
  space is a 'difficult' whole-footprint grant, and creature_passage.geometry keeps it
  an illegal stop (end_blocked), so no move ends there. Forced movement is unchanged.
  movement_pass_through(engine, mover, occupant) -> True | None lets a plug-in (e.g.
  a hostile pass-through talent) pass a hostile space as a 'difficult' grant; any
  other reply raises. Default-inert: with no provider the hook is empty.
  Observational (ext.run): grants are read during candidate generation, outside a
  transaction, so a plug-in must not rely on run_strict semantics here.
  Strict pass_through_entered(engine, mover, occupant, intent) -> None is a
  transactional notice after first entering a creature footprint; consumers may
  record source-specific crossing limits/protection. It fires once per crossing,
  never per interior step, so a player is asked a crossing question once.
  The existing pure opportunity_allowed query also applies to legacy reactors.
  C16: Overrun grants bind the allowed occupant's entity id and expire at the end
  of the current turn, so choosing a short move does not discard unused passage.
  A once-only crossing records use in pass_through_entered and keeps permission
  until the mover exits that footprint, then denies re-entry. Queries never spend it.
  Changes to condition data require CONDITION_APPLIED with the instance id.
  ext.athletics uses these same hooks for Tumble's one named-creature passage:
  entry consumes it, exit completes it, and movement_step grants Sudden Flank
  only on that exit. Interrupted recovery consumes entry without granting Flank.
  END_OF_CURRENT_TURN removes permission and unused target-specific Advantage.
  Living Battering Ram/Fortress-Line Breaker permission is scoped to their approved
  straight move; it never waives path, target, payment or attack requirements.
  Optional pure pass_through_grant(engine, mover, occupant) -> None or a
  (cost, scope) pair states one provider's grant and the exact integer (x,y,z)
  occupied voxels that grant covers; scope None covers the whole footprint.
  pass_through replies are whole-footprint grants, so existing abilities are
  unaffected. Because each provider names its own scope, a restricted grant can
  never narrow another ability's independent unrestricted grant: grants union
  their volumes, an unrestricted grant covers the footprint outright, and a voxel
  several grants cover keeps the cheapest cost. Ground pathfinding uses the map
  projection of covered voxels; flight uses exact voxels.
  Optional pure pass_through_limited_grant(engine, mover, occupant) -> None or
  list of (cost, scope, resource_id) grants a one-creature crossing per receipt.
  resource_id is a nonempty string, cost/scope follow pass_through_grant.
  Compatible held receipts bind on first entry, even alongside unlimited
  passage; permission lasts through that footprint and is consumed on exit.
  Planning counts equivalent receipts and retains crossing bindings, run-up
  headings and cost-optimal predecessors. Queries never consume real receipts;
  providers bind/consume them through entry/step hooks. Without a provider,
  ordinary movement is unchanged.
  Optional pure pass_through_preview(engine, mover, occupant) -> None or cost
  quotes a contingent future grant; actual entry still needs real permission.
  Strict pass_through_entered_cells(engine, mover, occupant, entered, intent) ->
  None is a transactional notice carrying the exact occupied voxels a step newly
  entered inside that creature, narrowed to what current grants cover. It is the
  general entry notification for a provider that bills or marks per region, so
  several providers each answer for their own voxels of one crossing. It fires on
  interior steps too; pass_through_entered stays the once-per-crossing notice.
- Voluntary movement: combat.voluntary_movement.destination_allowed is a pure
  knowledge-based query shared by ordinary and granted menus. Grants use observed
  occupancy; actual blockers are checked by native execution and recorded contact.
  Existing destination-only Frightened semantics remain unchanged here.
- Native movement cost changes: each iteration refreshes terrain, occupancy and
  dragging before its first budget guard, then rechecks after reactions. If a
  newly priced step is unaffordable, movement stops at the last paid square and
  records the shortened path and readable reason; it does not raise or undo the
  accepted reaction. Initial invalid candidate budgets still fail normally."""
