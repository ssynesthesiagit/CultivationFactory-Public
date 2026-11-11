"""object_hp_floor(engine, actor, obj, taken, source) -> None or integer HP floor.
  Shared object destruction protection, used by Banner's Imperial Standard.
  objects.deal calls it strictly after defenses/thresholds and before HP commit.
  Floors must be 0..maximum_hp, combine by maximum, cannot heal and do not
  create immunity. Missing subscribers preserve ordinary object damage.
"""
