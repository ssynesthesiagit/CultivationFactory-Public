"""resolve_attack_damage(ctx, attack_effect) in typed_executor is the shared sealed
primary-damage resolver for creature and object delivery. It sets the weapon-die
marker, folds attack_damage/attack_damage_types and then damage_roll_bonus once.
Providers may consume next-use state; call only during damage resolution, never
candidate discovery. It returns (dice, kinds, initial_type, damage_row, weapon); callers own critical
rolling or maximization and defenses. Rotting Grasp maximizes the resolved dice
and adds their modifier once, including when critical dice double.
"""
