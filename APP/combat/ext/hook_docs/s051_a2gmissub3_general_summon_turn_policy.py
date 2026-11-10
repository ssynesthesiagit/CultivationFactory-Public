"""A2GMISSUB3 general summon turn policy:
summon_turn_policy(engine, actor) -> None | {"skip": True} is a strict pure
query for an active present summon before its default action/command policy.
A skip removes its independent action, bonus action, reaction and movement
allowance for that slot, and advances it without granting the default Dodge.
Missing providers/None retain native command and Dodge behavior. Invalid
replies abort the transaction. Owner-driven expression providers resolve
their actual actions/movement through the owning transaction and ordinary
effects/native movement; this seam itself grants no action or movement.
Soul Warden opts in only where the owner's sealed immediate-strike action
exists. Unstamped historical command catalogs retain their earlier policy.
threshold_geometry.thresholds/crosses/side/open_threshold are pure shared
readers for live mounted finite apertures (mount_axis h/v, integer mount_line
in hundredths). Crossings require equal base altitude, opposite sides, and
intersection inside the aperture's one-cell span. They do not infer semantic
thresholds from actor names or extend a door over its entire wall.
Boundary Passage uses existing object_targets/object_action, movement_attempt,
forced_movement_attempt and teleport_gate. Its owned Mark objects carry native
damageable profiles; native teleport handles legality, seals and arrival.
Walk the Border's active state opts into existing pass_through as difficult
creature passage; end occupancy remains native and illegal.
A2GMISSUB3 Spirit effect tags: effect_allowed(ctx, row) honors optional
  spiritual_categories=["possession"] when the acting creature holds an
  explicit no_possession condition. Untagged rows retain their existing path.
  Soul Warden's specter_guard uses save_effects with save_categories
  possession/soul_displacement for its next-save Advantage; consuming the
  source-owned condition uses the normal condition-removal event. Other save
  categories and creatures without the guard are inert.
  Specter Half Cover uses cover/effect_cover and save_bonus_details. Named cover
  proposals combine by maximum (ordinary cover never stacks); other named
  save contributions retain additive behavior and cover reduction runs once.
"""
