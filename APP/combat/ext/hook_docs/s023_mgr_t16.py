"""Material traversal and movement selection (MGR-T16):
  material_traversal(engine, actor) -> None or {mode: str, materials: sequence
  of canonical material tags, difficult_materials: sequence of tags}. Pure,
  default-inert owned capability. Native menus merge every returned mode;
  grants in the same mode union their materials, using the cheapest permission
  for overlapping media. Vertical movement needs the material at each crossed
  volume; material support prevents falling inside it, never flight through air.
  flight.step_allowed/step_cost share its law at commit. Unlabelled independent
  blockers, roofs, occupancy and sealed regions remain blocking. Material tags
  grant neither vision nor breath. terrain_materials.at(grid, cell) and
  grid.materials_at(cell) expose authored records at an integer altitude;
  terrain_materials.query(engine, cell) also includes active zones' explicit
  material/sealed or wall.material/sealed and named terrain materials. Visual
  color/obscurement alone never supplies solid matter. Independent overlaps
  retain all records, so an unlabelled wall atop soil still blocks traversal.
  EDITOR_MATERIALS is the single builtin floor-to-matter mapping, while named
  terrains read terrain.json's material. Region material/sealed are optional.
  material_only=True denotes an overlapping matter annotation with no geometry
  or movement-price change. Endpoint recovery and invariants use the same public
  material placement query as route admission, including after a cold reload.
  movement_begin keeps its None return contract. movement_sequences.bind(engine,
  actor, family, available, selected) binds distinct owned features to the current
  accepted route. enabled(...) reads the nested transient scope; absent binding
  is unrestricted. MOVEMENT_COMMITTED.movement_selections records selected IDs
  as strings in lists. Selection survives reload by receipt; pauses and nested
  routes restore scopes. No subscriber/binding changes ordinary movement.
  Native _resolve_movement and ext.granted_movement.move accept optional
  movement_context metadata, read by movement_sequences.context(engine, mover)
  during movement_begin and traversal. feature_id names the initiating ability;
  it grants no ownership or benefit. Providers can reserve that ability in their
  own selections. Absent context is empty and default-inert. Nested movement
  starts with its own context; pauses, errors and completion restore the outer
  context in finally. Only explicit selection receipts are persisted.
  teleport_begin(ctx, subject, previous, destination, movement_context, unwilling, forced, feature_id) -> None
  is a strict pre-landing selection callback after
  teleport legality/seal gates, inside a fresh movement_sequences.sequence scope.
  feature_id is the action's mechanic, or the explicitly supplied settlement
  feature. Providers may ask and bind owned selections; pauses roll back the
  entire action including its costs. Selection remains active through arrival
  settlement and is persisted on MOVEMENT_COMMITTED with the same primitive
  shape as native paths. Nested moves restore their enclosing selection. This
  does not dispatch movement_begin, step hazards or opportunity attacks for a
  teleport. No binding/subscriber leaves existing teleport behavior unchanged."""
