"""Temporary map-image protocol (Athletics map and interception consumers):
  RuntimeObjectState.component.map_marker=1 opts into nonphysical table
  projection with no AC/HP; native object geometry and senses.perceives_object
  govern visibility. _update_object and the native OBJECT_UPDATED reducer route
  these records to state.map_images, keeping physical state.objects consumers
  (occupied squares, damage, inventory) unchanged. The empty collection is
  omitted from serialization. No marker means existing object storage/projection.
  Native state_event(engine, event) creates/removes owned images through
  CONDITION_UPDATED and OBJECT_UPDATED, preserving journal/reducer replay.
  combat.ext.afterimage_targeting.image_for_condition(engine, owner, condition)
  and perceived_image(engine, viewer, owner) are pure, default-None identity
  queries. condition.data.image_object_id binds owner_id, condition_instance_id
  and source_definition_id; component.intent_id names the creating intent.
  destroy_image(engine, image_object_id, source_definition_id, actor_id,
  intent_id=None) -> bool records exact-image destruction and native condition
  removal; stale/mismatched/missing images are inert. Public sibling parameters
  and receipts are primitive strings, never hidden creature facts. These helpers
  do not resolve attack/nonattack interception, movement admission or a d2."""
