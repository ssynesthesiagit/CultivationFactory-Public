"""Opposed-check effect contract (ext.contests / typed_executor):
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
  The selected spec includes its semantic kind even when no skill is named.
  Foundation's provider recognizes kind-only Cultivation checks and delegates
  to its existing owned-row, hostile-maintenance hazard qualification; unrelated
  checks and creatures without a qualifying Foundation benefit remain inert.
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
  the DC succeeds."""
