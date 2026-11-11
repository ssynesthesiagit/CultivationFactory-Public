"""Lock 21 rider utility: typed ActionDefinition.parameters.rider_utility is an
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
roll modification rather than a stored bonus."""
