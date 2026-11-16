"""General repeat-save resolution (gate2_engine.py resolve_repeat_save):
  Public engine.resolve_repeat_save(holder, instance_id, condition, save,
  checkpoint) accepts the exact held condition, original save ability/DC and
  trigger name. Optional keyword extra_mode supplies a granted roll mode;
  roll_source identifies the granting ability in SAVE_ROLLED only. Both default
  to None; source ownership and normal success settlement remain unchanged.
  The optional _roll_save receipt_source_id records original_save_source_id on
  that receipt; save mode/bonus/outcome hooks and the d20 scope still receive the
  original effect source. Omitted receipt attribution preserves native events.
  ModifierInstance.origin_save optionally stores the native saving ability/DC
  for a source-owned modifier. _add_modifier(..., origin_save=...) defaults to
  None and omits the field on ordinary rows; typed attack-mode penalties retain
  their actual save provenance for external penalty consumers.
  Both native turn expiry and event-triggered condition rechecks
  use it; charm_rules' repeat_on_ally_harm passes checkpoint ALLY_HARM. No
  ability ID enters core. Event subscribers retain their predicates/defaults.
  Each condition repeat builds one transient resolution dict
  {holder_id, instance_id, condition_id, source_definition_id,
  source_actor_id (the original caster), ability, dc, named, source_sphere,
  source_categories, checkpoint,
  roll, success, settled_by}; never saved.
  source_sphere and source_categories classify the originating action, not the
  holder or unrelated effects. source_sphere is its typed sphere ID or None;
  source_categories is a tuple of category:<tag> strings from the printed save
  rows that produce this exact condition, including nested outcome branches.
  Missing classification gives None and an empty tuple. Neither field infers
  categories from unrelated saves. They are transient resolution fields, never saved.

  Condition data repeat_save.named may hold a JSON list of consequence tags
  established by the condition provider for this exact repeat save. The engine
  merges these with the condition name into resolution.named and the native
  roll_context.named; save_mode readers can qualify the ongoing consequence.
  No tags means unchanged behavior; never infer tags from the whole action.
  repeat_save_scope(engine, resolution) -> context manager or None. Strict;
  entered before the roll and exited after the exact-instance
  removal, so deferred results (a granted move) run after it; it unwinds on
  player pauses and errors. Absent subscribers add nothing.
  repeat_save_failed(engine, resolution) -> None or {"result": "SUCCESS",
  "settled_by": source id}. Strict; asked once after a failed roll while
  the holder is active and the instance remains. One answer settles the
  save as a success: the failed die stays recorded and CONDITION_REMOVED
  adds settled_by. Any other answer raises; no answer keeps the failure.
  repeat_save_final(engine, resolution) -> None is a strict transactional
  notification after rewrites and condition settlement, still inside
  repeat_save_scope and before its deferred scope-exit results. resolution is
  the same transient dict above; success is the final boolean result and
  settled_by identifies any failed-save rescue. The failed die in roll remains
  recorded even when success becomes True. Providers may settle owned rewards
  in the enclosing transaction, but must not rewrite this result or infer failure
  from the original die. Exceptions unwind the transaction; no providers is
  default-inert. This is not a pure preview query and runs on either final result.

  Lucid Escape (auto/dreams dreams_lucid): register repeat_save_failed; find
  the holder's new save_escape row, require _printed_save(resolution
  ["named"]) and can_use_reaction(engine, holder, caster, row) with caster =
  engine.state.actors[resolution["source_actor_id"]]; ask with
  engine._active_intent, then pay inside _reaction_activation as the
  after_save path does. "succeed" and "end_effect" (this instance) answer
  SUCCESS with settled_by LUCID; for "move" also answer SUCCESS only if
  printed, and store the distance on a repeat_save_scope-owned scope keyed
  by holder_id so move_after runs at scope exit, after removal.
General reaction range query (ext/reaction_ranges.py reach):
  reaction_range_bonus(engine, actor, feature_id) -> nonnegative int or None
  is a strict pure query when typed_reactions generic eligibility or void_riders
  custom benefit reactions calculate their range. Replies add feet to base_ft;
  multiple providers add their bonuses. Exactly int is required (bool is invalid),
  and negative or malformed replies raise ValueError. Providers must gate on
  ownership and the requested feature_id and must not mutate, spend, roll, emit
  events or ask a controller. None contributes nothing; no replies preserves
  base_ft and is default-inert. It changes only range, not other eligibility."""
