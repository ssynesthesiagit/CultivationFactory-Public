"""General confirmed mixed-die damage bonus (A2SNIPER):
  confirmed_hit_damage_bonus(engine, attacker, target, spec, intent, source, critical) -> int or None is a strict checkpoint after critical conversion,
  before primary damage. Providers own evented bonus rolls and receive the
  final critical boolean, including cancellations. Returned amounts join the
  primary packet's modifier so Resistance, reduction, Concentration and lethal
  decisions see one combined packet. A miss never calls it. None means no dice
  or events; old catalogs with no owning marker retain their original stream.
  Invalid replies/errors abort the accepted transaction. sniper_precision uses
  it for surrendered Extra Attack dice of Head Shot, doubling dice on a critical,
  and Deadly Shot's flat +10 (never doubled). New Deadly Snipe variants resolve
  exactly one attack and preserve the remainder through the replacement marker.
  The Head Shot compiler seals owned Killing Aperture. A live Rangefinding,
  Hundred-Breath Wait or Perfect Shot line is sampled before ATTACK_ROLLED
  consumes it; that shot's surrendered dice use d10. Killing Aperture's other
  protected-save/narrative clauses remain manual, so it is not promoted to FULL.
Reviewed area-talent shape contracts (A2FLOWERS):
  A zone effect's optional shape_spec overrides triggers, inside and obscured
  in a linked area talent's compiled shape. Names and resource costs still come
  from that talent. The compiler deep-copies the explicit contract into the
  action; zones snapshots it at creation, so reload never reads current prose.
  Distinct start/enter triggers retain their own who/effects and the normal
  once-per-creature-per-turn accounting. No shape_spec retains prose inference.
  No save schema, policy, event or locked engine field changes. Existing
  choose_effects supports off-turn owner decisions in those area triggers.
  Flowers' Calming Perfume uses flowers_repeat_frightened to ask the actual
  recipient to accept/decline and choose one original save; no range search or
  command is substituted for that creature's consent. Beguiling Perfume reads
  only its saved flowers_beguiling marker in attack_mode; Charmed targeting uses
  the ordinary recipient gate and the ally penalty requires sight of its source.
  damage_recipient_effects is an opt-in defensive-reaction effect wrapper:
  nested explicit-target rows apply to typed.protects for a bystander, or the
  reactor on the self-damage path. It uses a transient copied Context and the
  existing executor; no unmarked saved reaction changes or new fields/events.
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
Yin mark choices (A2YIN): yin_marks reuses mark_applied/mark_spent and the
  strict effect_expiring_choice checkpoint. Patient Moon places an exact-instance
  watch using effect_durations.token(end, owner, next turn); this also covers a
  longer-lived mark, whose eligibility comes before its own expiration. Once per
  round acceptance uses a persisted integer turn flag. Twofold stores paired
  target identities; a transfer preserves the other mark's original deadline and
  retargets its exact-instance Patient watch without restarting that watch. Only
  new reviewed effects or compiled passive rows enroll. Old sealed rows are inert.
  No new core seam, event format, or saved condition field is required.
Affliction selected start effects (A2DISEASE): parts.<label>.start_effects is
an optional list of typed effects sealed in the affliction condition. The
choose_success=true asks the caster for one successful-save symptom from the
menu; absent flags retain the old standing choice. The
existing turn_start provider resolves those rows against the holder using the
original caster and catalog action's saved numbers. Each part shares the parent
concentration, repeat-save and expiry lifecycle. Absent rows are inert; old
saved afflictions are unchanged. Providers must not create a second independent
clock for a selected part. No core hook or saved schema field is added.
Contaminated Wound uses the existing damage_dealt and compile_block seams:
new owned disease_wound policy=1 rows carry sealed numbers. Actual damage from
Sow or a weapon opens one optional paid choice, with a shared integer turn use.
No owning row retains the saved Sow-only modifier and predecessor behavior.
The existing choice_reactors seam enrolls owners of sealed policy-1 rows,
including rows saved before enrollment was added. The service asks manual
owners during AI steps and lets automatic owners use their controller.
Absent rows and predecessor policies add no owner; no saved row is rewritten."""
