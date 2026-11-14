"""Printed Save DC seam (combat/save_dcs.py, combat/ability_checks.key_modifier):
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
  No ability id appears in either module."""
