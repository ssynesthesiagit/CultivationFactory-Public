"""Body Subpaths 5 (A2GBODSUB5):
  piercing_area is an opt-in typed line effect carrying effects=[one save row],
  object_multiplier and ignore_partial_cover. It orders creatures and damageable
  objects by nearest intersecting footprint distance, resolves each once, and
  rechecks native line of effect after each obstruction takes damage. It never
  ignores solid terrain. Harmful unscoped recipients are enemies; automatic
  aiming remains the controller's perceived-target menu. One shared damage roll
  and damage-type choice covers the activation. Immunity and Damage Thresholds
  remain native. Its save_cover_reduction answer removes only partial Dex cover.
  The nested save retains its explicit area applies_to scope; each singleton
  Context bounds that row's recipients without changing its selecting save's
  provenance. save_context.damage_save therefore reports area delivery to
  save-limited defenses. Ordinary target saves keep their single-target scope.
  The resolution-local Context.damage_cache['_ordered_objects']=True tells
  objects.technique_used that object packets were already resolved, preventing
  duplicate delivery. Absent flag preserves ordinary blasts. objects.area_reaches
  is the public shared object-intersection/line-of-effect query for this provider
  and ordinary object blasts; it exempts only the target object's own wall cells.
  Eight Gates uses the existing flight query while six Gates are open: current
  effective walking Speed and Hover. Native movement/falling own altitude and
  loss of flight. Seventh Gate includes Void Resistance as printed.
  Parasite Vessel uses existing pass_through only during Worm Demon Body;
  difficult creature transit never permits an occupied destination or wall
  passage. Internal Brood uses save for explicit category:disease save provenance,
  without inferring disease from Poison. Brood Tide shares one resolution cache
  for its area damage and retains enemy-side recipients.
  Brood Substitution binds its pending movement to the active intent. Only a
  DAMAGE_COMMITTED from that resolution consumes the marker; action completion
  clears it when no packet was delivered (including nested saves with no damage).
  The hit Reaction and failed-save Reaction therefore share the same exact-packet
  boundary without leaving a marker for a later unrelated hit.
  Its Swarm-Shell is a damageable bound_objects.place asset guarding precisely
  its terrain zone, with printed AC/HP/defenses. Destruction removes that zone;
  turn_boundary_start removes it at the owner's next start and native_lifecycle
  removes the asset. It takes no actions or cover. Opening widths and shell
  endpoint occupancy remain explicit unresolved printed clauses."""
