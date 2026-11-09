"""Typed keys and seams added by rider lane C14 (absent = unchanged behaviour):
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
  Opening Phrase's "+PB to one Concentration saving throw" uses save_bonus_details with source system:combat.concentration
      (combat/ext/music.py). Its named contribution contains the exact condition instance ID collected before
      the roll. SAVE_ROLLED consumes only that contributing instance, never a replacement granted by a
      mid-save rewrite. The delivered roll_id and actor identify the original save even if earlier event
      hooks append more events. No held bonus = no change. No new engine hook or saved field is needed.
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
  reaction_committed(engine, reactor, row) -> None. Notifies plug-ins once after an accepted non-free Reaction and all its
      printed costs commit, before its effect resolves. Generic costs notify from typed_reactions._spend_generic; native
      open_reaction/spend_reaction notify at commitment. Previews and free responses never notify. Hooks are default-inert.
      Specialized consumers scope each accepted response with typed_reactions.reaction_resolution(engine, actor, source_id).
      That scope never catches interruption: it unwinds the entire consumer, including returns after the scope.
      Hook runners use typed_reactions.dispatch (invoke_strict) to discard the interrupted hook's reply (None).
      Native/generic responder loops use the same dispatcher, as ``with reaction_dispatch():``, around each
      individual response, not the whole loop.
      Nested hook runners propagate interruption of their enclosing response; later hooks/responders continue.
      activation_payments.reaction_completed reports post-payment eligibility to this one dispatcher;
      paid costs stay spent and enclosing responder loops continue. Its local notification frame is discarded on pause/rollback.
      open_reaction(..., payment=callable) and spend_reaction(..., payment=callable) reserve economy before a native payment,
      then notify commitment. Built-in native defenses use the same commitment dispatcher after paying their printed costs.
      split_reaction_effects(effects) separates a leading spend_mark/spend_resource payment prefix from consequences; execute
      the prefix through the existing typed effect runner in payment, and only the remaining effects after open_reaction.
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
  obscurement_ignored(engine, zone, viewer, seen) -> True | None. Strict pure observer/subject
      exemption from ONE zone's visual concealment. zones._blocks and
      _through_obscuring_wall consult it for perception and attack modes alike.
      It never removes physical cover, grid LoS/LoE, blindness or Hidden/Invisible
      conditions, and never changes another viewer's knowledge. No subscriber:
      existing visual rules remain unchanged. Yang Overbright Trail consumes it
      for its marked subject, originating owner, ordinary zones and 60-ft range.
  attack_mode_removed(engine, attacker, target, ranged) -> iterable of "ADVANTAGE" | "DISADVANTAGE:invisible" |
      "DISADVANTAGE:blinded" | "DISADVANTAGE:obscured" | "DISADVANTAGE:prone", or None. Pure query (combat/ext/attack_mode_removal.py ``removed``): the
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
      drunken_style enrolls active Chaos-Step Awakening owners for their optional step after an Off-Rhythm miss.
      tabik_dark enrolls allied Darkness creators only when another active ally owns a Clearsight Meld action;
      no owned ability means no enrollment. Consent and movement remain scoped to the reached checkpoint.
      Needle's generic inline-choice transport enrolls manual participants only when a compiled action opts in with
      ``parameters.typed.manual_inline_choice``. This supports an affected creature choosing during another creature's
      AI turn, while unrelated action catalogs remain default-inert; only a reached checkpoint prompts.
      qiweaving_bond enrolls potential Shared Reservoir givers carrying a bond from an owner whose saved catalog
      has that action; unrelated reaction plans are unnecessary. No Reservoir action or bond is default-inert.
      ink_riders enrolls potential recipients only when an active writer owns an explicit ink_press_mark effect;
      cross-team player recipients can consent during an AI turn, while hostile AI recipients decline.
      Team membership selects the AI default, never whether a player is allowed to consent.
      protection_second_pass enrolls active allies of a stamped Sanctuary owner, including potential entrants
      outside its Ward. Actual relief checks membership, lifetime, source and exact instance at the checkpoint;
      unstamped historical Sanctuary states advertise nobody. The query reads state without mutations.

  eligible_recipients(ctx) -> None or list[ActorState], strict, before before_target_reactions.
    One opted-in provider may supply a single-aim action's legal multi-recipient
    pool. It must enforce printed sides, range, sight, line of effect and vessel
    rules. The transport checks live identity, uniqueness and missed locations;
    two providers or invalid replies abort. No provider preserves the old pool.
    The subset selector, reactions, saves and effects share the final roster.
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
    shove_failed(ctx, target, result)          -> None, after a failed Brutal Shove contest, where ctx.actor is the mover whose
                                                 forced movement failed (result: success False, mine, theirs, skill). Dispatched with
                                                 run_strict (transactional): Ground Keeps Score (earth_responses.py) moves a Burden
                                                 Mark from the mover when the mover's own Mark-holding fails the contest.
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
  Advancing Overruns (brute_shove): compile_action identifies the owned RAM/Line Breaker talent directly, not a missing
    passive row. brute_advance offers a separately budgeted native path. Its transaction-local pass_through preview
    never rolls; movement_attempt calls brute_overrun before entry, applying apply_shove_success on the SAME contest
    result (no second roll). Failure returns the standard stop receipt. Manhandle reuses apply_manhandle, once per
    Line Breaker move. opportunity_allowed exempts only the Ram target during that move; difficult_exempt removes
    only nonmagical ground costs for Line Breaker. Nested unrelated moves and nonowners receive no benefits.
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
Summon source data may opt into the same contract with choose_visible_space=true
and a printed range_ft. compile_summons returns placement_range_ft; the compiler
seals a CELL action and cell_placement={} after ordinary summon conversion.
Default absent/false retains the exact SELF catalogue. This general data seam
supports any single-creature summon, not an ability-id case. Star Shadow opts in.
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
old contexts and non-opted-in policies retain their scores and serialized shape."""
