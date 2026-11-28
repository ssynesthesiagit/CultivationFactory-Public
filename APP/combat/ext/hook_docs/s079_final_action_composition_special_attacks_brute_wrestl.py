"""Final action composition (Special Attacks, Brute/Wrestling):
  compose_actions(info) -> list[ActionDefinition] or None. Runs after ordinary,
  plug-in and targeting action compilation, before actor IDs and bundle sealing.
  info: owner_sheet, owned_ids, spheres, passives, actor_id, actions (snapshot of
  the complete input catalog). Providers append unique owned variants; None is
  default-inert. They preserve costs, targets, restrictions and payloads. The
  special_attacks provider and shared replacement_actions(info) contract compose
  Brute/Wrestling continuations and optional one-strike weapon starts. Sniper's
  existing caller shares that contract; already compiled IDs are not repeated.
  replaces_attack=0 explicitly excludes options whose multi-option printed source
  contains another option's replacement wording (Overrun retains its own economy).
  action_completed alone settles each continuation's slot count, so it cannot
  restart the Attack action or double-decrement via technique_used. Ordinary
  starts spend an Action; continuations require its spent Action and enough real
  remaining slots, which expire through the existing natural turn-flag boundary.
  compose_actions is also the one composition-time seam for a pre-roll attack
  modifier (A2BRUTAL): combat/ext/pre_roll_attack.py runs at priority 1000, after
  every provider, and folds a modifier's flat attack_modifier row into the sole
  attack's first_roll_bonus and its first_hit_only flat extra_damage row into
  first_hit_damage. It keys on source_modifier and row shape, never on an
  ability/talent id. The executor adds both to the first attack roll/hit;
  tabletop's attack_to_hit/damage_text show the same values without rewriting
  numbers.attack_bonus, and first_hit_damage joins the hit's own damage roll
  (weapon type, one DAMAGE_ROLLED) instead of a second packet."""
