"""Durable physical item state (ITEMLIFE1):
  object_state_record(object, engine) -> object | None is a pure sequential
  transform before native _update_object validates/stores/journals an upsert.
  Default None preserves the supplied record. Inventory retirement projects
  destroyed/zero HP here; unrelated objects are unchanged. Optional upsert
  payload metadata (e.g. damage) cannot override the canonical object field.
  objects.deal shares the native upsert rather than a direct store/event path."""
