"""Hook contract: wall_defenses(ctx, zone, stats) -> defense dict or None.
  docket_walls.defense_stats calls it once per wall attack before rolling/damage.
  Optional damage_multiplier (positive integer, default 1) multiplies the final
  post-defense damage without changing saved wall stats. Integrated Heavenly Fist
  uses it for the printed double damage to lower/equal-CL temporary barriers.
  Object/wall weapon attacks retain object_weapon_source/wall_weapon_source in
  typed metadata so integrated-weapon providers resolve the actual physical weapon.
  ctx identifies the actual attacking action/actor; zone identifies the owner;
  stats is the current defense dict. Return a copied dict for owned, qualified
  benefits; never mutate the input or saved zone. transform dispatches subscribers
  in registration order, passing each the previous non-None result as stats.
  None retains that result; later explicit replacements of the same field win.
  Independent benefits must preserve unrelated fields from their input dict.
  No subscribers/None leaves existing defenses and saved zones intact."""
