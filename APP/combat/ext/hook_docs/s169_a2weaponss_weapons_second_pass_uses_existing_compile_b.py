"""A2WEAPONSS: weapons_second_pass uses existing compile_block/compile_actions,
candidate_allowed, turn_start_choice, save/save_mode/save_final, attack_result,
after_miss_choice, effect_subject_allowed, event and movement_step contracts.
Conduit choices are actor-owned evented conditions; Casting-Hand variants name
their physical parent through variant_of and preserve ordinary costs/hand gates.
Long Weapon Measure reads the current step's OA exemption snapshot, actual
readied Reach profile, perceived hostile eligibility and per-round receipt.
Conduit Hand Correction waives the current miss's later damage in its own
resolution cache; no query consumes its next-save protection. save_final or
the real qualifying Concentration SAVE_ROLLED receipt consumes that protection.
General weapon ability replacement: weapon_attack_ability(ctx, attack_effect)
-> None or {ability: nonempty string, modifier: integer}. Strict, for each
actual typed weapon strike (including each strike in a multi-attack packet),
before attack declaration. Exactly one accepted provider is permitted per
strike. Its eligibility and consent are provider-owned. The executor copies
only this Context's weapon/numbers and replaces the original ability
contribution in to-hit and weapon damage, including the positive-modifier
omission for off-hand damage. Explicit variants carry consent metadata and use
this same runtime substitution path. Proficiency, refinement,
dice, hand occupancy, ammunition, Loading, economy and costs are preserved.
Unarmed/non-weapon packets and no answer are inert; no saved catalog mutation.
General exact-item checks: item_check_mode(ctx, subject, purpose, item_action_id)
-> ADVANTAGE/DISADVANTAGE/None. Open-Hand Disarm supplies its chosen item id
before the defender's actual ability check; opposing modes cancel normally.
This pure query may not consume a benefit. With no provider the check is unchanged."""
