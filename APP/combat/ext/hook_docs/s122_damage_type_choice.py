"""damage_type_choice(ctx, kinds, targets) -> one allowed damage type or None.
    General transactional checkpoint in typed_executor.choose_damage_type for a
    printed player choice, shared by attack and save/area damage. Exactly one
    provider may answer, and its result must be in kinds. Context and targets are
    resolution-local, never saved. No answer preserves the historical automatic
    selection and old event bytes. Newly sealed Corpse Explosion uses one choice
    for the whole blast; manual owners are asked, while AI preference considers
    perceived targets only. The hook is inert without an owning provider.
Lock round 26 movement and Concentration seams (gate2_engine.py, 2026-10-08):
  engine.movement_scope(actor_id) -> {actor_id, source_id, mode, granted} or None.
  A pure query, true only while _resolve_movement walks that actor's steps:
  movement_attempt/step checkpoints, leave-reach opportunity attacks and the
  reactions they open. None before path validation and after
  MOVEMENT_COMMITTED; transient, never saved, unwinds on pauses/errors.
  Use it from an existing ac(engine, actor) hook for "during movement" rules.
  Shield Skate (auto/shield shield_mobility): return
  -armour.shield_bonus_earning(engine, actor) when skating(engine, actor) and
  engine.movement_scope(actor.entity_id) is not None; otherwise None.
  Painted map terrain now reaches _hostile_difficult_cells (and so movement
  cost) through zones.difficult_cells even with no typed zone active; the
  existing difficult_exempt / difficult_zone_exempt hooks still excuse it.
  concentration_save_failed(engine, actor, roll, dc, context) -> "MAINTAIN" or
  None. Strict; called only after a failed Concentration save while actor
  has current Concentration. context = {source_actor_id, damage_source_id,
  started_sequence, source_definition_id}. Exactly one "MAINTAIN" keeps the
  concentration and skips FAILED_DAMAGE_CHECK; the owner must log the rescue
  and schedule the later end itself (an expiring condition whose
  effect_expiring hook calls concentration.end_copy(engine, actor,
  started_sequence, reason)). The failed roll stays recorded. No subscriber
  keeps the historical ending. Shield Soul Never Falls (auto/shield
  shield_incarnation): when the concentration is on a Shield talent, offer
  "maintain" in use(); answer "MAINTAIN" only when chosen."""
