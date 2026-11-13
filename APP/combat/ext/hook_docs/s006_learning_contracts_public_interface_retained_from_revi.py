"""Learning contracts (public interface retained from reviewed 4d78beec):
  learning_choices(sheet, sphere_id, talents, draft=None) -> list[choice] | None
  previews all source-owned choices, without mutating ownership or state.
  learning_receipt(sheet, kind, record_id, selected, talents) -> dict | None
  strictly validates one acquisition against its pre-learning sheet; exceptions
  abort acquisition. Receipts are saved atomically under the character lock.
  learning_projection(sheet, advancement) -> sheet projects stored grants;
  replay must not retest whether a proficiency was already known.
  owner_sheet_projection(sheet, combat_service, project_id) -> sheet projects
  durable external procedure results before compilation. Providers validate
  source ownership and must not create products while reading. Default inert.
  Journey actors' rest_preparations map holds completed procedure products;
  JourneyStore.actor_preparations returns a deep copy. journey_rest providers
  may populate this map only after the native eight-hour rest completes.
  committed_products(combat_service, engine) -> None synchronizes existing
  durable products after a successful manual/automatic commit, never preview.
  Providers are idempotent and default-inert for actors without their products.
  A provider that persists mutable product state must fence stale writers: only
  a strictly newer state revision of the same immutable identity may replace the
  durable product, so a stale parallel encounter cannot undo committed state.
  JourneyStore.update_preparation validates immutable creation identity before
  atomically updating an existing product; it cannot create an item or receipt.
condition_source_perceived(engine, holder, source, condition) -> None/bool.
Pure condition-upkeep query. With no answer charm_rules keeps its existing
source visibility rule. A printed alternative perception channel can return
True while it remains available; False rejects it. Multiple channels combine
with any(True). This does not bypass independent Hidden, damage or expiry
endings and stores no state. Catch the Eye supplies native hearing/voice and
sight/special-sense perception only for its own Captivated condition."""
