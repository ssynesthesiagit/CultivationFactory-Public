"""Area knowledge policy (owner 2026-10-08): area_knowledge_policy's match_start
  provider records area_knowledge_policy=1 in MATCH_CREATED for new fights.
  It also binds area_origin_permissions, a sparse source-ID -> integer 0 map
  of printed unseen-origin exceptions; absent sources require sight. Targeting
  consumes this saved map plus saved typed overrides, never current prose.
  Missing optional stamps retain the zero policy; reload restores the saved
  permission map from the creation event. A stamped fight missing
  its binding is rejected rather than silently using changed source authority.
  combat.area_knowledge.origin_allowed(engine, actor, action, destination) -> bool
  gates CELL square perception for rules requiring sight, independently of range
  and line of effect. Explicit typed/printed unseen-origin permissions remain.
  preview_engine(engine, actor) -> read-only engine projection uses the public
  target_knowledge.actors_for view for area_safety and collateral metadata.
  Execution always uses the original engine and hits actual area occupants.
  This is a general owner rule, not an ability hook or runtime method patch."""
