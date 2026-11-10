"""Still-Water and AI admission hook contracts.

Native effect and decision seams added by source plug-ins (Still-Water R8):
  attack_slot_replacement(ctx, attack, target, index, remaining) -> nonnegative int | None;
    called before each ordinary attack slot; return the number of slots consumed by
    a successfully resolved replacement, or None to leave the slot untouched.
  condition_data_additions(ctx, subject, effect) -> dict | None; each returned
    mapping is merged additively into a new condition's stored data, so it may add
    keys but never replace one with a different value (the engine raises then).
  movement_step_completed(engine, mover, previous, destination, intent, forced) ->
    None; runs after a legal step is entered and its hazards/reactions resolved.
  attack_aftermath(ctx, target, hit, index) -> None; runs after a settled attack
    (documented with its consumers in the Still Water contracts below).
  All are default-inert, source-owned hooks; consumers must preserve the core
  result when no provider responds.

  ai_player_only_action_allowed(engine, actor, action) -> True to admit a plug-in-owned player_only action into the
                                                 AI's ordinary legal candidate set; called only for AI contexts and
                                                 defaults false. The owner plug-in must prove the actor owns the option.
Still Water / Drawn from Stillness contracts (combat/ext/still_water.py):
  integrated_weapon_selected(engine, actor, source, item) -> True | False | None.
  Pure confirmation that the selected integrated item is the actor's own recorded
  Draw Weapon; None leaves every other selection source to its owner.
  attack_aftermath(ctx, target, hit, index) -> None. Runs after one committed
  attack resolves; consumes this Draw attack's queued follow-up moves, ends its
  posture and sheathes only when the owner's own pause asks. Without a Draw
  profile the hook is inert.
  attack_attempt_tracking(engine, attacker, defender, source, intent) -> True | None.
  Opts one attack attempt into a stable attempt id while a Still Water posture or
  Empty-Scabbard Step watches it; None leaves ordinary tracking unchanged.
  attack_line_movement(ctx, row, cells) -> True | None. Performs One Breath,
  Three Horizons' half-speed move along the already accepted line; None when this
  action is not that source.
  attack_line_profiles(ctx, base_id) -> dict[str, action] | None. Supplies the
  remaining legal Draw Weapon profiles to One Breath's line; None otherwise.
  attack_line_continuation(ctx, row) -> True | None. Keeps One Breath's accepted
  remainder installed after a counter; individual native remainder candidates
  still own their choices and countdown. None is default.
  weapon_attack_draw_allowed(engine, actor, action, identity) -> True | None.
  Allows the recorded Draw Weapon to become ready during its own attack; None
  leaves other weapons' draw gates untouched.
  object_attack_prepare(ctx, obj, index) -> True | False | None. Rechecks reach
  and hands for a Draw Weapon attack on an object and installs the object weapon;
  False vetoes, None is inert for other owners.
  object_attack_modes(ctx, obj, index) -> "ADVANTAGE" | None. Posture's advantage
  on the owner's Draw object attack; None leaves ordinary modes.
  object_attack_damage_type(ctx, obj, index, kind) -> str | None. Offers the Draw
  Weapon's damage types (and Force for Heavenly Fist); None for other attacks.
  object_attack_packets(ctx, obj, index, critical) -> list[tuple[int, str]] | None.
  Adds First Cut's proficiency packet and optional move once per turn; None when
  this is not the owner's Draw object attack.
  object_attack_resolved(ctx, obj, hit, index) -> None. Closes posture and runs
  follow-up move/sheath after an object attack; inert without a Draw profile.
  held_weapon_impairment_allowed(ctx, holder, item, operation, qualifiers) ->
  True | None. Heavenly Fist keeps the wielded Draw Weapon usable against the
  printed mundane break, rust, dulling and weapon-breaking causes, but not
  Disarm; None leaves every ordinary equipment gate in force.

"""
