"""Native journey acquisition and continuation contracts:
  journey_source_sheet(sheet, session, actor_id) -> replacement sheet | None
  is a pure sequential transform of a copy of the current installed sheet.
  Each provider receives the previous replacement; None retains that sheet.
  Overlay only committed, owned source state and preserve unrelated changes.
  On creation/reopening this runs after retained actor state is restored and
  before recompilation and initialization; acquisition runs it before dispatch.
  Exceptions propagate and abort before save. No provider preserves the sheet.
  Committed acquisitions are projected again when a carried creature opens the
  next journey, so menus and combat bundles reflect what it learned.

  journey_acquisition(session, actor_id, source, payload, sheet) -> dict | None
  is a strict transactional request against the current source-overlaid sheet.
  Exactly one provider must return {'sheet': dict | None, 'acquisition_id': str};
  absent or ambiguous providers reject before save. Providers return None for
  unowned sources and validate access, attainment, costs and replacement before
  recording acquisition. A sheet of None may retain a paid failed attempt; a
  dict is compiled and replaces the bundle with held resource amounts capped
  to the new maxima. Exceptions propagate and abort the cold session.
  journey_acquired(session, actor_id, source, acquisition_id) -> None fires
  only for a replaced bundle, strictly before revision/save and immediate combat
  entry. This notification may republish existing paid continuation, never a
  new activation or refund. Its return is ignored; no provider makes no edits.
  It is deliberately not dispatched when journey_acquisition returned sheet None.

  journey_initialize(session, actor_id) -> None strictly notifies each actor
  after retained state, source-sheet overlays and any recompilation, before
  journey_initialized(session) -> None strictly notifies once for the full
  roster. Both run before the first save; returns are ignored. Gate owned
  sources and do not duplicate retained effects. Exceptions abort creation;
  no providers leave ordinary initialization unchanged.

  journey_snapshot_actor(creature, session, actor_id, engine) -> actor | None
  is a pure sequential transform before the generic encounter snapshot on
  resume. Return a copy to strip only owned transferable effects; never mutate
  the terminal fight. None retains the actor; no provider preserves the normal
  snapshot. Exceptions propagate and prevent the journey save. Then native
  resources, position, exhaustion and incapacitation are imported, followed by
  journey_encounter_settled(session, actor_id, engine, creature) -> None for
  that actor. This strict notification receives the original combat creature
  and may capture owned continuation from the terminal fight. Its return is
  ignored. It runs before travel phase/revision/save; exceptions abort resume,
  and no provider adds continuation. Never change the immutable terminal fight.

  journey_scene_end(session, previous_scene_id, current_scene_id) -> None is
  a strict notification after the trusted table-owner declaration and scene
  identity update, before SCENE_ENDED/revision/save. Return values are ignored.
  Providers reset only owned scene allowances; rest/encounter end do not imply
  a scene boundary. Exceptions abort the cold session; no provider adds edits.

  fact_admission_schema(session, source, subject, kind) -> dict | None is a
  pure query used on declaration and replay-checked reads. Exactly one provider
  must return value_type ('text', 'flag', 'document'), maximum_seconds and
  description; optional authority is 'subject' (default) or 'table_owner'.
  Return None for unsupported sources/kinds. No unique schema means rejection,
  never a grant. query logs and skips provider exceptions; the remaining replies
  still require exactly one schema. Subject authority cannot impersonate world
  facts, and world authority cannot supply private consent. The declaration
  caller validates bounded plain data, expiry and readers before saving; a
  schema does not prove acquisition or fabricate a committed mechanical fact."""
